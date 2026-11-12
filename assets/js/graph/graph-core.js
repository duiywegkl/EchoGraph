const graphStyle = getComputedStyle(document.documentElement);
const graphColor = name => graphStyle.getPropertyValue('--' + name).trim();
const GRAPH_TYPE_COLORS = Object.fromEntries(['character','location','item','event','concept','other'].map(t => [t, graphColor(t)]));
function nodeRadius(d) {
    const degree = links.filter(l => (l.source.id || l.source) === d.id || (l.target.id || l.target) === d.id).length;
    return Math.min(22, 14 + Math.sqrt(degree) * 2);
}
function edgeEndpoints(d) {
    const dx = d.target.x - d.source.x;
    const dy = d.target.y - d.source.y;
    const distance = Math.hypot(dx, dy);
    const ux = distance ? dx / distance : 0;
    const uy = distance ? dy / distance : 0;
    const sourceOffset = Math.min(nodeRadius(d.source), distance / 2);
    const targetOffset = Math.min(nodeRadius(d.target) + 2, distance / 2);
    return {
        x1: d.source.x + ux * sourceOffset,
        y1: d.source.y + uy * sourceOffset,
        x2: d.target.x - ux * targetOffset,
        y2: d.target.y - uy * targetOffset
    };
}
function positionLinks(selection) {
    selection.each(function(d) {
        const edge = edgeEndpoints(d);
        d3.select(this).attr("x1", edge.x1).attr("y1", edge.y1)
            .attr("x2", edge.x2).attr("y2", edge.y2);
    });
}
function highlightNeighbours(focus) {
    if (!node || !link || !linkLabel) return;
    const id = value => value && (value.id || value);
    const neighbours = new Set(focus ? [focus.id] : []);
    if (focus) links.forEach(l => { if (id(l.source) === focus.id) neighbours.add(id(l.target)); if (id(l.target) === focus.id) neighbours.add(id(l.source)); });
    g.selectAll('.node-group').style('opacity', d => !focus || neighbours.has(d.id) ? 1 : .25);
    const incident = d => !!focus && (id(d.source) === focus.id || id(d.target) === focus.id);
    link.classed('active', incident)
        .style('opacity', d => !focus || incident(d) ? 1 : .25)
        .attr('marker-end', d => incident(d) ? 'url(#graphArrowActive)' : 'url(#graphArrow)');
    linkLabel.classed('active', incident)
        .style('opacity', d => !focus || incident(d) ? 1 : .3);
}
/**
 * EchoGraph 知识图谱可视化核心 JavaScript
 */

// 全局变量
let simulation, svg, g, node, link, label, linkLabel, zoom, tooltip;
let nodes = [];
let links = [];
let bridge = null;
let editMode = false;
let selectedNode = null;
let tempLine = null;
let physicsEnabled = true;
let currentCdnIndex = 0;
let loadStartTime = Date.now();

// CDN 列表
const cdnUrls = [
    'https://d3js.org/d3.v7.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js',
    'https://unpkg.com/d3@7/dist/d3.min.js',
    'https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js'
];

/**
 * 根据节点数量智能计算力参数
 */
function calculateForceParameters(nodeCount, linkCount) {
    // 更强的基础排斥力：根据节点数量动态调整，防止挤在一起
    let baseRepulsion;
    if (nodeCount <= 5) {
        baseRepulsion = -200;
    } else if (nodeCount <= 10) {
        baseRepulsion = -400;
    } else if (nodeCount <= 20) {
        baseRepulsion = -600;
    } else {
        baseRepulsion = -800 - (nodeCount - 20) * 20; // 节点越多，排斥力越强
    }

    // 碰撞半径：节点多时需要更大的半径避免重叠
    const collisionRadius = Math.round(Math.max(25, 35 + Math.log(Math.max(1, nodeCount)) * 5));

    // 连线距离：节点多时需要更长的距离拉开空间
    let linkDistance;
    if (nodeCount <= 10) {
        linkDistance = 100;
    } else if (nodeCount <= 20) {
        linkDistance = 120;
    } else {
        linkDistance = Math.round(140 + Math.log(nodeCount) * 10);
    }

    // 中心引力：只有当节点很少时才启用
    const needCenterForce = nodeCount < 5;
    const centerStrength = needCenterForce ? 0.05 : 0;

    console.log(`智能力参数 - 节点:${nodeCount}, 连线:${linkCount}`);
    console.log(`排斥力:${baseRepulsion}, 碰撞:${collisionRadius}, 连线:${linkDistance}, 中心:${centerStrength}`);

    return {
        repulsion: baseRepulsion,
        collisionRadius: collisionRadius,
        linkDistance: linkDistance,
        centerStrength: centerStrength
    };
}

