// Layout operations share the graph-core.js D3 selections and node data.
const MIN_READABLE_LABEL_PX = 11;

function graphNeighbours() {
    const adjacent = new Map(nodes.map(d => [d.id, []]));
    links.forEach(l => {
        const source = l.source.id || l.source, target = l.target.id || l.target;
        if (adjacent.has(source) && adjacent.has(target)) {
            adjacent.get(source).push(target);
            adjacent.get(target).push(source);
        }
    });
    return adjacent;
}

function labelBox(d, x = d.x, y = d.y) {
    const size = labelSizes.get(d.id) || {width: (d.name || '').length * 12, top: nodeRadius(d), bottom: nodeRadius(d) + 14};
    const radius = nodeRadius(d);
    return {left: x - Math.max(radius, size.width / 2) - 3,
        right: x + Math.max(radius, size.width / 2) + 3,
        top: y + Math.min(-radius, size.top) - 3,
        bottom: y + Math.max(radius, size.bottom) + 3};
}

function boxSize(d) {
    const b = labelBox(d, 0, 0);
    return {width: b.right - b.left, height: b.bottom - b.top};
}

function linkLength(l) {
    const a = boxSize(l.source), b = boxSize(l.target);
    const leaf = Math.min(nodeDegrees.get(l.source.id) || 0, nodeDegrees.get(l.target.id) || 0) <= 1;
    return (a.width + b.width) * (leaf ? 0.46 : 0.55) + (leaf ? 14 : 25);
}

function graphBounds(members = nodes) {
    const boxes = members.map(d => labelBox(d));
    return {left: Math.min(...boxes.map(b => b.left)), right: Math.max(...boxes.map(b => b.right)),
        top: Math.min(...boxes.map(b => b.top)), bottom: Math.max(...boxes.map(b => b.bottom))};
}

function mainNode(adjacent = graphNeighbours()) {
    return nodes.find(d => d.is_main_character || d.attributes?.is_main_character) ||
        nodes.reduce((best, d) => adjacent.get(d.id).length > adjacent.get(best.id).length ? d : best);
}

