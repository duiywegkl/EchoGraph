"""
知识图谱HTML模板生成器
生成D3.js交互式图谱的HTML页面
"""
import json
from pathlib import Path
from src.ui.theme import css_variables
from src.graph.node_types import NODE_TYPES


def legend_html():
    return "".join(f'<span><i style="--dot:var(--{kind.id})"></i>{kind.label}</span>' for kind in NODE_TYPES)


class GraphHTMLGenerator:
    """知识图谱HTML生成器"""

    def __init__(self):
        self.template_path = Path(__file__).parent / ".." / "templates" / "graph-template.html"
        self.last_graph_data = None

    def generate_graph_html(self, nodes_json, links_json, output_path, layout_json="{}"):
        """生成图谱HTML文件"""
        self.last_graph_data = (nodes_json, links_json)
        try:
            # 如果模板文件存在，使用模板
            if self.template_path.exists():
                return self._generate_from_template(nodes_json, links_json, output_path, layout_json)
            else:
                # 否则使用内置模板
                return self._generate_builtin_template(nodes_json, links_json, output_path, layout_json)
        except Exception as e:
            # 如果生成失败，创建简化版本
            self._generate_fallback_html(output_path)
            raise e

    def _generate_from_template(self, nodes_json, links_json, output_path, layout_json="{}"):
        """从模板文件生成HTML，并为本地 assets 注入 <base href>"""
        with open(self.template_path, 'r', encoding='utf-8') as f:
            template = f.read()

        # 计算仓库根目录，用于作为 base href，确保 assets 相对路径可用
        try:
            repo_root = (self.template_path.resolve().parent.parent.parent.parent).resolve()
            base_href = repo_root.as_uri() + '/'
        except Exception:
            base_href = ''

        # 如模板未包含 <base>，则在 <head> 内注入
        if '<base ' not in template and base_href:
            template = template.replace('<head>', f'<head>\n    <base href="{base_href}">')

        # 替换模板中的占位符
        html_content = template.replace('/*THEME_VARS*/', css_variables()).replace('{{TYPE_LEGEND}}', legend_html()).replace('{{NODES_DATA}}', nodes_json)
        html_content = html_content.replace('{{TYPE_METADATA}}', json.dumps([{'id': t.id, 'label': t.label} for t in NODE_TYPES], ensure_ascii=False)).replace('{{LINKS_DATA}}', links_json)
        html_content = html_content.replace('{{LAYOUT_DATA}}', layout_json)

        # 注入本地D3绝对路径，确保在受限环境下也能加载
        try:
            d3_uri = (self.template_path.resolve().parent.parent.parent.parent / 'assets' / 'js' / 'd3.v7.min.js').resolve().as_uri()
            injection = f'<script>window.localD3PathInjected = "{d3_uri}";</script>'
            html_content = html_content.replace('<script src="assets/js/graph/graph-core.js"></script>', injection + '\n    <script src="assets/js/graph/graph-core.js"></script>')
        except Exception:
            pass

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return True

    def _generate_builtin_template(self, nodes_json, links_json, output_path, layout_json="{}"):
        """生成内置HTML模板"""
        # Keep the built-in fallback in sync with the live graph layout.
        # A missing template file still yields an offline graph with the same assets.
        html_content = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>EchoGraph Knowledge Graph</title>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<link rel="stylesheet" href="assets/css/graph/graph-visualization.css"><style>/*THEME_VARS*/</style></head><body>