/**
 * 更新力参数
 */
function updateForceParameters() {
    const params = calculateForceParameters(nodes.length, links.length);

    simulation.force("charge", d3.forceManyBody().strength(params.repulsion));
    simulation.force("collision", d3.forceCollide().radius(params.collisionRadius));
    simulation.force("link", d3.forceLink(links).id(d => d.id).distance(params.linkDistance));

    // 只在需要时添加中心引力
    if (params.centerStrength > 0) {
        simulation.force("x", d3.forceX(window.innerWidth / 2).strength(params.centerStrength));
        simulation.force("y", d3.forceY(window.innerHeight / 2).strength(params.centerStrength));
    } else {
        simulation.force("x", null);  // 移除中心引力
        simulation.force("y", null);
    }

    simulation.alpha(0.3).restart();
}

// 本地D3.js路径（支持从HTML注入绝对路径）
const localD3Path = (typeof window !== 'undefined' && window.localD3PathInjected) || './assets/js/d3.v7.min.js';

/**
 * 初始化图谱数据
 */
function initializeGraphData() {
    // 从window对象获取数据并赋值给全局变量
    if (window.graphNodes && window.graphLinks) {
        nodes = window.graphNodes;
        links = window.graphLinks;
        console.log('数据初始化完成:', nodes.length, '个节点,', links.length, '个连接');
    } else {
        console.warn('未找到图谱数据，使用空数组');
        nodes = [];
        links = [];
    }
}

/**
 * 初始化 WebChannel
 */
function initWebChannel() {
    console.log('初始化WebChannel...');
    if (typeof QWebChannel !== 'undefined') {
        new QWebChannel(qt.webChannelTransport, function (channel) {
            bridge = channel.objects.bridge;
            console.log('✅ WebChannel初始化成功');
            console.log('Bridge对象:', bridge);

            // 测试连接
            if (bridge && bridge.log) {
                bridge.log('WebChannel连接测试成功');
            }
        });
    } else {
        console.error('❌ QWebChannel不可用');
    }
}

/**
 * 检查CDN内容
 */
function checkCdnContent(url) {
    console.log(`🔍 检查CDN内容: ${url}`);

    fetch(url, {
        method: 'GET',
        mode: 'cors',
        cache: 'no-cache'
    })
    .then(response => {
        console.log(`📡 CDN响应状态: ${response.status} ${response.statusText}`);
        console.log(`📡 Content-Type: ${response.headers.get('content-type')}`);
        console.log(`📡 Content-Length: ${response.headers.get('content-length')}`);

        return response.text();
    })
    .then(content => {
        console.log(`📄 CDN内容长度: ${content.length} 字符`);
        console.log(`📄 前100字符:`, content.substring(0, 100));

        if (content.toLowerCase().includes('<html') || content.toLowerCase().includes('<!doctype')) {
            console.error(`❌ CDN返回HTML而非JavaScript: ${url}`);
            console.log('完整HTML内容:', content);
        } else if (content.includes('d3') && content.includes('function')) {
            console.log(`✅ CDN内容看起来是有效的JavaScript: ${url}`);
        } else {
            console.warn(`⚠️  CDN内容类型未知: ${url}`);
            console.log('内容预览:', content.substring(0, 500));
        }
    })
    .catch(error => {
        console.error(`❌ 无法获取CDN内容: ${url}`, error);
        console.error('Fetch错误类型:', error.name);
        console.error('Fetch错误信息:', error.message);
    });
}

/**
 * 尝试加载本地D3.js文件
 */
