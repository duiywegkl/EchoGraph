/**
 * ChronoForge 知识图谱 JavaScript 逻辑
 * 基于 D3.js 的交互式图谱
 */

// 全局变量
let nodes = [];
let links = [];
let bridge = null;
let editMode = false;
let selectedNode = null;
let tempLine = null;
let physicsEnabled = true;
let simulation = null;

// 初始化WebChannel
function initWebChannel() {
    console.log('初始化WebChannel...');
    if (typeof QWebChannel !== 'undefined') {
        new QWebChannel(qt.webChannelTransport, function (channel) {
            bridge = channel.objects.bridge;
            console.log('✅ WebChannel初始化成功');
            
            if (bridge && bridge.log) {
                bridge.log('WebChannel连接测试成功');
            }
        });
    } else {
        console.error('❌ QWebChannel不可用');
    }
}

// 主初始化函数
function initializeGraphWithData(nodesData, linksData) {
    console.log('开始初始化图谱', nodesData, linksData);
    
    nodes = nodesData;
    links = linksData;
    
    // 初始化WebChannel
    initWebChannel();
    
    // 尝试加载D3.js
    loadD3Script();
}

// 加载D3.js库
function loadD3Script() {
    // 检查是否已经加载了D3
    if (typeof d3 !== 'undefined') {
        console.log('D3.js已存在，直接初始化');
        hideLoading();
        initializeGraph();
        return;
    }
    
    console.log('⚠️ 检测到网络访问受限，CDN无法访问');
    console.log('🔄 尝试本地D3.js文件');
    
    tryLoadLocalD3();
}

// 尝试加载本地D3.js文件
function tryLoadLocalD3() {
    const localD3Path = './assets/js/d3.v7.min.js';
    console.log('🏠 尝试加载本地D3.js文件:', localD3Path);
    
    const script = document.createElement('script');
    script.src = localD3Path;
    
    const loadTimer = setTimeout(() => {
        console.warn('本地D3.js加载超时');
        script.onerror();
    }, 5000);
    
    script.onload = function() {
        clearTimeout(loadTimer);
        console.log('✅ 本地D3.js加载成功！');
        
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

// 隐藏加载动画
function hideLoading() {
    console.log('隐藏加载动画，显示图谱');
    document.getElementById('loading').style.display = 'none';
    document.getElementById('graphContainer').style.display = 'block';
    document.getElementById('controls').style.display = 'block';
}

// 显示简化版本
function showFallback() {
    console.log('显示简化版本');
    document.getElementById('loading').style.display = 'none';
    document.getElementById('fallback').style.display = 'flex';
    
    generateEntityCards();
}

// 生成实体卡片
function generateEntityCards() {
    const entityGrid = document.getElementById('entityGrid');
    const typeColors = {
        'character': '#4a90e2',
        'location': '#27ae60', 
        'item': '#f39c12',
        'event': '#e74c3c',
        'concept': '#9b59b6'
    };
    
    let cardsHtml = '';
    nodes.forEach(node => {
        const color = typeColors[node.type] || '#9b59b6';
        cardsHtml += `
            <div class="entity-card" style="border-color: ${color};">
                <div class="entity-type" style="color: ${color};">[${node.type}]</div>
                <div class="entity-name">${node.name}</div>
                <div class="entity-desc">${node.description || '暂无描述'}</div>
            </div>
        `;
    });
    
    entityGrid.innerHTML = cardsHtml;
    console.log('实体卡片生成完成');
}

// 初始化D3图谱
function initializeGraph() {
    console.log('开始初始化图谱');
    
    try {
        const svg = d3.select("#graph");
        const width = window.innerWidth;
        const height = window.innerHeight;
        
        svg.attr("width", width).attr("height", height);
        
        const g = svg.append("g");
        
        // 缩放行为
        const zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on("zoom", (event) => {
                g.attr("transform", event.transform);
            });
        
        svg.call(zoom);
        
        // 力导向布局
        simulation = d3.forceSimulation(nodes)
            .force("link", d3.forceLink(links).id(d => d.id).distance(100))
            .force("charge", d3.forceManyBody().strength(-300))
            .force("center", d3.forceCenter(width / 2, height / 2));
        
        // 创建连线
        const link = g.append("g")
            .selectAll("line")
            .data(links)
            .join("line")
            .attr("class", "link editable-link");
        
        // 添加关系标签
        const linkLabel = g.append("g")
            .selectAll("text")
            .data(links)
            .join("text")
            .attr("class", "relation-label")
            .text(d => d.relation || "关联")
            .style("cursor", "pointer");
        
        // 创建节点
        const node = g.append("g")
            .selectAll("circle")
            .data(nodes)
            .join("circle")
            .attr("class", d => `node ${d.type}`)
            .attr("r", 20)
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended));
        
        // 节点标签
        const label = g.append("g")
            .selectAll("text")
            .data(nodes)
            .join("text")
            .attr("class", "node-label")
            .attr("dy", ".35em")
            .text(d => d.name);
        
        // 工具提示
        const tooltip = d3.select("#tooltip");
        
        node.on("mouseover", (event, d) => {
            tooltip.style("opacity", 1)
                .html(`<strong>${d.name}</strong><br/>
                       类型: ${d.type}<br/>
                       描述: ${d.description || '暂无描述'}`)
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 10) + "px");
        })
        .on("mouseout", () => {
            tooltip.style("opacity", 0);
        });
        
        // 更新位置
        simulation.on("tick", () => {
            link.attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);
            
            linkLabel.attr("x", d => (d.source.x + d.target.x) / 2)
                     .attr("y", d => (d.source.y + d.target.y) / 2 - 5);
            
            node.attr("cx", d => d.x)
                .attr("cy", d => d.y);
            
            label.attr("x", d => d.x)
                 .attr("y", d => d.y);
        });
        
        // 绑定事件
        setupEventHandlers(node, link, linkLabel, svg, zoom, g);
        
        console.log('✅ 图谱初始化完成！');
        
    } catch (error) {
        console.error('图谱初始化过程中发生错误:', error);
        throw error;
    }
}

