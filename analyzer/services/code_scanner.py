"""
code_scanner.py
================
Pure-Python (stdlib `ast` only, no third-party deps) engine that walks a
Django/Python codebase and builds a knowledge graph of it:

    - files
    - classes / Django models
    - functions / methods / views
    - urls.py routes

Edges represent: imports, class inheritance, model FK/M2M/O2O relations,
url -> view routing, and function/method call relationships (name-based
heuristic resolution - good enough for a hackathon demo, not a full
type-checker).

On top of the raw graph it computes:
    - dead code candidates   (functions/methods nothing calls)
    - circular imports       (cycles in the file-level import graph)

The public entry point is `scan_project(root_path)` which returns a
plain dict: {"nodes": [...], "edges": [...], "stats": {...}}
ready to be JSON-serialised and handed to the frontend.
"""
import ast
import os
from collections import defaultdict

DEFAULT_IGNORE_DIRS = {
    '__pycache__', '.git', 'venv', 'env', '.venv', 'node_modules',
    'migrations', 'staticfiles', 'dist', 'build', '.idea', '.vscode',
}

RELATION_CALL_NAMES = {'ForeignKey', 'OneToOneField', 'ManyToManyField'}

# Methods that Django/the framework calls implicitly - never flag as dead
FRAMEWORK_ENTRY_METHODS = {
    '__init__', '__str__', '__repr__', '__unicode__', 'save', 'delete',
    'clean', 'clean_fields', 'get_absolute_url', 'get_queryset', 'get_context_data',
    'get', 'post', 'put', 'patch', 'delete_', 'setUp', 'tearDown', 'ready',
    'get_form', 'get_form_kwargs', 'form_valid', 'form_invalid', 'get_success_url',
}

MAX_SNIPPET_CHARS = 4000


def _rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, '/')


def _safe_source(src_text, node, limit=MAX_SNIPPET_CHARS):
    try:
        seg = ast.get_source_segment(src_text, node)
    except Exception:
        seg = None
    if not seg:
        return ""
    if len(seg) > limit:
        return seg[:limit] + "\n# ... (truncated)"
    return seg


def _call_name(call_node):
    """Best-effort extraction of the 'name' being called for a Call node."""
    func = call_node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _base_name(base_node):
    if isinstance(base_node, ast.Name):
        return base_node.id
    if isinstance(base_node, ast.Attribute):
        return base_node.attr
    return None