function tryLoadLocalD3() {
    console.log('🏠 尝试加载本地D3.js文件:', localD3Path);

    const script = document.createElement('script');
    script.src = localD3Path;
    script.timeout = 5000;

    const loadTimer = setTimeout(() => {
        console.warn('本地D3.js加载超时');
        script.onerror();
    }, 5000);

    script.onload = function() {
        clearTimeout(loadTimer);
        console.log('✅ 本地D3.js加载成功！');
        console.log('D3版本:', typeof d3 !== 'undefined' ? d3.version : 'undefined');

        if (typeof d3 === 'undefined') {
            console.error('本地脚本加载了但是d3对象未定义');
            showFallback();
            return;
        }

        hideLoading();
        try {
            initializeGraph();
        } catch (error) {
            console.error('初始化图谱失败:', error);
            showFallback();
        }
    };

    script.onerror = function() {
        clearTimeout(loadTimer);
        console.error('❌ 本地D3.js文件不存在或加载失败');
        console.log('💡 建议: 下载D3.js到', localD3Path);
        console.log('🎨 显示简化版本图谱...');
        showFallback();
    };

    document.head.appendChild(script);
}

/**
 * 加载D3脚本
 */
function loadD3Script() {
    console.log('⚠️  检测到网络访问受限，CDN无法访问');
    console.log('🔄 跳过CDN，直接尝试本地D3.js文件');
    tryLoadLocalD3();
}

/**
 * 隐藏加载动画
 */
function hideLoading() {
    console.log('隐藏加载动画，显示图谱');
    document.getElementById('loading').style.display = 'none';
    document.getElementById('graphContainer').style.display = 'block';
    document.getElementById('controls').style.display = 'block';
}

/**
 * 显示简化版本
 */
function showFallback() {
    console.log('显示简化版本');
    document.getElementById('loading').style.display = 'none';
    document.getElementById('fallback').style.display = 'flex';
    generateEntityCards();
}

/**
 * 生成实体卡片
 */
function generateEntityCards() {
    // 确保数据已初始化
    if (nodes.length === 0) {
        initializeGraphData();
    }

    const entityGrid = document.getElementById('entityGrid');
    const typeColors = GRAPH_TYPE_COLORS;

    const typeNames = {character:'角色',location:'地点',item:'物品',event:'事件',concept:'概念',other:'其他'};
    let cardsHtml = '';
    nodes.forEach(node => {
        const color = typeColors[node.type] || GRAPH_TYPE_COLORS.other;
        cardsHtml += `
            <div class="entity-card" style="border-color: ${color};">
                <div class="entity-type" style="color: ${color};">${typeNames[node.type] || typeNames.other}</div>
                <div class="entity-name">${node.name}</div>
                <div class="entity-desc">${node.description || '暂无描述'}</div>
            </div>
        `;
    });

    entityGrid.innerHTML = cardsHtml;
    console.log('实体卡片生成完成');
}

/**
 * 初始化图谱
 */
