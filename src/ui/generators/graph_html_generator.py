"""
知识图谱HTML模板生成器
生成D3.js交互式图谱的HTML页面
"""
from pathlib import Path


class GraphHTMLGenerator:
    """知识图谱HTML生成器"""

    def __init__(self):
        self.template_path = Path(__file__).parent / ".." / "templates" / "graph-template.html"

    def generate_graph_html(self, nodes_json, links_json, output_path):
        """生成图谱HTML文件"""
        try:
            # 如果模板文件存在，使用模板
            if self.template_path.exists():
                return self._generate_from_template(nodes_json, links_json, output_path)
            else:
                # 否则使用内置模板
                return self._generate_builtin_template(nodes_json, links_json, output_path)
        except Exception as e:
            # 如果生成失败，创建简化版本
            self._generate_fallback_html(output_path)
            raise e

    def _generate_from_template(self, nodes_json, links_json, output_path):
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
        html_content = template.replace('{{NODES_DATA}}', nodes_json)
        html_content = html_content.replace('{{LINKS_DATA}}', links_json)

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

    def _generate_builtin_template(self, nodes_json, links_json, output_path):
        """生成内置HTML模板"""
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>EchoGraph Knowledge Graph</title>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link rel="stylesheet" href="assets/css/graph.css">
</head>
<body>
    <div id="loading" class="loading">
        <div class="spinner"></div>
        <p>正在加载图谱...</p>
    </div>

    <div class="controls" id="controls">
        <button onclick="resetZoom()">重置视图</button>
        <button onclick="togglePhysics()">关闭物理效果</button>
        <button onclick="toggleEditMode()" id="editModeBtn">编辑关系</button>
        <button onclick="location.reload()">刷新图谱</button>
    </div>

    <div class="graph-container" id="graphContainer">
        <svg id="graph" width="100%" height="100%"></svg>
    </div>

    <div class="tooltip" id="tooltip"></div>

    <div id="fallback" class="fallback">
        <h2 style="color: #4a90e2; margin-bottom: 30px;">知识图谱 - 简化视图</h2>
        <div class="entity-grid" id="entityGrid">
            <!-- 实体卡片将通过JavaScript动态生成 -->
        </div>
        <p style="opacity: 0.7; font-size: 14px; margin-top: 20px;">
            网络访问受限，无法加载D3.js库，显示简化版本<br>
            <small>已尝试从CDN和本地文件加载D3.js</small>
        </p>
        <button onclick="location.reload()" style="
            background: #4a90e2; color: white; border: none;
            padding: 10px 20px; border-radius: 5px; cursor: pointer; margin-top: 15px;
        ">重新加载</button>
    </div>

    <script src="assets/js/graph.js"></script>
    <script>
        // 设置数据
        window.graphData = {{
            nodes: {nodes_json},
            links: {links_json}
        }};

        // 初始化图谱
        document.addEventListener('DOMContentLoaded', function() {{
            initializeGraphWithData(window.graphData.nodes, window.graphData.links);
        }});
    </script>
</body>
</html>"""

        # 为内置模板注入本地D3绝对路径（若存在对应标签）
        try:
            d3_uri = (self.template_path.resolve().parent.parent.parent.parent / 'assets' / 'js' / 'd3.v7.min.js').resolve().as_uri()
            injection = f'<script>window.localD3PathInjected = "{d3_uri}";</script>'
            html_content = html_content.replace('<script src="assets/js/graph.js"></script>', injection + '\n    <script src="assets/js/graph.js"></script>')
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
                body { background-color: #2d2d2d; color: white; font-family: Arial, sans-serif; }
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
            f.write(html_content)