<div id="loading" class="loading"><div class="spinner"></div><p>正在加载图谱...</p></div>
<div class="controls" id="controls"><div class="layout-control"><button id="arrangeBtn" onclick="arrangeGraph('auto')">一键整理</button><button id="layoutMenuBtn" aria-label="选择布局" aria-expanded="false" onclick="toggleLayoutMenu(event)">▾</button><div id="layoutMenu" class="layout-menu" hidden><button onclick="arrangeGraph('auto')">自动整理</button><button onclick="arrangeGraph('radial')">以主角为中心</button><button onclick="arrangeGraph('type')">按类型分组</button></div></div><button onclick="fitGraphToView()">适应窗口</button><button onclick="togglePhysics()">关闭物理效果</button><button onclick="toggleEditMode()" id="editModeBtn" title="编辑关系模式：单击两个节点创建关系，双击节点编辑节点">编辑关系</button><button onclick="toggleForcePanel()" id="forcePanelBtn">调节力度</button><button onclick="refreshGraphFromHost()">刷新图谱</button></div>
<div class="force-panel" id="forcePanel" style="display:none"><h4>物理参数调节</h4>
<div class="force-control"><label>排斥力度:</label><input type="range" id="repulsionSlider" min="-1500" max="-20" step="20" value="-400"><span id="repulsionValue">-400</span></div>
<div class="force-control"><label>连线长度:</label><input type="range" id="linkDistanceSlider" min="60" max="250" step="10" value="120"><span id="linkDistanceValue">120</span></div>
<div class="force-control"><label>碰撞半径:</label><input type="range" id="collisionSlider" min="20" max="80" step="2" value="40"><span id="collisionValue">40</span></div>
<div class="force-control"><label>中心引力:</label><input type="range" id="centerStrengthSlider" min="0" max="0.3" step="0.01" value="0"><span id="centerStrengthValue">0</span></div>
<div class="force-control"><button onclick="resetToSmart()">智能参数</button><button onclick="applyForceChanges()">应用设置</button></div></div>
<div class="graph-container" id="graphContainer"><svg id="graph" width="100%" height="100%"></svg></div><div class="tooltip" id="tooltip"></div>
<div class="legend">{{TYPE_LEGEND}}</div>
<div id="fallback" class="fallback"><h2>知识图谱 - 简化视图</h2><div class="entity-grid" id="entityGrid"></div>
<p>网络访问受限，无法加载D3.js库，显示简化版本<br><small>已尝试从CDN和本地文件加载D3.js</small></p>
<button onclick="location.reload()">重新加载</button></div>
<script>window.graphNodes = {{NODES_DATA}}; window.graphLinks = {{LINKS_DATA}}; window.graphLayout = {{LAYOUT_DATA}}; window.graphTypes = {{TYPE_METADATA}};</script>
<script src="assets/js/graph/graph-layout.js"></script><script src="assets/js/graph/graph-core.js"></script></body></html>"""
        html_content = html_content.replace('/*THEME_VARS*/', css_variables()).replace('{{TYPE_LEGEND}}', legend_html()).replace('{{NODES_DATA}}', nodes_json).replace('{{TYPE_METADATA}}', json.dumps([{'id': t.id, 'label': t.label} for t in NODE_TYPES], ensure_ascii=False)).replace('{{LINKS_DATA}}', links_json).replace('{{LAYOUT_DATA}}', layout_json)

        # 为内置模板注入本地D3绝对路径（若存在对应标签）
        try:
            d3_uri = (self.template_path.resolve().parent.parent.parent.parent / 'assets' / 'js' / 'd3.v7.min.js').resolve().as_uri()
            injection = f'<script>window.localD3PathInjected = "{d3_uri}";</script>'
            html_content = html_content.replace('<script src="assets/js/graph/graph-core.js"></script>', injection + '\n    <script src="assets/js/graph/graph-core.js"></script>')
        except Exception:
            pass

        # 注入 <base href> 以确保相对 assets/ 路径可用（基于仓库根目录）
        try:
            repo_root = (self.template_path.resolve().parent.parent.parent.parent).resolve()
            base_href = repo_root.as_uri() + '/'
            if '<base ' not in html_content:
                html_content = html_content.replace('<head>', f'<head>\n    <base href="{base_href}">')
        except Exception:
            pass

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return True

    def _generate_fallback_html(self, output_path):
        """生成备用简化HTML"""
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>EchoGraph Knowledge Graph</title>
            <style>
                /*THEME_VARS*/ body { background-color: var(--bg-base); color: var(--text-primary); font-family: Microsoft YaHei UI, Segoe UI, sans-serif; }
                .graph-container { display: flex; justify-content: center; align-items: center; height: 100vh; }
                .placeholder { font-size: 18px; opacity: 0.7; text-align: center; }
            </style>
        </head>
        <body>
            <div class="graph-container">
                <div class="placeholder">
                    知识图谱加载失败<br>
                    请检查网络连接或刷新页面<br>
                    <small>(需要访问CDN获取D3.js库)</small>
                </div>
            </div>
        </body>
        </html>
        """

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content.replace('/*THEME_VARS*/', css_variables()))