function initializeGraph() {
    console.log('开始初始化图谱');

    // 首先初始化数据
    initializeGraphData();

    try {
        svg = d3.select("#graph");
        console.log('SVG元素选择成功');

        const width = window.innerWidth;
        const height = window.innerHeight;
        console.log(`画布尺寸: ${width}x${height}`);

        svg.attr("width", width).attr("height", height);

        const defs = svg.append("defs");
        [["graphArrow", "rgba(232,227,217,.32)"],
         ["graphArrowActive", "rgba(232,227,217,.75)"]].forEach(([id, fill]) => {
            defs.append("marker").attr("id", id).attr("viewBox", "0 -4 8 8")
                .attr("refX", 8).attr("refY", 0).attr("markerWidth", 8)
                .attr("markerHeight", 8).attr("markerUnits", "userSpaceOnUse")
                .attr("orient", "auto")
                .append("path").attr("d", "M0,-4L8,0L0,4Z").attr("fill", fill);
        });
        g = svg.append("g");
        console.log('创建SVG组元素');

        // 缩放行为
        zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on("zoom", (event) => {
                g.attr("transform", event.transform);
            });

        svg.call(zoom);
        console.log('缩放行为设置完成');

        // 力导向布局 - 使用智能参数
        const params = calculateForceParameters(nodes.length, links.length);

        simulation = d3.forceSimulation(nodes)
            .force("link", d3.forceLink(links).id(d => d.id).distance(params.linkDistance))
            .force("charge", d3.forceManyBody().strength(params.repulsion))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collision", d3.forceCollide().radius(params.collisionRadius))
            .alphaDecay(0.02)     // 更慢的衰减
            .velocityDecay(0.8);  // 增加阻尼

        // 只在需要时添加中心引力
        if (params.centerStrength > 0) {
            simulation.force("x", d3.forceX(width / 2).strength(params.centerStrength));
            simulation.force("y", d3.forceY(height / 2).strength(params.centerStrength));
        }

        console.log('力导向布局创建完成');

        // 创建连线
        link = g.append("g")
            .selectAll("line")
            .data(links)
            .join("line")
            .attr("class", "link editable-link")
            .attr("marker-end", "url(#graphArrow)");

        console.log(`创建了 ${links.length} 条连线`);

        // 添加关系标签
        linkLabel = g.append("g")
            .selectAll("text")
            .data(links)
            .join("text")
            .attr("class", "relation-label")
            .text(d => d.relation || "关联")
            .style("cursor", "pointer");

        // 创建节点组（包含圆圈和文字）
        const nodeGroup = g.append("g")
            .selectAll("g")
            .data(nodes)
            .join("g")
            .attr("class", "node-group")
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended));

        // 在节点组中添加圆圈
        node = nodeGroup.append("circle")
            .attr("class", d => `node ${d.type}`)
            .attr("r", d => nodeRadius(d));

        // 在节点组中添加文字标签
        label = nodeGroup.append("text")
            .attr("class", "node-label")
            .attr("dy", d => nodeRadius(d) + 12)
            .style("pointer-events", "none")
            .text(d => d.name);
        console.log(`创建了 ${nodes.length} 个节点`);

        // 工具提示
        tooltip = d3.select("#tooltip");

        setupEventHandlers(nodeGroup);
        setupSimulation();
        setupSliderListeners();

        console.log('✅ 图谱初始化完成！');

    } catch (error) {
        console.error('图谱初始化过程中发生错误:', error);
        console.error('错误堆栈:', error.stack);
        throw error;
    }
}

/**
 * 设置事件处理器
 */
function setupEventHandlers(nodeGroup) {
    // 节点鼠标悬停
    nodeGroup.on("mouseover", (event, d) => {
        highlightNeighbours(d);
        tooltip.style("opacity", 1)
            .html(`<strong>${d.name}</strong><br/>
                   类型: ${d.type}<br/>
                   描述: ${d.description || '暂无描述'}`)
            .style("left", (event.pageX + 10) + "px")
            .style("top", (event.pageY - 10) + "px");
    })
    .on("mouseout", () => {
        tooltip.style("opacity", 0);
        highlightNeighbours(selectedNode ? selectedNode.datum() : null);
    });

    // 节点点击事件
    nodeGroup.on("click", function(event, d) {
        event.stopPropagation();
        console.log('节点被点击:', d.name, '编辑模式:', editMode, '已选中节点:', selectedNode ? selectedNode.datum().name : 'none');

        if (editMode) {
            handleRelationEdit(d, d3.select(this));
        } else if (bridge && bridge.editNode) {
            bridge.editNode(d.name, d.type);
        }
    });

    // 关系连线和标签点击编辑
    link.on("click", function(event, d) {
        event.stopPropagation();
        if (editMode) openRelationEditDialog(d);
    });

    linkLabel.on("click", function(event, d) {
        event.stopPropagation();
        if (editMode) openRelationEditDialog(d);
    });

    // SVG点击取消选择
    svg.on("click", function(event) {
        if (editMode && event.target === this) {
            clearSelection();
        }
    });

    // 窗口大小改变
    window.addEventListener('resize', () => {
        const newWidth = window.innerWidth;
        const newHeight = window.innerHeight;
        console.log(`窗口大小改变: ${newWidth}x${newHeight}`);
        svg.attr("width", newWidth).attr("height", newHeight);

        // 更新所有与位置相关的力
        simulation.force("center", d3.forceCenter(newWidth / 2, newHeight / 2));
        simulation.force("x", d3.forceX(newWidth / 2).strength(0.05));
        simulation.force("y", d3.forceY(newHeight / 2).strength(0.05));
        simulation.alpha(0.3).restart();
    });
}

/**
 * 设置力学模拟
 */
