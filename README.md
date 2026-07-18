# CodeGraph — Codebase Knowledge Graph

Point it at a Django/Python project and get back an **interactive
architecture graph**: URL flow, model relationships, function call graph,
dead code detection, and circular dependency detection — automatically.

Built with **Django** (backend, storage, upload handling) + Python's
built-in `ast` module (static analysis engine, zero third-party parsing
dependencies) + **vis-network** (frontend graph rendering) + plain HTML/CSS/JS.

## Quick start (2 minutes)

```bash
# 1. Create & activate a virtualenv (recommended)
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies (just Django)
pip install -r requirements.txt

# 3. Set up the database (stores scan results)
python manage.py migrate

# 4. Run the server
python manage.py runserver
```

Open **http://127.0.0.1:8000/** in your browser.

## Demoing it

1. Click **"Analyze sample project"** on the homepage — this scans the
   bundled `sample_project/` (a tiny Django app with models, views, urls,
   utils) and takes you straight to the graph.
2. On the graph page you'll see:
   - **Models** (purple diamonds) connected by their `ForeignKey` /
     `ManyToManyField` relations.
   - **URL routes** (pink triangles) pointing at the view functions/classes
     they route to.
   - **Function → function call edges** (green), computed by walking every
     function body for `Call` nodes and matching them back to defined
     functions/methods in the project.
   - A **dead code candidate** (`deprecated_export_view`, `legacy_tax_calculator`,
     etc.) — anything nothing else calls, isn't wired into `urls.py`, and
     isn't a framework-reserved method (`__init__`, `save`, `get`, ...).
   - A **circular import** between `utils.py` and `helpers.py` — highlighted
     in orange, with the exact cycle path listed in the left panel.
3. Click any node to open the right-hand detail panel: its source code,
   and every place it's called **from** (incoming) and everything it
   **calls** (outgoing).
4. Use the left panel to filter by node/edge type, search by name, or hit
   "Highlight dead code" / "Highlight circular imports" to jump straight
   to the interesting bits.
5. To analyze a real project instead: zip up any Django/Python codebase
   (exclude `venv/`, `node_modules/`, `.git/` — these are ignored anyway)
   and upload it from the homepage. Nothing is executed — every file is
   only parsed with `ast.parse`.

## How the analysis engine works

All the logic lives in `analyzer/services/code_scanner.py` — a single,
dependency-free `ProjectScanner` class:

1. **Discover** every `.py` file under the target root (skipping
   `migrations/`, `venv/`, `node_modules/`, etc).
2. **Pass 1 — register**: parse each file with `ast.parse` and register a
   node for the file itself, every top-level class (flagging Django
   `Model` subclasses and class-based views specially), and every
   function/method — capturing its source snippet via
   `ast.get_source_segment`.
3. **Pass 2 — edges**:
   - `import` / `from ... import ...` statements resolved against the
     project's own module paths → file-to-file import edges.
   - Class bases resolved against registered classes → inheritance edges.
   - `ForeignKey(...)` / `OneToOneField(...)` / `ManyToManyField(...)`
     assignments inside models → model relation edges.
   - `urls.py` → walks `path()` / `re_path()` calls, resolves the view
     argument (function reference or `SomeView.as_view()`) back to a
     registered node → URL routing edges.
   - Every function/method body is walked for `Call` nodes; the callee
     name is matched against all known function/method names in the
     project → call-graph edges (name-based heuristic — same trade-off
     real tools like `pyan`/`code2flow` make without a full type checker).
4. **Dead code detection**: any function/method with zero incoming
   `call`/`url`/`inherit` edges, that isn't a dunder method, a test, or a
   framework-reserved hook (`save`, `clean`, `get`, `post`,
   `get_context_data`, ...) is flagged.
5. **Circular import detection**: DFS with a recursion stack over the
   file-level import graph; any node on a back-edge is part of a cycle.
6. **Call summaries**: every node gets a precomputed `incoming` /
   `outgoing` edge list attached, so the frontend can show "who calls
   this / what this calls" instantly with zero extra requests.

The whole result (`{nodes, edges, stats}`) is stored as one `JSONField`
on a `Scan` row — one write, and the graph page renders it entirely
client-side.

## Project structure

```
codegraph/
├── manage.py
├── requirements.txt
├── codegraph/              # Django project settings/urls
├── analyzer/                # The app
│   ├── models.py             # Scan model (stores each analysis run)
│   ├── views.py              # index / analyze / graph_detail / history
│   ├── urls.py
│   ├── services/
│   │   └── code_scanner.py   # <-- the whole analysis engine
│   ├── templates/analyzer/
│   │   ├── base.html
│   │   ├── index.html        # upload / "analyze sample" screen
│   │   └── graph.html        # interactive graph + sidebar
│   └── static/analyzer/
│       ├── css/style.css
│       └── js/graph.js       # vis-network rendering + filters + detail panel
└── sample_project/          # Demo Django app the sample-scan analyzes
    ├── models.py             # Author, Book, Review, Tag + 1 dead function
    ├── views.py              # function + class-based views + 1 dead view
    ├── urls.py
    ├── utils.py              # <-> helpers.py = intentional circular import
    └── helpers.py
```

## Known limitations (be upfront about these in Q&A)

- Call-graph resolution is **name-based**, not type-resolved — if two
  unrelated classes both have a `save()` method, a call to one may show
  an edge to both. This is the same trade-off most static call-graph
  tools make without a full type checker; a future version could add
  confidence scores or type inference.
- Only Python is analyzed (no JS/HTML templates yet) — a natural
  "next step" to mention if asked about roadmap.
- Uploaded projects are parsed with `ast.parse` only — nothing is ever
  `exec`'d or imported, so it's safe to run on untrusted code.
