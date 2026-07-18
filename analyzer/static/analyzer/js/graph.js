(function () {
    const statusEl = document.getElementById('network-status');

    function showStatus(message, isError) {
        if (!statusEl) return;
        statusEl.textContent = message;
        statusEl.style.display = message ? 'flex' : 'none';
        statusEl.classList.toggle('network-status-error', !!isError);
    }

    let raw;
    try {
        raw = JSON.parse(document.getElementById('graph-data').textContent);
    } catch (e) {
        console.error('CodeGraph: failed to parse graph data', e);
        showStatus('Could not read the scan data for this graph. Try re-running the scan.', true);
        return;
    }

    const stats = raw.stats;

    document.getElementById('stat-files').textContent = stats.total_files;
    document.getElementById('stat-nodes').textContent = stats.total_nodes;
    document.getElementById('stat-edges').textContent = stats.total_edges;
    document.getElementById('stat-dead').textContent = stats.dead_code_count;
    document.getElementById('stat-cycles').textContent = stats.cycle_count;

    if (typeof vis === 'undefined') {
        console.error('CodeGraph: vis-network failed to load (check network/CDN access).');
        showStatus('The graph library failed to load — check your internet connection and reload the page.', true);
        return;
    }

    if (!raw.nodes || !raw.nodes.length) {
        showStatus('No nodes were found in this scan.', false);
        return;
    }

    if (stats.cycles && stats.cycles.length) {
        const block = document.getElementById('cycles-block');
        const list = document.getElementById('cycles-list');
        block.style.display = 'block';
        stats.cycles.forEach(cycle => {
            const div = document.createElement('div');
            div.className = 'cycle-item';
            div.textContent = cycle.join('  →  ');
            list.appendChild(div);
        });
    }

    const TYPE_COLOR = {
        file: '#94a3b8', model: '#a855f7', class: '#3b82f6', view: '#f59e0b',
        function: '#34d399', method: '#2dd4bf', url: '#fb7185', test: '#64748b',
    };
    const TYPE_SHAPE = {
        file: 'box', model: 'diamond', class: 'ellipse', view: 'ellipse',
        function: 'dot', method: 'dot', url: 'triangle', test: 'dot',
    };
    const EDGE_COLOR = {
        import: '#94a3b8', call: '#34d399', inherit: '#3b82f6',
        relation: '#a855f7', url: '#fb7185', contains: '#3a3f52',
    };

    const nodesById = {};
    raw.nodes.forEach(n => { nodesById[n.id] = n; });

    const visNodes = new vis.DataSet(raw.nodes.map(n => buildVisNode(n)));
    const visEdges = new vis.DataSet(raw.edges.map((e, i) => buildVisEdge(e, i)));

    function buildVisNode(n) {
        const color = TYPE_COLOR[n.type] || '#888';
        const size = n.type === 'file' ? 16 : (n.type === 'method' ? 8 : 12);
        const node = {
            id: n.id,
            label: n.label,
            shape: TYPE_SHAPE[n.type] || 'dot',
            size: size,
            font: { color: '#e7e9f0', size: 12, face: 'Segoe UI' },
            color: {
                background: color,
                border: n.dead ? '#f87171' : (n.in_cycle ? '#fbbf24' : color),
                highlight: { background: color, border: '#ffffff' },
            },
            borderWidth: (n.dead || n.in_cycle) ? 3 : 1,
            shapeProperties: { borderDashes: n.in_cycle ? [4, 3] : false },
            _type: n.type,
        };
        return node;
    }

    function buildVisEdge(e, i) {
        const color = EDGE_COLOR[e.type] || '#666';
        return {
            id: 'e' + i,
            from: e.source,
            to: e.target,
            color: { color: e.in_cycle ? '#fbbf24' : color, opacity: e.type === 'contains' ? 0.4 : 0.85 },
            width: e.in_cycle ? 2.5 : 1,
            dashes: e.type === 'contains' ? [2, 3] : (e.type === 'inherit'),
            arrows: e.type === 'import' ? '' : 'to',
            smooth: { type: 'continuous' },
            _type: e.type,
            hidden: e.type === 'contains',
        };
    }

    const container = document.getElementById('network');
    const data = { nodes: visNodes, edges: visEdges };
    const options = {
        physics: {
            solver: 'forceAtlas2Based',
            forceAtlas2Based: { gravitationalConstant: -60, springLength: 90, springConstant: 0.06, avoidOverlap: 0.4 },
            stabilization: { iterations: 200 },
        },
        interaction: { hover: true, tooltipDelay: 150 },
        layout: { improvedLayout: true },
    };
    let network;
    try {
        network = new vis.Network(container, data, options);
        showStatus('');
    } catch (e) {
        console.error('CodeGraph: failed to render the network graph', e);
        showStatus('Something went wrong rendering the graph. See the browser console for details.', true);
        return;
    }

    if (typeof network.once === 'function') {
        try { network.once('stabilized', function () { showStatus(''); }); } catch (e) { /* non-critical */ }
    }

    // ---------------- Detail panel ----------------
    const panel = document.getElementById('detail-panel');

    function renderDetail(nodeId) {
        const n = nodesById[nodeId];
        if (!n) return;
        const badgeColor = TYPE_COLOR[n.type] || '#888';

        let flags = '';
        if (n.dead) flags += '<span class="flag-dead">⚠ Dead code candidate</span>';
        if (n.in_cycle) flags += '<span class="flag-cycle">⟳ In circular import</span>';

        let sourceHtml = '';
        if (n.source) {
            sourceHtml = `<div class="detail-section"><h4>Source</h4><div class="detail-source">${escapeHtml(n.source)}</div></div>`;
        } else if (n.type === 'file') {
            sourceHtml = `<div class="detail-section"><h4>About</h4><p class="no-calls">This node represents the file <code>${escapeHtml(n.file)}</code>. Expand "Structure" edges in the left panel to see everything it contains.</p></div>`;
        }

        const incoming = n.incoming || [];
        const outgoing = n.outgoing || [];

        sourceHtml += buildCallSection('Incoming (who uses this)', incoming);
        sourceHtml += buildCallSection('Outgoing (what this uses)', outgoing);

        panel.innerHTML = `
            <span class="detail-type-badge" style="background:${badgeColor}22; color:${badgeColor};">${n.type}</span>
            <div class="detail-title">${escapeHtml(n.label)}</div>
            <div class="detail-file">${escapeHtml(n.file || '')}</div>
            <div class="detail-flags">${flags}</div>
            ${sourceHtml}
        `;

        panel.querySelectorAll('[data-goto]').forEach(el => {
            el.addEventListener('click', () => {
                const target = el.getAttribute('data-goto');
                network.selectNodes([target]);
                network.focus(target, { scale: 1.1, animation: true });
                renderDetail(target);
            });
        });
    }

    function buildCallSection(title, items) {
        if (!items.length) {
            return `<div class="detail-section"><h4>${title}</h4><p class="no-calls">None found.</p></div>`;
        }
        const rows = items.slice(0, 60).map(it =>
            `<li data-goto="${it.id}"><span>${escapeHtml(it.label)}</span><span class="call-type">${it.type}</span></li>`
        ).join('');
        return `<div class="detail-section"><h4>${title} (${items.length})</h4><ul class="call-list">${rows}</ul></div>`;
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str == null ? '' : str;
        return div.innerHTML;
    }

    network.on('click', function (params) {
        if (params.nodes.length) {
            renderDetail(params.nodes[0]);
        }
    });

    // ---------------- Filters: node types ----------------
    document.querySelectorAll('.type-toggle').forEach(cb => {
        cb.addEventListener('change', applyTypeFilters);
    });
    function applyTypeFilters() {
        const active = new Set(
            Array.from(document.querySelectorAll('.type-toggle:checked')).map(cb => cb.value)
        );
        const updates = raw.nodes.map(n => ({ id: n.id, hidden: !active.has(n.type) }));
        visNodes.update(updates);
    }

    // ---------------- Filters: edge types ----------------
    document.querySelectorAll('.edge-toggle').forEach(cb => {
        cb.addEventListener('change', applyEdgeFilters);
    });
    function applyEdgeFilters() {
        const active = new Set(
            Array.from(document.querySelectorAll('.edge-toggle:checked')).map(cb => cb.value)
        );
        const updates = raw.edges.map((e, i) => ({ id: 'e' + i, hidden: !active.has(e.type) }));
        visEdges.update(updates);
    }

    // ---------------- Search ----------------
    document.getElementById('search-input').addEventListener('input', function (e) {
        const q = e.target.value.trim().toLowerCase();
        if (!q) {
            visNodes.update(raw.nodes.map(n => ({ id: n.id, font: { color: '#e7e9f0', size: 12 } })));
            return;
        }
        const matches = [];
        const updates = raw.nodes.map(n => {
            const match = n.label.toLowerCase().includes(q);
            if (match) matches.push(n.id);
            return { id: n.id, font: { color: match ? '#ffffff' : '#4b5165', size: match ? 14 : 12 } };
        });
        visNodes.update(updates);
        if (matches.length) {
            network.fit({ nodes: matches, animation: true });
        }
    });

    // ---------------- Highlight buttons ----------------
    document.getElementById('btn-highlight-dead').addEventListener('click', function () {
        const deadIds = raw.nodes.filter(n => n.dead).map(n => n.id);
        if (!deadIds.length) { alert('No dead code candidates found in this scan 🎉'); return; }
        network.selectNodes(deadIds);
        network.fit({ nodes: deadIds, animation: true });
    });

    document.getElementById('btn-highlight-cycles').addEventListener('click', function () {
        const cycIds = raw.nodes.filter(n => n.in_cycle).map(n => n.id);
        if (!cycIds.length) { alert('No circular imports found in this scan 🎉'); return; }
        network.selectNodes(cycIds);
        network.fit({ nodes: cycIds, animation: true });
    });

    document.getElementById('btn-reset').addEventListener('click', function () {
        network.unselectAll();
        network.fit({ animation: true });
        document.getElementById('search-input').value = '';
        visNodes.update(raw.nodes.map(n => ({ id: n.id, font: { color: '#e7e9f0', size: 12 } })));
    });

    // apply the default edge filter (hide "contains" initially) on load
    applyEdgeFilters();
})();