function setupSimulation() {
    simulation.on("tick", () => {
        positionLinks(link);

        linkLabel.attr("x", d => {
            const edge = edgeEndpoints(d);
            return (edge.x1 + edge.x2) / 2;
        }).attr("y", d => {
            const edge = edgeEndpoints(d);
            return (edge.y1 + edge.y2) / 2;
        });

        // 更新节点组位置（包含圆圈和文字）
        g.selectAll(".node-group")
            .attr("transform", d => `translate(${d.x}, ${d.y})`);
    });
}

/**
 * 拖拽函数
 */
function dragstarted(event, d) {
    if (physicsEnabled) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
    }
    d.fx = d.x;
    d.fy = d.y;
}

function dragged(event, d) {
    d.fx = event.x;
    d.fy = event.y;

    // 立即更新数据位置
    d.x = event.x;
    d.y = event.y;

    // 立即更新节点组位置（包含圆圈和文字）
    d3.select(this).attr("transform", `translate(${d.x}, ${d.y})`);

    // 立即更新相关的连线
    positionLinks(link.filter(l => l.source.id === d.id || l.target.id === d.id));

    // 立即更新连线标签位置
    linkLabel.filter(l => l.source.id === d.id || l.target.id === d.id)
        .attr("x", l => {
            const edge = edgeEndpoints(l);
            return (edge.x1 + edge.x2) / 2;
        })
        .attr("y", l => {
            const edge = edgeEndpoints(l);
            return (edge.y1 + edge.y2) / 2;
        });
}

function dragended(event, d) {
    if (physicsEnabled) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
    } else {
        d.fx = event.x;
        d.fy = event.y;
        console.log(`节点 ${d.name} 固定在位置: (${event.x}, ${event.y})`);
    }
}

/**
 * 控制函数
 */
window.resetZoom = function() {
    console.log('重置视图');
    svg.transition().duration(750).call(
        zoom.transform,
        d3.zoomIdentity.translate(0, 0).scale(1)
    );
}


// 聚焦并高亮指定节点（按 id 或 name 匹配）
window.focusNodeById = function(nodeId) {
    try {
        if (!node || !svg || !zoom) return false;
        const sel = node.filter(d => d.id === nodeId || d.name === nodeId);
        if (sel.empty()) return false;
        // 取消其他选中并高亮当前
        node.classed('selected-node', false);
        sel.classed('selected-node', true);
        // 计算目标位置（取力导坐标）
        const coords = sel.nodes().map(n => ({x: n.__data__.x || 0, y: n.__data__.y || 0}));
        const cx = d3.mean(coords, p => p.x);
        const cy = d3.mean(coords, p => p.y);
        const width = svg.node().clientWidth;
        const height = svg.node().clientHeight;
        const transform = d3.zoomIdentity.translate(width / 2 - cx, height / 2 - cy).scale(1.2);
        svg.transition().duration(600).call(zoom.transform, transform);
        return true;
    } catch (e) {
        console.warn('focusNodeById failed:', e);
        return false;
    }
}

window.togglePhysics = function() {
    const btn = document.querySelector('button[onclick="togglePhysics()"]');

    if (physicsEnabled) {
        console.log('关闭物理效果（仍可拖动但不弹跳）');
        physicsEnabled = false;
        btn.textContent = '启动物理效果';
        btn.classList.toggle('active');
        simulation.stop();
    } else {
        console.log('启动物理效果');
        physicsEnabled = true;
        btn.textContent = '关闭物理效果';
        btn.classList.toggle('active');
        simulation.alpha(0.3).restart();
    }
}

window.toggleForcePanel = function() {
    const panel = document.getElementById('forcePanel');
    const btn = document.getElementById('forcePanelBtn');

    if (panel.style.display === 'none') {
        panel.style.display = 'block';
        btn.textContent = '隐藏调节';
        btn.classList.toggle('active');

        // 更新滑块值为当前参数
        updateSliderValues();
    } else {
        panel.style.display = 'none';
        btn.textContent = '调节力度';
        btn.classList.toggle('active');
    }
}

window.refreshGraphFromHost = function() {
    if (typeof bridge !== 'undefined' && bridge && bridge.refreshGraph) {
        bridge.refreshGraph();
    } else {
        location.reload();
    }
}

window.resetToSmart = function() {
    console.log('重置为智能参数');
    updateForceParameters();
    updateSliderValues();
}