function boxesOverlap(a, b) {
    return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function placeNewNodes(restored) {
    const adjacent = graphNeighbours();
    const placed = nodes.filter(d => restored.has(d.id));
    const missing = nodes.filter(d => !restored.has(d.id));
    // Revisit nodes in neighbour order so chains grow from an existing anchor.
    missing.sort((a, b) => adjacent.get(b.id).filter(id => restored.has(id)).length -
        adjacent.get(a.id).filter(id => restored.has(id)).length);
    missing.forEach((d, index) => {
        const nearby = (adjacent.get(d.id) || []).map(id => nodes.find(n => n.id === id))
            .filter(n => n && Number.isFinite(n.fx) && Number.isFinite(n.fy));
        const centerX = nearby.length ? d3.mean(nearby, n => n.fx) : d3.mean(placed, n => n.x) || 0;
        const centerY = nearby.length ? d3.mean(nearby, n => n.fy) : d3.mean(placed, n => n.y) || 0;
        for (let attempt = 0; attempt < 500; attempt++) {
            const angle = (attempt + index) * 2.399963229728653;
            const distance = 70 + 28 * Math.sqrt(attempt);
            const x = centerX + distance * Math.cos(angle);
            const y = centerY + distance * Math.sin(angle);
            const box = labelBox(d, x, y);
            if (placed.every(other => !boxesOverlap(box, labelBox(other)))) {
                d.x = d.fx = x; d.y = d.fy = y;
                break;
            }
        }
        if (!Number.isFinite(d.fx)) {
            d.x = d.fx = centerX + 200 + index * 30;
            d.y = d.fy = centerY;
        }
        placed.push(d);
    });
}

function separateLabels(members = nodes, maxPasses = 50) {
    // The force collision is circular. This last bounded pass handles exact label rectangles.
    for (let pass = 0; pass < maxPasses; pass++) {
        let moved = false;
        for (let i = 0; i < members.length; i++) {
            const a = members[i];
            for (let j = i + 1; j < members.length; j++) {
                const b = members[j], ab = labelBox(a), bb = labelBox(b);
                if (!boxesOverlap(ab, bb)) continue;
                const dx = Math.min(ab.right - bb.left, bb.right - ab.left) + 2;
                const dy = Math.min(ab.bottom - bb.top, bb.bottom - ab.top) + 2;
                if (dx < dy) {
                    const direction = a.x <= b.x ? 1 : -1;
                    a.x -= direction * dx / 2; b.x += direction * dx / 2;
                } else {
                    const direction = a.y <= b.y ? 1 : -1;
                    a.y -= direction * dy / 2; b.y += direction * dy / 2;
                }
                moved = true;
            }
        }
        if (!moved) break;
    }
}

function compactForce(members, edges, durationMs = 650) {
    const ids = new Set(members.map(d => d.id));
    const local = edges.filter(l => ids.has(l.source.id || l.source) && ids.has(l.target.id || l.target));
    const sim = d3.forceSimulation(members)
        .force('link', d3.forceLink(local).id(d => d.id).distance(linkLength).strength(0.45))
        .force('charge', d3.forceManyBody().strength(-55 - 12 * Math.sqrt(members.length)).distanceMax(260))
        .force('x', d3.forceX(0).strength(0.035))
        .force('y', d3.forceY(0).strength(0.035))
        .velocityDecay(0.55).stop();
    const deadline = performance.now() + durationMs;
    for (let tick = 0; tick < 150 && performance.now() < deadline; tick++) sim.tick();
    sim.stop();
    separateLabels(members);
}

function radialLayout() {
    const adjacent = graphNeighbours();
    const root = mainNode(adjacent);
    const depth = new Map([[root.id, 0]]), parent = new Map(), queue = [root.id];
    for (let i = 0; i < queue.length; i++) {
        for (const id of adjacent.get(queue[i])) if (!depth.has(id)) {
            depth.set(id, depth.get(queue[i]) + 1); parent.set(id, queue[i]); queue.push(id);
        }
    }
    const maxDepth = Math.max(...depth.values());
    nodes.filter(d => !depth.has(d.id)).forEach(d => depth.set(d.id, maxDepth + 1));
    root.x = root.y = 0;
    const positions = new Map([[root.id, 0]]);
    let previousRadius = 0, previousHeight = boxSize(root).height;
    for (let ring = 1; ring <= maxDepth + 1; ring++) {
        const members = nodes.filter(d => depth.get(d.id) === ring);
        if (!members.length) continue;
        members.sort((a, b) => (positions.get(parent.get(a.id)) ?? 0) -
            (positions.get(parent.get(b.id)) ?? 0) || (nodeDegrees.get(b.id) || 0) - (nodeDegrees.get(a.id) || 0));
        const height = Math.max(...members.map(d => boxSize(d).height));
        const required = members.reduce((sum, d) => sum + boxSize(d).width + 5, 0) / (2 * Math.PI);
        const laneCount = ring === 1 ? 1 : Math.min(3, Math.ceil(required / (previousRadius + height + 15)));
        const lanes = Array.from({length: laneCount}, () => ({members: [], arc: 0}));
        for (const [, siblings] of d3.groups(members, d => parent.get(d.id) || d.id)) {
            const lane = lanes.reduce((best, candidate) => candidate.arc < best.arc ? candidate : best);
            lane.members.push(...siblings);
            lane.arc += siblings.reduce((sum, d) => sum + boxSize(d).width + 5, 0);
        }
        lanes.forEach(lane => {
            lane.members.sort((a, b) => (positions.get(parent.get(a.id)) ?? 0) -
                (positions.get(parent.get(b.id)) ?? 0));
            const radius = Math.max(previousRadius + (previousHeight + height) / 2 + 7,
                lane.arc / (2 * Math.PI));
            let cursor = -Math.PI / 2;
            lane.members.forEach(d => {
                const span = (boxSize(d).width + 5) / radius;
                const angle = cursor + span / 2;
                positions.set(d.id, angle);
                d.x = radius * Math.cos(angle); d.y = radius * Math.sin(angle);
                cursor += span;
            });
            previousRadius = radius; previousHeight = height;
        });
    }
}

function typeLayout() {
    const groups = [...d3.group(nodes, d => d.type || 'other')].map(([type, members]) => ({type, members}));
    const groupOf = new Map(nodes.map(d => [d.id, d.type || 'other']));
    groups.forEach(group => {
        group.members.forEach((d, i) => {
            const angle = i * 2.399963229728653, radius = 28 * Math.sqrt(i);
            d.x = radius * Math.cos(angle); d.y = radius * Math.sin(angle);
        });
        compactForce(group.members, links, Math.max(90, 600 / groups.length));
        group.box = graphBounds(group.members);
        group.area = (group.box.right - group.box.left) * (group.box.bottom - group.box.top);
        group.cross = links.filter(l => {
            const a = groupOf.get(l.source.id || l.source), b = groupOf.get(l.target.id || l.target);
            return a !== b && (a === group.type || b === group.type);
        }).length;
    });
    groups.sort((a, b) => b.cross - a.cross || b.area - a.area);
    const placed = [];
    groups.forEach(group => {
        const box = group.box, cx = (box.left + box.right) / 2, cy = (box.top + box.bottom) / 2;
        const connected = placed.map(p => ({p, weight: links.filter(l => {
            const a = groupOf.get(l.source.id || l.source), b = groupOf.get(l.target.id || l.target);
            return (a === group.type && b === p.group.type) || (b === group.type && a === p.group.type);
        }).length})).filter(v => v.weight);
        let best = null, bestScore = Infinity;
        for (let attempt = 0; attempt < 700; attempt++) {
            const angle = attempt * 2.399963229728653;
            const radius = attempt === 0 ? 0 : 24 * Math.sqrt(attempt);
            const x = radius * Math.cos(angle), y = radius * Math.sin(angle);
            const candidate = {left: box.left + x - cx - 8, right: box.right + x - cx + 8,
                top: box.top + y - cy - 8, bottom: box.bottom + y - cy + 8};
            if (placed.some(p => boxesOverlap(candidate, p.box))) continue;
            const score = connected.length ? connected.reduce((sum, v) => sum + v.weight * Math.hypot(x - v.p.x, y - v.p.y), 0) /
                connected.reduce((sum, v) => sum + v.weight, 0) : radius;
            if (score < bestScore) { bestScore = score; best = {x, y, box: candidate}; }
            if (best && attempt > 160) break;
        }
        if (!best) best = {x: placed.length * 300, y: 0, box: {left: box.left + placed.length * 300, right: box.right + placed.length * 300, top: box.top, bottom: box.bottom}};
        group.members.forEach(d => { d.x += best.x - cx; d.y += best.y - cy; });
        placed.push({group, ...best});
    });
}

function renderGraph() {
    positionLinks(link);
    linkLabel.attr('x', d => (edgeEndpoints(d).x1 + edgeEndpoints(d).x2) / 2)
        .attr('y', d => (edgeEndpoints(d).y1 + edgeEndpoints(d).y2) / 2);
    g.selectAll('.node-group').attr('transform', d => `translate(${d.x}, ${d.y})`);
}

function updateEdgeLabelVisibility(scale) {
    if (!linkLabel) return;
    const focus = selectedNode && selectedNode.datum();
    linkLabel.style('display', d => scale >= 1.5 || (focus &&
        ((d.source.id || d.source) === focus.id || (d.target.id || d.target) === focus.id)) ? null : 'none');
}

function fitGraphToView() {
    if (!svg || !zoom || !nodes.length) return;
    const bounds = graphBounds();
    const width = svg.node().clientWidth || window.innerWidth;
    const height = svg.node().clientHeight || window.innerHeight;
    const margin = 42, topMargin = 76;
    const fitted = Math.min(4, (width - 2 * margin) / Math.max(1, bounds.right - bounds.left),
        (height - topMargin - margin) / Math.max(1, bounds.bottom - bounds.top));
    const fontPx = parseFloat(getComputedStyle(label.node()).fontSize) || 12;
    const scale = Math.min(1.5, Math.max(MIN_READABLE_LABEL_PX / fontPx, fitted));
    const anchor = fitted >= scale ? {x: (bounds.left + bounds.right) / 2, y: (bounds.top + bounds.bottom) / 2} :
        window.currentLayoutKind === 'type' ? {x: d3.mean(nodes, d => d.x), y: d3.mean(nodes, d => d.y)} : mainNode();
    const transform = d3.zoomIdentity.translate(width / 2 - scale * anchor.x,
        topMargin + (height - topMargin - margin) / 2 - scale * anchor.y).scale(scale);
    svg.call(zoom.transform, transform);
}

function saveLayoutSoon() {
    pendingLayoutSave = true;
    clearTimeout(layoutSaveTimer);
    layoutSaveTimer = setTimeout(() => {
        if (!bridge || !bridge.saveLayout) return;
        bridge.saveLayout(JSON.stringify(Object.fromEntries(nodes.map(d => [d.id, {x: d.x, y: d.y}]))));
        pendingLayoutSave = false;
    }, 200);
}

function arrangeGraph(kind = 'auto') {
    if (!simulation || !nodes.length) return;
    document.getElementById('layoutMenu').hidden = true;
    document.getElementById('layoutMenuBtn').setAttribute('aria-expanded', 'false');
    const started = performance.now();
    window.currentLayoutKind = kind;
    simulation.stop();
    nodes.forEach(d => { d.fx = d.fy = null; });
    if (kind === 'radial') radialLayout();
    else if (kind === 'type') typeLayout();
    else {
        compactForce(nodes, links, nodes.length > 180 ? 1050 : 850);
    }
    separateLabels();
    nodes.forEach(d => { d.fx = d.x; d.fy = d.y; d.vx = d.vy = 0; });
    simulation.stop();
    physicsEnabled = false;
    const btn = document.querySelector('button[onclick="togglePhysics()"]');
    if (btn) { btn.textContent = '启动物理效果'; btn.classList.add('active'); }
    renderGraph();
    fitGraphToView();
    saveLayoutSoon();
    window.lastLayoutMetrics = {kind, durationMs: Math.round(performance.now() - started)};
}

function toggleLayoutMenu(event) {
    event.stopPropagation();
    const menu = document.getElementById('layoutMenu');
    menu.hidden = !menu.hidden;
    document.getElementById('layoutMenuBtn').setAttribute('aria-expanded', String(!menu.hidden));
}

document.addEventListener('click', event => {
    const control = document.querySelector('.layout-control');
    if (control && !control.contains(event.target)) {
        document.getElementById('layoutMenu').hidden = true;
        document.getElementById('layoutMenuBtn').setAttribute('aria-expanded', 'false');
    }
});