// 设置事件处理器
function setupEventHandlers(node, link, linkLabel, svg, zoom, g) {
    // 节点点击事件
    node.on("click", function(event, d) {
        event.stopPropagation();
        
        if (editMode) {
            if (!selectedNode) {
                console.log('通过WebChannel编辑节点:', d.name, '类型:', d.type);
                if (typeof bridge !== 'undefined' && bridge.editNode) {
                    bridge.editNode(d.name, d.type);
                }
            } else {
                handleRelationEdit(d, d3.select(this));
            }
        }
    });
    
    // 连线点击事件
    link.on("click", function(event, d) {
        event.stopPropagation();
        openRelationEditDialog(d);
    });
    
    linkLabel.on("click", function(event, d) {
        event.stopPropagation();
        openRelationEditDialog(d);
    });
    
    // SVG点击取消选择
    svg.on("click", function(event) {
        if (editMode && event.target === this) {
            clearSelection();
        }
    });
    
    // 拖拽函数
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
        
        if (!physicsEnabled) {
            d.x = event.x;
            d.y = event.y;
            updateNodePosition(d);
        }
    }
    
    function dragended(event, d) {
        if (physicsEnabled) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        } else {
            d.fx = event.x;
            d.fy = event.y;
        }
    }
}

// 控制函数
window.resetZoom = function() {
    console.log('重置视图');
    // 实现重置视图逻辑
};

window.togglePhysics = function() {
    physicsEnabled = !physicsEnabled;
    console.log('物理效果:', physicsEnabled ? '开启' : '关闭');
    // 实现物理效果切换逻辑
};

window.toggleEditMode = function() {
    editMode = !editMode;
    console.log('编辑模式:', editMode ? '开启' : '关闭');
    
    const btn = document.getElementById('editModeBtn');
    if (editMode) {
        btn.textContent = '退出编辑';
        btn.style.backgroundColor = '#e74c3c';
    } else {
        btn.textContent = '编辑关系';
        btn.style.backgroundColor = '#4a90e2';
        clearSelection();
    }
};

// 辅助函数
function clearSelection() {
    if (selectedNode) {
        selectedNode.classed('selected-node', false);
        selectedNode = null;
    }
    if (tempLine) {
        tempLine.remove();
        tempLine = null;
    }
}

function handleRelationEdit(nodeData, nodeElement) {
    // 实现关系编辑逻辑
    console.log('处理关系编辑:', nodeData.name);
}

function openRelationEditDialog(linkData) {
    const newRelation = prompt(
        `编辑关系: ${linkData.source.name} -> ${linkData.target.name}\n当前关系: ${linkData.relation}\n\n请输入新的关系类型:`,
        linkData.relation
    );
    
    if (newRelation && newRelation.trim() && newRelation.trim() !== linkData.relation) {
        linkData.relation = newRelation.trim();
        // 更新显示
        console.log('关系已更新:', newRelation);
    }
}

function updateNodePosition(d) {
    // 手动更新节点位置的逻辑
    console.log('更新节点位置:', d.name);
}

// 调试函数
window.debugGraph = function() {
    console.log('=== 图谱状态调试信息 ===');
    console.log('D3.js已加载:', typeof d3 !== 'undefined');
    console.log('nodes数组长度:', nodes ? nodes.length : 'undefined');
    console.log('links数组长度:', links ? links.length : 'undefined');
    console.log('editMode当前值:', editMode);
    console.log('selectedNode:', selectedNode);
    console.log('=========================');
};