def _string_const(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class ProjectScanner:
    def __init__(self, root_path, ignore_dirs=None):
        self.root = root_path
        self.ignore_dirs = ignore_dirs or DEFAULT_IGNORE_DIRS
        self.nodes = {}          # id -> node dict
        self.edges = []          # list of dicts {source, target, type, label}
        self.file_sources = {}   # relpath -> source text
        self.file_trees = {}     # relpath -> ast.Module
        self.func_by_simplename = defaultdict(list)   # simple name -> [node_id,...]
        self.class_by_name = {}                        # class name -> node_id (first match wins)
        self.errors = []

    # ------------------------------------------------------------------ #
    # Pass 0: discover files
    # ------------------------------------------------------------------ #
    def discover_files(self):
        py_files = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in self.ignore_dirs and not d.startswith('.')]
            for fn in filenames:
                if fn.endswith('.py'):
                    py_files.append(os.path.join(dirpath, fn))
        return sorted(py_files)

    # ------------------------------------------------------------------ #
    # Node helpers
    # ------------------------------------------------------------------ #
    def add_node(self, node_id, **kwargs):
        if node_id not in self.nodes:
            self.nodes[node_id] = {
                'id': node_id,
                'label': kwargs.get('label', node_id),
                'type': kwargs.get('type', 'file'),
                'file': kwargs.get('file', ''),
                'source': kwargs.get('source', ''),
                'dead': False,
                'in_cycle': False,
            }
        self.nodes[node_id].update({k: v for k, v in kwargs.items() if v is not None})
        return self.nodes[node_id]

    def add_edge(self, source, target, etype, label=''):
        if source == target:
            return
        # de-dup identical edges
        key = (source, target, etype, label)
        if not hasattr(self, '_edge_keys'):
            self._edge_keys = set()
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append({'source': source, 'target': target, 'type': etype, 'label': label})

    # ------------------------------------------------------------------ #
    # Pass 1: register files, classes, functions/methods
    # ------------------------------------------------------------------ #
    def pass1_register(self, py_files):
        for path in py_files:
            rel = _rel(path, self.root)
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    src = f.read()
                tree = ast.parse(src, filename=rel)
            except Exception as e:
                self.errors.append(f"{rel}: parse error - {e}")
                continue

            self.file_sources[rel] = src
            self.file_trees[rel] = tree

            file_id = f"file:{rel}"
            self.add_node(file_id, type='file', label=rel, file=rel)

            is_urls_file = os.path.basename(rel) == 'urls.py'
            is_views_file = os.path.basename(rel) == 'views.py'
            is_test_file = os.path.basename(rel).startswith('test')

            for node in tree.body:
                try:
                    if isinstance(node, ast.ClassDef):
                        self._register_class(node, rel, file_id, src)
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        kind = 'view' if is_views_file else ('test' if is_test_file else 'function')
                        fid = f"func:{rel}:{node.name}"
                        self.add_node(
                            fid, type=kind, label=f"{node.name}()", file=rel,
                            source=_safe_source(src, node), lineno=node.lineno,
                        )
                        self.add_edge(file_id, fid, 'contains')
                        self.func_by_simplename[node.name].append(fid)
                except Exception as e:
                    self.errors.append(f"{rel}: registration error near line {getattr(node, 'lineno', '?')} - {e}")

            if is_urls_file:
                self._pending_urls = getattr(self, '_pending_urls', [])
                self._pending_urls.append((tree, rel, file_id, src))

    def _register_class(self, node, rel, file_id, src):
        base_names = [n for n in (_base_name(b) for b in node.bases) if n]
        is_model = any(b in ('Model', 'AbstractUser', 'AbstractBaseUser') for b in base_names)
        is_view_class = any('View' in b for b in base_names)
        ctype = 'model' if is_model else ('view' if is_view_class else 'class')

        cid = f"class:{rel}:{node.name}"
        self.add_node(
            cid, type=ctype, label=node.name, file=rel,
            source=_safe_source(src, node), lineno=node.lineno, bases=base_names,
        )
        self.add_edge(file_id, cid, 'contains')
        if node.name not in self.class_by_name:
            self.class_by_name[node.name] = cid

        # inheritance edges resolved in pass2 (need all classes registered first)
        self.nodes[cid]['_base_names'] = base_names

        # methods + model fields
        model_fields = []  # (field_name, relation_call_name, target_name)
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mid = f"func:{rel}:{node.name}.{item.name}"
                self.add_node(
                    mid, type='method', label=f"{node.name}.{item.name}()", file=rel,
                    source=_safe_source(src, item), lineno=item.lineno, owner=cid,
                )
                self.add_edge(cid, mid, 'contains')
                self.func_by_simplename[item.name].append(mid)
            elif is_model and isinstance(item, ast.Assign):
                call = item.value
                if isinstance(call, ast.Call):
                    cname = _call_name(call)
                    if cname in RELATION_CALL_NAMES:
                        target = None
                        if call.args:
                            a0 = call.args[0]
                            if isinstance(a0, ast.Name):
                                target = a0.id
                            elif isinstance(a0, ast.Attribute):
                                target = a0.attr
                            else:
                                s = _string_const(a0)
                                if s:
                                    target = s.split('.')[-1]
                        field_name = item.targets[0].id if isinstance(item.targets[0], ast.Name) else '?'
                        model_fields.append((field_name, cname, target))
        if model_fields:
            self.nodes[cid]['_model_fields'] = model_fields

    # ------------------------------------------------------------------ #
    # Pass 2: imports, inheritance, model relations, urls
    # ------------------------------------------------------------------ #
    def pass2_edges(self):
        # module dotted-path -> relpath, so `from app.models import X` resolves
        module_to_rel = {}
        root_basename = os.path.basename(os.path.normpath(self.root))
        for rel in self.file_sources:
            dotted = rel[:-3].replace('/', '.')  # strip .py
            module_to_rel[dotted] = rel
            # Imports are often written relative to the *parent* of the scanned
            # root (e.g. `from sample_project.utils import x` while root ==
            # ".../sample_project"), so also register the root-prefixed form.
            module_to_rel[f"{root_basename}.{dotted}"] = rel
            if dotted.endswith('.__init__'):
                module_to_rel[dotted[:-9]] = rel
                module_to_rel[f"{root_basename}.{dotted[:-9]}"] = rel

        for rel, tree in self.file_trees.items():
            file_id = f"file:{rel}"
            try:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self._maybe_import_edge(file_id, alias.name, module_to_rel)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            self._maybe_import_edge(file_id, node.module, module_to_rel)
            except Exception as e:
                self.errors.append(f"{rel}: import scan error - {e}")

        # inheritance
        for cid, ndata in self.nodes.items():
            if ndata['type'] in ('class', 'model', 'view') and '_base_names' in ndata:
                try:
                    for b in ndata['_base_names']:
                        target = self.class_by_name.get(b)
                        if target:
                            self.add_edge(cid, target, 'inherit', label='extends')
                except Exception as e:
                    self.errors.append(f"{cid}: inheritance error - {e}")
                ndata.pop('_base_names', None)

        # model FK/O2O/M2M relations
        for cid, ndata in list(self.nodes.items()):
            if '_model_fields' in ndata:
                try:
                    for field_name, relation, target_name in ndata['_model_fields']:
                        target_id = self.class_by_name.get(target_name)
                        if target_id:
                            self.add_edge(cid, target_id, 'relation', label=f"{field_name} ({relation})")
                except Exception as e:
                    self.errors.append(f"{cid}: model relation error - {e}")
                ndata.pop('_model_fields', None)

        # urls.py -> view routing
        for tree, rel, file_id, src in getattr(self, '_pending_urls', []):
            try:
                self._register_urlpatterns(tree, rel, file_id, src)
            except Exception as e:
                self.errors.append(f"{rel}: urls.py scan error - {e}")

        # call graph (name-heuristic)
        try:
            self._build_call_graph()
        except Exception as e:
            self.errors.append(f"call graph error - {e}")

    def _maybe_import_edge(self, file_id, module_name, module_to_rel):
        if not module_name:
            return
        target_rel = module_to_rel.get(module_name)
        if not target_rel:
            # try progressively shorter dotted prefixes (handles `from . import models` style paths)
            parts = module_name.split('.')
            while parts and not target_rel:
                target_rel = module_to_rel.get('.'.join(parts))
                parts = parts[:-1]
        if target_rel:
            target_id = f"file:{target_rel}"
            if target_id != file_id:
                self.add_edge(file_id, target_id, 'import')

    def _register_urlpatterns(self, tree, rel, file_id, src):
        idx = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = _call_name(node)
                if fname not in ('path', 're_path', 'url'):
                    continue
                pattern = _string_const(node.args[0]) if node.args else '?'
                view_ref = node.args[1] if len(node.args) > 1 else None
                view_id, view_label = self._resolve_view(view_ref)
                idx += 1
                uid = f"url:{rel}:{idx}"
                self.add_node(
                    uid, type='url', label=f"/{(pattern or '').lstrip('/')}", file=rel,
                    source=_safe_source(src, node),
                )
                self.add_edge(file_id, uid, 'contains')
                if view_id and view_id in self.nodes:
                    self.add_edge(uid, view_id, 'url', label='routes to')
                elif view_label:
                    self.nodes[uid]['unresolved_view'] = view_label

    def _resolve_view(self, view_ref):
        """Return (node_id_or_None, human_label) for a urls.py view argument."""
        if view_ref is None:
            return None, None
        # views.func_name
        if isinstance(view_ref, ast.Attribute):
            name = view_ref.attr
            # class-based view: SomeView.as_view()
            if name == 'as_view' and isinstance(view_ref.value, ast.Name):
                cls = view_ref.value.id
                return self.class_by_name.get(cls), cls
            candidates = self.func_by_simplename.get(name, [])
            return (candidates[0] if candidates else None), name
        if isinstance(view_ref, ast.Call):
            # e.g. SomeView.as_view() or views.SomeView.as_view()
            fn = view_ref.func
            if isinstance(fn, ast.Attribute) and fn.attr == 'as_view':
                owner = fn.value
                cls = owner.id if isinstance(owner, ast.Name) else (
                    owner.attr if isinstance(owner, ast.Attribute) else None
                )
                if cls:
                    return self.class_by_name.get(cls), cls
            name = _call_name(view_ref)
            candidates = self.func_by_simplename.get(name, [])
            return (candidates[0] if candidates else None), name
        if isinstance(view_ref, ast.Name):
            name = view_ref.id
            candidates = self.func_by_simplename.get(name, [])
            if candidates:
                return candidates[0], name
            return self.class_by_name.get(name), name
        return None, None

    def _build_call_graph(self):
        for rel, tree in self.file_trees.items():
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner_class = None
                    caller_id = None
                    # figure out whether this def is a top-level func or a method
                    # (cheap approach: check our registered nodes)
                    top_id = f"func:{rel}:{node.name}"
                    if top_id in self.nodes and self.nodes[top_id]['type'] in ('function', 'view', 'test'):
                        caller_id = top_id
                    else:
                        # search method ids for this file matching this function name
                        for nid, ndata in self.nodes.items():
                            if ndata['type'] == 'method' and ndata['file'] == rel and nid.endswith(f".{node.name}"):
                                # only good match if this def node's lineno matches
                                if ndata.get('lineno') == node.lineno:
                                    caller_id = nid
                                    break
                    if not caller_id:
                        continue
                    for inner in ast.walk(node):
                        if isinstance(inner, ast.Call) and inner is not node:
                            cname = _call_name(inner)
                            if not cname or cname == node.name:
                                continue
                            for callee_id in self.func_by_simplename.get(cname, []):
                                self.add_edge(caller_id, callee_id, 'call')

    # ------------------------------------------------------------------ #
    # Pass 3: dead code detection
    # ------------------------------------------------------------------ #
    def detect_dead_code(self):
        incoming_count = defaultdict(int)
        for e in self.edges:
            if e['type'] in ('call', 'url', 'inherit'):
                incoming_count[e['target']] += 1

        dead_ids = []
        for nid, ndata in self.nodes.items():
            if ndata['type'] not in ('function', 'method', 'view'):
                continue
            simple_name = ndata['label'].split('.')[-1].rstrip('()')
            if simple_name in FRAMEWORK_ENTRY_METHODS:
                continue
            if simple_name.startswith('test') or ndata['type'] == 'test':
                continue
            if simple_name.startswith('__') and simple_name.endswith('__'):
                continue
            if incoming_count.get(nid, 0) == 0:
                ndata['dead'] = True
                dead_ids.append(nid)
        return dead_ids

    # ------------------------------------------------------------------ #
    # Pass 4: circular import detection (file-level import graph)
    # ------------------------------------------------------------------ #
    def detect_cycles(self):
        graph = defaultdict(set)
        for e in self.edges:
            if e['type'] == 'import':
                graph[e['source']].add(e['target'])

        visited = set()
        stack = []
        on_stack = set()
        cycles = []

        def dfs(u):
            visited.add(u)
            stack.append(u)
            on_stack.add(u)
            for v in graph.get(u, ()):
                if v not in visited:
                    dfs(v)
                elif v in on_stack:
                    # found a cycle - extract it from the stack
                    idx = stack.index(v)
                    cycle = stack[idx:] + [v]
                    cycles.append(cycle)
            stack.pop()
            on_stack.discard(u)

        for node_id in list(graph.keys()):
            if node_id not in visited:
                dfs(node_id)

        cyclic_nodes = set()
        cyclic_edge_pairs = set()
        for cyc in cycles:
            for i in range(len(cyc) - 1):
                cyclic_nodes.add(cyc[i])
                cyclic_edge_pairs.add((cyc[i], cyc[i + 1]))
            cyclic_nodes.add(cyc[-1])

        for nid in cyclic_nodes:
            if nid in self.nodes:
                self.nodes[nid]['in_cycle'] = True
        for e in self.edges:
            if (e['source'], e['target']) in cyclic_edge_pairs:
                e['in_cycle'] = True

        # de-duplicate cycles that are rotations of each other
        unique = []
        seen_sets = []
        for cyc in cycles:
            s = frozenset(cyc)
            if s not in seen_sets:
                seen_sets.append(s)
                unique.append([self.nodes[n]['label'] for n in cyc if n in self.nodes])
        return unique

    # ------------------------------------------------------------------ #
    # Pass 5: attach incoming/outgoing edge summaries to every node
    # ------------------------------------------------------------------ #
    def attach_call_summaries(self):
        incoming = defaultdict(list)
        outgoing = defaultdict(list)
        for e in self.edges:
            if e['source'] in self.nodes and e['target'] in self.nodes:
                outgoing[e['source']].append({
                    'id': e['target'], 'label': self.nodes[e['target']]['label'], 'type': e['type'],
                })
                incoming[e['target']].append({
                    'id': e['source'], 'label': self.nodes[e['source']]['label'], 'type': e['type'],
                })
        for nid, ndata in self.nodes.items():
            ndata['incoming'] = incoming.get(nid, [])
            ndata['outgoing'] = outgoing.get(nid, [])

    # ------------------------------------------------------------------ #
    def run(self):
        py_files = self.discover_files()
        self.pass1_register(py_files)
        self.pass2_edges()
        dead_ids = self.detect_dead_code()
        cycles = self.detect_cycles()
        self.attach_call_summaries()

        node_list = list(self.nodes.values())
        type_counts = defaultdict(int)
        for n in node_list:
            type_counts[n['type']] += 1

        stats = {
            'total_files': len(self.file_sources),
            'total_nodes': len(node_list),
            'total_edges': len(self.edges),
            'dead_code_count': len(dead_ids),
            'cycle_count': len(cycles),
            'cycles': cycles,
            'type_counts': dict(type_counts),
            'errors': self.errors,
        }
        return {'nodes': node_list, 'edges': self.edges, 'stats': stats}


def scan_project(root_path, ignore_dirs=None):
    scanner = ProjectScanner(root_path, ignore_dirs=ignore_dirs)
    return scanner.run()