window.applyForceChanges = function() {
    const repulsion = parseFloat(document.getElementById('repulsionSlider').value);
    const linkDistance = parseFloat(document.getElementById('linkDistanceSlider').value);
    const collision = parseFloat(document.getElementById('collisionSlider').value);
    const centerStrength = parseFloat(document.getElementById('centerStrengthSlider').value);

    console.log('应用自定义力参数:', { repulsion, linkDistance, collision, centerStrength });

    // 更新力参数
    simulation.force("charge", d3.forceManyBody().strength(repulsion));
    simulation.force("collision", d3.forceCollide().radius(collision));
    simulation.force("link", d3.forceLink(links).id(d => d.id).distance(linkDistance));

    // 中心引力
    if (centerStrength > 0) {
        simulation.force("x", d3.forceX(window.innerWidth / 2).strength(centerStrength));
        simulation.force("y", d3.forceY(window.innerHeight / 2).strength(centerStrength));
    } else {
        simulation.force("x", null);
        simulation.force("y", null);
    }

    simulation.alpha(0.3).restart();
}

function updateSliderValues() {
    const params = calculateForceParameters(nodes.length, links.length);

    document.getElementById('repulsionSlider').value = params.repulsion;
    document.getElementById('repulsionValue').textContent = Math.round(params.repulsion);

    document.getElementById('linkDistanceSlider').value = params.linkDistance;
    document.getElementById('linkDistanceValue').textContent = Math.round(params.linkDistance);

    document.getElementById('collisionSlider').value = params.collisionRadius;
    document.getElementById('collisionValue').textContent = Math.round(params.collisionRadius);

    document.getElementById('centerStrengthSlider').value = params.centerStrength;
    document.getElementById('centerStrengthValue').textContent = params.centerStrength.toFixed(2);
}

function setupSliderListeners() {
    // 实时更新显示值
    document.getElementById('repulsionSlider').oninput = function() {
        document.getElementById('repulsionValue').textContent = this.value;
    };

    document.getElementById('linkDistanceSlider').oninput = function() {
        document.getElementById('linkDistanceValue').textContent = this.value;
    };

    document.getElementById('collisionSlider').oninput = function() {
        document.getElementById('collisionValue').textContent = this.value;
    };

    document.getElementById('centerStrengthSlider').oninput = function() {
        document.getElementById('centerStrengthValue').textContent = parseFloat(this.value).toFixed(2);
    };
}

window.toggleEditMode = function() {
    console.log('=== toggleEditMode 函数被调用 ===');
    console.log('当前 editMode 值:', editMode);
    console.log('即将切换为:', !editMode);

    editMode = !editMode;
    console.log('新的 editMode 值:', editMode);

    const btn = document.getElementById('editModeBtn');
    console.log('找到按钮元素:', btn);

    if (!btn) {
        console.error('❌ 找不到编辑按钮元素！');
        return;
    }

    if (editMode) {
        console.log('✅ 进入关系编辑模式');
        btn.textContent = '退出编辑';
        btn.classList.toggle('active');
        svg.classed('editing-mode', true);
    } else {
        console.log('✅ 退出关系编辑模式');
        btn.textContent = '编辑关系';
        btn.classList.toggle('active');
        svg.classed('editing-mode', false);
        clearSelection();
    }
}

/**
 * 清除选择状态
 */
function clearSelection() {
    if (selectedNode) {
        selectedNode.classed('selected-node', false);
        selectedNode = null;
    }
    if (tempLine) {
        tempLine.remove();
        tempLine = null;
    }
    highlightNeighbours(null);
}

/**
 * 处理关系编辑
 */
function handleRelationEdit(nodeData, nodeElement) {
    if (!selectedNode) {
        selectedNode = nodeElement;
        selectedNode.classed('selected-node', true);
        highlightNeighbours(nodeData);
        return;
    }
    const sourceData = selectedNode.datum();
    clearSelection();
    if (sourceData.id === nodeData.id) return;
    const existingLink = links.find(link =>
        link.source.id === sourceData.id && link.target.id === nodeData.id);
    if (existingLink) {
        openRelationEditDialog(existingLink);
    } else {
        relationDialog(`${sourceData.name} → ${nodeData.name}`, '', false, value => {
            if (bridge && bridge.createRelationship) bridge.createRelationship(sourceData.id, nodeData.id, value);
        });
    }
}

function relationDialog(title, current, canDelete, onSave, onDelete) {
    const overlay = document.createElement('div');
    overlay.className = 'relation-dialog-overlay';
    const card = document.createElement('div');
    card.className = 'relation-dialog';
    const heading = document.createElement('h3');
    heading.textContent = title;
    const input = document.createElement('input');
    input.type = 'text';
    input.value = current;
    input.placeholder = '关系类型';
    const buttons = document.createElement('div');
    buttons.className = 'relation-dialog-actions';
    const makeButton = (label, action, cssClass) => {
        const button = document.createElement('button');
        button.textContent = label;
        if (cssClass) button.className = cssClass;
        button.onclick = action;
        buttons.appendChild(button);
    };
    const close = () => overlay.remove();
    makeButton('取消', close);
    if (canDelete) makeButton('删除关系', () => { close(); onDelete(); }, 'danger');
    makeButton('保存', () => {
        const value = input.value.trim();
        if (!value) { input.focus(); return; }
        close();
        if (value !== current) onSave(value);
    }, 'primary');
    input.onkeydown = event => {
        if (event.key === 'Enter') buttons.lastChild.click();
        if (event.key === 'Escape') close();
    };
    card.append(heading, input, buttons);
    overlay.append(card);
    document.body.append(overlay);
    input.focus();
    input.select();
}

function openRelationEditDialog(linkData) {
    const source = linkData.source.id || linkData.source;
    const target = linkData.target.id || linkData.target;
    relationDialog(`${source} → ${target}`, linkData.relation || '', true,
        value => { if (bridge && bridge.updateRelationship) bridge.updateRelationship(source, target, value); },
        () => { if (bridge && bridge.deleteRelationship) bridge.deleteRelationship(source, target); });
}

/**
 * 更新可视化
 */
function updateVisualization() {
    const linkSelection = g.select("g").selectAll("line")
        .data(links);

    const newLinks = linkSelection.enter()
        .append("line")
        .attr("class", "link editable-link")
        .attr("marker-end", "url(#graphArrow)");

    newLinks.on("click", function(event, d) {
        if (!editMode) return;
        event.stopPropagation();
        openRelationEditDialog(d);
    });

    link = linkSelection.merge(newLinks);

    const labelSelection = g.selectAll(".relation-label")
        .data(links);

    const newLabels = labelSelection.enter()
        .append("text")
        .attr("class", "relation-label")
        .style("cursor", "pointer");

    newLabels.on("click", function(event, d) {
        if (!editMode) return;
        event.stopPropagation();
        openRelationEditDialog(d);
    });

    linkLabel = labelSelection.merge(newLabels)
        .text(d => d.relation || "关联");
    highlightNeighbours(selectedNode ? selectedNode.datum() : null);

    simulation.nodes(nodes);
    simulation.force("link").links(links);
    simulation.alpha(0.3).restart();
}

/**
 * 调试函数
 */
window.debugGraph = function() {
    console.log('=== 图谱状态调试信息 ===');
    console.log('D3.js已加载:', typeof d3 !== 'undefined');
    console.log('nodes数组长度:', nodes ? nodes.length : 'undefined');
    console.log('links数组长度:', links ? links.length : 'undefined');
    console.log('editMode当前值:', editMode);
    console.log('selectedNode:', selectedNode);
    console.log('按钮元素:', document.getElementById('editModeBtn'));
    console.log('SVG元素:', svg ? svg.node() : 'undefined');
    console.log('node元素数量:', node ? node.size() : 'undefined');
    console.log('=========================');
};

// 页面加载初始化
if (document.readyState === 'loading') {
    console.log('等待DOM加载完成...');
    document.addEventListener('DOMContentLoaded', () => {
        console.log('DOM加载完成，初始化WebChannel和D3');
        initWebChannel();
        loadD3Script();
    });
} else {
    console.log('DOM已加载，立即初始化WebChannel和D3');
    initWebChannel();
    loadD3Script();
}

// 超时保护
setTimeout(() => {
    if (document.getElementById('loading').style.display !== 'none') {
        console.warn('30秒超时，强制显示简化版本');
        showFallback();
    }
}, 30000);