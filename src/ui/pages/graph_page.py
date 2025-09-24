"""
GraphPage - 模块化页面，严格对齐 run_ui.bak 的布局与控件组织：
- 左侧：标题+操作按钮行 + QWebEngineView
- 右侧：搜索与过滤、实体列表（含类型过滤按钮）、节点详情（含增删改按钮）、图谱统计
仅还原外观与结构；业务行为留空/简化，不改变布局。
"""
from pathlib import Path
from typing import Optional, List, Dict
import json
import os
import time
import traceback
import requests

from PySide6.QtCore import Qt, QUrl, QObject, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QLabel, QPushButton,
    QGroupBox, QLineEdit, QTextEdit, QListWidget, QListWidgetItem, QHBoxLayout as _H,
    QMessageBox, QStyle, QFileDialog, QDialog, QFormLayout, QComboBox, QScrollArea
)
from PySide6.QtWebChannel import QWebChannel

from ..generators.graph_html_generator import GraphHTMLGenerator
from src.ui.managers.scenario_manager import ScenarioManager

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except Exception:
    QWebEngineView = None  # type: ignore

class GraphBridge(QObject):
    """JavaScript <-> Python 桥接对象（与原版一致）"""
    def __init__(self, graph_page: "GraphPage"):
        super().__init__()
        self.graph_page = graph_page

    @Slot(str)
    def log(self, message: str):
        from loguru import logger as _logger
        _logger.debug(f"[GraphJS] {message}")

    @Slot(str, str)
    def editNode(self, entity_name: str, entity_type: str):
        """JavaScript直接调用此方法编辑节点"""
        try:
            from loguru import logger as _logger
            _logger.info(f"通过WebChannel编辑节点: {entity_name} ({entity_type})")
            self.graph_page.edit_node_with_python_dialog(entity_name, entity_type)
        except Exception as e:
            from loguru import logger as _logger
            _logger.error(f"WebChannel编辑节点失败: {e}")

    @Slot(str, str, str)
    def createRelation(self, source_name: str, target_name: str, relation_type: str):
        """JavaScript直接调用此方法创建关系"""
        try:
            from loguru import logger as _logger
            _logger.info(f"通过WebChannel创建关系: {source_name} -> {target_name} ({relation_type})")
            # 可以在这里添加创建关系的逻辑
        except Exception as e:
            from loguru import logger as _logger
            _logger.error(f"WebChannel创建关系失败: {e}")


from loguru import logger


class GraphPage(QWidget):
    """知识关系图谱页面（布局/视觉对齐原版）"""

    def __init__(self, memory_system: Optional[object] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.memory = memory_system

        # 输出HTML位置（仓库根目录/generated/graph.html）
        repo_root = Path(__file__).resolve().parents[3]
        out_dir = repo_root / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        self.graph_file_path = (out_dir / "graph.html").resolve()

        # WebChannel（必须在加载前设置，避免 JS 中 qt 未定义）
        self.channel = QWebChannel()
        self.bridge = GraphBridge(self)
        self.channel.registerObject("bridge", self.bridge)

        # HTML 生成器
        self.html_generator = GraphHTMLGenerator()

        # tavern 占位属性（保持接口一致）
        self.tavern_mode = False
        self.tavern_session_id: Optional[str] = None

        self._init_ui()
        self._connect_signals()
        self.refresh_graph()

    # ---------------- UI -----------------
    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(10)

        left = self._create_graph_panel()
        right = self._create_control_panel()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)  # 图谱区域占3/4
        splitter.setStretchFactor(1, 1)  # 控制区域占1/4

        layout.addWidget(splitter)

    def _create_graph_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)

        # 标题和快速操作
        header = _H()
        title = QLabel("知识关系图谱")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet("color: #4a90e2; margin-bottom: 10px;")

        self.refresh_btn = QPushButton("刷新图谱")
        self.refresh_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))

        self.save_btn = QPushButton("保存数据")
        self.save_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.save_btn.setStyleSheet("QPushButton { background-color: #28a745; color: white; font-weight: bold; }")
        self.save_btn.setToolTip("手动保存知识图谱和记忆数据到文件")

        self.export_btn = QPushButton("导出图谱")
        self.export_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))

        self.init_graph_btn = QPushButton("初始化图谱")
        self.init_graph_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))

        self.clear_graph_btn = QPushButton("清空图谱")
        self.clear_graph_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))

        self.reset_view_btn = QPushButton("重置视图")
        self.reset_view_btn.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))

        # 注意力机制按钮
        self.attention_analysis_btn = QPushButton("注意力分析")
        self.attention_analysis_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.attention_analysis_btn.setStyleSheet("QPushButton { background-color: #ff6b35; color: white; font-weight: bold; }")
        self.attention_analysis_btn.setToolTip("分析实体重要性，优化上下文以解决注意力分散问题")

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.refresh_btn)
        header.addWidget(self.save_btn)
        header.addWidget(self.export_btn)
        header.addWidget(self.init_graph_btn)
        header.addWidget(self.clear_graph_btn)
        header.addWidget(self.reset_view_btn)
        header.addWidget(self.attention_analysis_btn)

        v.addLayout(header)

        # 图谱显示区域
        if WEBENGINE_AVAILABLE:
            self.graph_view = QWebEngineView()
            self.graph_view.setMinimumHeight(500)
            #
            #
            #
            #
            # 关键：在加载HTML之前绑定WebChannel，确保JS中的 qt.webChannelTransport 可用
            try:
                self.graph_view.page().setWebChannel(self.channel)
            except Exception:
                pass
            v.addWidget(self.graph_view)
        else:
            self.graph_view = None  # type: ignore
            placeholder = QLabel("未安装 QtWebEngine，无法显示图谱。")
            placeholder.setAlignment(Qt.AlignCenter)
            v.addWidget(placeholder)

        return panel

    def _create_control_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)

        # 搜索区域
        search_group = QGroupBox("搜索与过滤")
        s_v = QVBoxLayout(search_group)
        self.search_input = QLineEdit(); self.search_input.setPlaceholderText("搜索节点或关系...")
        self.search_btn = QPushButton("搜索")
        self.clear_search_btn = QPushButton("清除")
        s_h = _H(); s_h.addWidget(self.search_btn); s_h.addWidget(self.clear_search_btn)
        s_v.addWidget(self.search_input); s_v.addLayout(s_h)
        v.addWidget(search_group)

        # 实体列表
        entity_group = QGroupBox("实体列表")
        e_v = QVBoxLayout(entity_group)
        f_h = _H()
        self.filter_all_btn = QPushButton("全部")
        self.filter_character_btn = QPushButton("角色")
        self.filter_location_btn = QPushButton("地点")
        self.filter_item_btn = QPushButton("物品")
        self.filter_event_btn = QPushButton("事件")
        for btn in [self.filter_all_btn, self.filter_character_btn, self.filter_location_btn, self.filter_item_btn, self.filter_event_btn]:
            btn.setCheckable(True); btn.setMaximumHeight(30); f_h.addWidget(btn)
        self.filter_all_btn.setChecked(True)
        e_v.addLayout(f_h)
        self.entity_list = QListWidget(); self.entity_list.setMinimumHeight(200)
        e_v.addWidget(self.entity_list)
        v.addWidget(entity_group)

        # 节点详情
        detail_group = QGroupBox("节点详情")
        d_v = QVBoxLayout(detail_group)
        self.detail_text = QTextEdit(); self.detail_text.setReadOnly(True); self.detail_text.setMaximumHeight(150)
        self.detail_text.setPlaceholderText("选择一个节点查看详细信息...")
        d_v.addWidget(self.detail_text)
        node_actions = _H()
        self.add_node_btn = QPushButton("添加节点")
        self.edit_node_btn = QPushButton("编辑节点")
        self.delete_node_btn = QPushButton("删除节点")

        # 设置按钮图标（与原版一致）
        self.add_node_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        self.edit_node_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.delete_node_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))

        node_actions.addWidget(self.add_node_btn); node_actions.addWidget(self.edit_node_btn); node_actions.addWidget(self.delete_node_btn)
        d_v.addLayout(node_actions)
        v.addWidget(detail_group)

        # 图谱统计
        stats_group = QGroupBox("图谱统计")
        t_v = QVBoxLayout(stats_group)
        self.stats_label = QLabel("节点数量: 0\n关系数量: 0\n最后更新: 未知")
        self.stats_label.setStyleSheet("color: #cccccc; font-size: 12px;")
        t_v.addWidget(self.stats_label)
        v.addWidget(stats_group)

        v.addStretch()
        return panel

    # -------------- 信号 -----------------
    def _connect_signals(self):
        self.refresh_btn.clicked.connect(self.refresh_graph)
        self.save_btn.clicked.connect(self.save_graph_data)
        self.export_btn.clicked.connect(self.export_graph)
        self.init_graph_btn.clicked.connect(self.initialize_graph)
        self.clear_graph_btn.clicked.connect(self.clear_graph)
        self.reset_view_btn.clicked.connect(self.reset_view)
        self.attention_analysis_btn.clicked.connect(self.show_attention_analysis)
        self.search_btn.clicked.connect(self.search_nodes)
        self.clear_search_btn.clicked.connect(self.clear_search)
        self.search_input.returnPressed.connect(self.search_nodes)
        for btn in [self.filter_all_btn, self.filter_character_btn, self.filter_location_btn, self.filter_item_btn, self.filter_event_btn]:
            btn.clicked.connect(self.filter_entities)
        self.entity_list.itemClicked.connect(self.on_entity_selected)
        self.entity_list.itemDoubleClicked.connect(self.edit_selected_node)

        # 节点编辑按钮连接
        self.add_node_btn.clicked.connect(self.add_node)
        self.edit_node_btn.clicked.connect(self.edit_node)
        self.delete_node_btn.clicked.connect(self.delete_node)

    # -------------- 行为 --------------
    def refresh_graph(self):
        """刷新关系图谱（对齐 bak：本地/酒馆模式自动选择数据源）"""
        try:
            if not WEBENGINE_AVAILABLE:
                return

            # 酒馆模式：直接从 API 刷新
            if getattr(self, 'tavern_mode', False) and getattr(self, 'tavern_session_id', None):
                logger.debug(f"[Graph] 酒馆模式刷新，session={self.tavern_session_id}")
                self.refresh_from_api_server(self.tavern_session_id)
                return

            logger.debug("[Graph] 本地模式刷新知识关系图谱...")

            # *** 不要调用reload_entities_from_json()！它会删除所有关系！***
            # 直接获取实体数据，不重建知识图谱
            entities = self.get_all_entities()

            # 更新右侧 UI
            self.update_entity_list_with_data(entities)
            self.update_stats_with_data(entities)

            # 生成并加载 HTML
            self.generate_graph_html_with_data(entities)
            if self.graph_file_path.exists():
                self.graph_view.load(QUrl.fromLocalFile(str(self.graph_file_path)))
        except Exception as e:
            logger.error(f"刷新图谱失败: {e}")
            QMessageBox.warning(self, "错误", f"刷新图谱失败：{e}")

    def save_graph_data(self):
        """手动保存知识图谱和记忆数据（对齐原逻辑，本地/酒馆两种路径）"""
        try:
            # 酒馆模式：调用后端保存接口
            if getattr(self, 'tavern_mode', False) and getattr(self, 'tavern_session_id', None):
                try:
                    import requests
                    api_base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:9543")
                    save_url = f"{api_base_url}/sessions/{self.tavern_session_id}/save"
                    logger.info(f"[Graph] [酒馆模式] 调用保存接口: {save_url}")
                    resp = requests.post(save_url, timeout=int(os.getenv("API_TIMEOUT", "30")))
                    if resp.status_code == 200:
                        QMessageBox.information(self, "保存成功", "已请求后端保存当前会话的知识图谱与记忆数据。")
                        logger.info("[Graph] [酒馆模式] 保存请求成功")
                    else:
                        raise RuntimeError(f"HTTP {resp.status_code}")
                except Exception as api_err:
                    logger.error(f"[Graph] [酒馆模式] 保存失败: {api_err}")
                    QMessageBox.critical(self, "保存失败", f"酒馆模式下保存失败：{api_err}")
                return

            # 本地模式：通过内存系统落盘 graphml + entities.json
            mem = self.memory or getattr(self.window(), "memory", None)
            if not mem:
                QMessageBox.warning(self, "保存失败", "未找到记忆系统，无法保存数据。")
                return

            # 先将知识图谱中的实体同步到 entities.json
            if hasattr(mem, 'sync_entities_to_json'):
                mem.sync_entities_to_json()

            # 再调用统一保存（包含热记忆 + 图谱 graphml）
            if hasattr(mem, 'save_all_memory'):
                mem.save_all_memory()
            else:
                # 兜底：仅保存知识图谱
                if hasattr(mem, 'knowledge_graph') and hasattr(mem, 'graph_save_path') and mem.graph_save_path:
                    try:
                        mem.knowledge_graph.save_graph(mem.graph_save_path)
                    except Exception as ge:
                        logger.warning(f"[Graph] 仅保存图谱失败: {ge}")

            QMessageBox.information(self, "保存成功", "已将知识图谱与实体数据保存到本地。")
        except Exception as e:
            logger.error(f"[Graph] 保存数据失败: {e}\n{traceback.format_exc()}")
            QMessageBox.critical(self, "保存失败", f"保存数据时发生错误：\n{e}")

    def export_graph(self):
        """导出图谱为JSON（包含实体与简单统计）"""
        try:
            default_path = str(Path.home() / "knowledge_graph.json")
            file_path, _ = QFileDialog.getSaveFileName(
                self, "导出知识图谱", default_path, "JSON 文件 (*.json);;所有文件 (*.*)"
            )
            if not file_path:
                return

            entities = self.get_all_entities()
            export_data = {
                'metadata': {
                    'title': 'EchoGraph Knowledge Graph',
                    'created_by': 'EchoGraph',
                    'export_time': time.time(),
                    'version': '1.0.0'
                },
                'entities': entities,
                'statistics': {
                    'total_entities': len(entities),
                    'entity_types': {}
                }
            }
            for entity in entities:
                t = entity.get('type', 'unknown')
                export_data['statistics']['entity_types'][t] = export_data['statistics']['entity_types'].get(t, 0) + 1

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)

            QMessageBox.information(self, "导出成功", f"知识图谱已导出到：\n{file_path}\n\n包含 {len(entities)} 个实体")
            logger.info(f"[Graph] 导出成功: {file_path}")
        except Exception as e:
            logger.error(f"[Graph] 导出失败: {e}")
            QMessageBox.critical(self, "导出失败", f"导出失败：{e}")

    def initialize_graph(self):
        """
        初始化图谱：本地测试模式下创建默认的《超时空之轮》知识图谱；酒馆模式暂不在前端初始化。
        """
        try:
            # 酒馆模式：提示改由后端或会话初始化
            if getattr(self, 'tavern_mode', False):
                QMessageBox.information(self, "提示", "酒馆模式下请通过后端会话初始化知识图谱。")
                return

            mem = self.memory or getattr(self.window(), "memory", None)
            if not mem:
                QMessageBox.warning(self, "初始化失败", "未找到记忆系统，无法初始化图谱。")
                return

            reply = QMessageBox.question(
                self,
                "初始化知识图谱",
                "是否要创建默认的《超时空之轮》开局？\n\n这将清空现有图谱并创建新的世界设定。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply != QMessageBox.Yes:
                return

            # 清空现有数据
            if hasattr(mem, 'clear_all'):
                mem.clear_all()
            elif hasattr(mem, 'knowledge_graph'):
                mem.knowledge_graph.clear()
                if hasattr(mem, 'sync_entities_to_json'):
                    mem.sync_entities_to_json()

            # 创建默认场景（超时空之轮）
            try:
                scenario_manager = ScenarioManager(mem, None, None, None)
                opening_story, entity_count, relationship_count = scenario_manager.create_chrono_trigger_scenario()
            except Exception as se:
                logger.error(f"[Graph] 创建默认场景失败: {se}")
                QMessageBox.critical(self, "初始化失败", f"创建默认场景失败：\n{se}")
                return

            # 保存并刷新
            if hasattr(mem, 'save_all_memory'):
                mem.save_all_memory()
            self.refresh_graph()

            QMessageBox.information(
                self,
                "时空之门已开启！",
                f"《超时空之轮》世界已创建！\n\n包含 {entity_count} 个实体、{relationship_count} 条关系。"
            )
        except Exception as e:
            logger.error(f"[Graph] 初始化失败: {e}")
            QMessageBox.critical(self, "初始化失败", f"初始化图谱时发生错误：\n{e}")

    def clear_graph(self):
        """清空当前图谱并保存（不删除文件，仅清空内容）"""
        try:
            mem = self.memory or getattr(self.window(), "memory", None)
            if not mem:
                QMessageBox.warning(self, "清空失败", "未找到记忆系统，无法清空图谱。")
                return

            if hasattr(mem, 'knowledge_graph'):
                mem.knowledge_graph.clear()
            if hasattr(mem, 'sync_entities_to_json'):
                mem.sync_entities_to_json()
            if hasattr(mem, 'save_all_memory'):
                mem.save_all_memory()
            elif hasattr(mem, 'graph_save_path') and mem.graph_save_path:
                mem.knowledge_graph.save_graph(mem.graph_save_path)

            QMessageBox.information(self, "完成", "已清空知识图谱。")
            self.refresh_graph()
        except Exception as e:
            logger.error(f"[Graph] 清空失败: {e}")
            QMessageBox.critical(self, "清空失败", f"清空图谱时发生错误：\n{e}")

    def reset_view(self):
        try:
            if WEBENGINE_AVAILABLE and self.graph_view:
                self.graph_view.page().runJavaScript("window.resetZoom && window.resetZoom();")
        except Exception as e:
            logger.error(f"[Graph] 重置视图失败: {e}")

    def search_nodes(self):
        """在右侧实体列表中过滤匹配项（名称/描述包含关键字）"""
        keyword = self.search_input.text().strip().lower()
        try:
            for i in range(self.entity_list.count()):
                item = self.entity_list.item(i)
                ent = item.data(Qt.UserRole) or {}
                name = str(ent.get('name', '')).lower()
                desc = str(ent.get('description', '')).lower()
                matched = (keyword in name) or (keyword in desc)
                item.setHidden(False if not keyword else not matched)
        except Exception as e:
            logger.error(f"[Graph] 搜索失败: {e}")

    def clear_search(self):
        self.search_input.clear()
        # 取消隐藏所有条目
        for i in range(self.entity_list.count()):
            self.entity_list.item(i).setHidden(False)

    def filter_entities(self):
        sender = self.sender()
        for btn in [self.filter_all_btn, self.filter_character_btn, self.filter_location_btn, self.filter_item_btn, self.filter_event_btn]:
            btn.setChecked(btn is sender)
        # 刷新列表（根据选中的类型）
        selected_type = "全部"
        if sender is self.filter_character_btn:
            selected_type = "角色"
        elif sender is self.filter_location_btn:
            selected_type = "地点"
        elif sender is self.filter_item_btn:
            selected_type = "物品"
        elif sender is self.filter_event_btn:
            selected_type = "事件"
        self.update_entity_list_with_data(self.get_all_entities(), selected_type)

    def on_entity_selected(self, item: QListWidgetItem):  # type: ignore[name-defined]
        ent = item.data(Qt.UserRole) or {}
        lines = [
            f"名称: {ent.get('name','')}",
            f"类型: {ent.get('type','')}",
            f"描述: {ent.get('description','')}"
        ]
        attrs = ent.get('attributes', {}) or {}
        if attrs:
            lines.append("属性:")
            for k, v in attrs.items():
                lines.append(f"  - {k}: {v}")
        self.detail_text.setPlainText("\n".join(lines))
        # 同时在前端高亮并尝试居中该节点
        try:
            if WEBENGINE_AVAILABLE and self.graph_view:
                node_id = ent.get('name','')
                js = f"window.focusNodeById && window.focusNodeById({json.dumps(node_id)});"
                self.graph_view.page().runJavaScript(js)
        except Exception as e:
            logger.debug(f"[Graph] 前端聚焦失败: {e}")

    def focus_on_node(self, item: QListWidgetItem):  # type: ignore[name-defined]
        try:
            ent = item.data(Qt.UserRole) or {}
            node_id = ent.get('name','')
            if WEBENGINE_AVAILABLE and self.graph_view:
                js = f"window.focusNodeById && window.focusNodeById({json.dumps(node_id)});"
                self.graph_view.page().runJavaScript(js)
        except Exception as e:
            logger.error(f"[Graph] 聚焦节点失败: {e}")

    def edit_selected_node(self, item: QListWidgetItem):  # type: ignore[name-defined]
        """双击实体列表项目时编辑节点"""
        try:
            ent = item.data(Qt.UserRole) or {}
            entity_name = ent.get('name', '')
            entity_type = ent.get('type', 'character')

            if entity_name:
                self.edit_node_with_python_dialog(entity_name, entity_type)
            else:
                QMessageBox.warning(self, "错误", "无法获取节点信息")
        except Exception as e:
            logger.error(f"[Graph] 双击编辑节点失败: {e}")
            QMessageBox.critical(self, "错误", f"编辑节点失败：\n\n{str(e)}")


    def _collect_graph_data(self) -> tuple[List[Dict], List[Dict]]:
        """
        从 memory.knowledge_graph 中收集节点/关系，生成给前端的简单结构；找不到 memory 时返回空。
        """
        nodes: List[Dict] = []
        links: List[Dict] = []
        try:
            mem = self.memory or getattr(self.window(), "memory", None)
            if mem and hasattr(mem, "knowledge_graph") and hasattr(mem.knowledge_graph, "graph"):
                G = mem.knowledge_graph.graph
                for n, attrs in G.nodes(data=True):
                    nodes.append({
                        "id": n,
                        "name": attrs.get("name", n),
                        "type": attrs.get("type", "concept"),
                        "description": attrs.get("description", "")
                    })
                for s, t, attrs in G.edges(data=True):
                    links.append({
                        "source": s,
                        "target": t,
                        "relation": attrs.get("relationship", "关联")
                    })
        except Exception as e:
            logger.warning(f"[Graph] 收集数据失败，将使用空数据: {e}")
        return nodes, links
                # 节点
    # ---- 数据与生成（对齐 bak） ----
    def get_all_entities(self) -> List[Dict]:
        """获取所有实体：优先酒馆模式 API，其次本地 memory.graph"""
        try:
            entities: List[Dict] = []

            # 酒馆模式：从 API 拉取
            if getattr(self, 'tavern_mode', False) and getattr(self, 'tavern_session_id', None):
                try:
                    import requests
                    api_base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:9543")
                    export_url = f"{api_base_url}/sessions/{self.tavern_session_id}/export"
                    api_timeout = int(os.getenv("API_TIMEOUT", "15"))
                    resp = requests.get(export_url, timeout=api_timeout)
                    if resp.status_code == 200:
                        graph_data = resp.json().get('graph_data', {})
                        for node in graph_data.get('nodes', []):
                            entities.append({
                                'name': node.get('id', ''),
                                'type': node.get('type', 'concept'),
                                'description': node.get('description', ''),
                                'created_time': time.time(),
                                'last_modified': time.time(),
                                'attributes': {}
                            })
                        logger.info(f"[Graph] 从API获取 {len(entities)} 个实体")
                        return entities
                except Exception as api_err:
                    logger.warning(f"[Graph] API 获取实体失败，回退本地: {api_err}")

            # 本地：从 memory.knowledge_graph 读取
            mem = self.memory
            if mem is None:
                mw = self.window()
                mem = getattr(mw, 'memory', None)
            if mem and hasattr(mem, 'knowledge_graph') and hasattr(mem.knowledge_graph, 'graph'):
                for node_id, attrs in mem.knowledge_graph.graph.nodes(data=True):
                    entity = {
                        'name': node_id,
                        'type': attrs.get('type', 'concept'),
                        'description': attrs.get('description', ''),
                        'created_time': attrs.get('created_time', time.time()),
                        'last_modified': attrs.get('last_modified', time.time()),
                        'attributes': {}
                    }
                    excluded = {'type', 'description', 'created_time', 'last_modified'}
                    for k, v in attrs.items():
                        if k not in excluded:
                            entity['attributes'][k] = v
                    entities.append(entity)
                logger.info(f"[Graph] 从本地图谱读取 {len(entities)} 个实体")
            return entities
        except Exception as e:
            logger.error(f"[Graph] 获取实体失败: {e}")
            return []

    def update_entity_list_with_data(self, entities: List[Dict], filter_type: str = "全部"):
        try:
            self.entity_list.clear()
            filtered: List[Dict] = []
            for ent in entities:
                t = ent.get('type')
                if filter_type == "全部" or \
                   (filter_type == "角色" and t == "character") or \
                   (filter_type == "地点" and t == "location") or \
                   (filter_type == "物品" and t == "item") or \
                   (filter_type == "事件" and t == "event"):
                    filtered.append(ent)
            for ent in filtered:
                text = f"【{ent.get('type','未知')}】{ent.get('name','未命名')}"
                desc = ent.get('description')
                if desc:
                    text += f" - {desc[:50]}{'...' if len(desc) > 50 else ''}"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, ent)
                self.entity_list.addItem(item)
        except Exception as e:
            logger.error(f"[Graph] 更新实体列表失败: {e}")

    def update_stats_with_data(self, entities: List[Dict]):
        try:
            node_count = len(entities)
            # 简单估算关系数；真实关系通过 HTML 可视化体现
            relation_count = node_count * 2
            from datetime import datetime
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.stats_label.setText(f"节点数量: {node_count}\n关系数量: {relation_count}\n最后更新: {ts}")
        except Exception as e:
            logger.error(f"[Graph] 更新统计失败: {e}")

    def _get_type_group(self, entity_type: str) -> int:
        return {
            'character': 1,
            'location': 2,
            'item': 3,
            'event': 4,
            'concept': 5,
        }.get(entity_type, 5)

    def generate_graph_html_with_data(self, entities: List[Dict]):
        try:
            nodes = []
            links = []
            # 节点
            for ent in entities:
                nodes.append({
                    'id': ent['name'],
                    'name': ent['name'],
                    'type': ent.get('type', 'concept'),
                    'description': ent.get('description', ''),
                    'group': self._get_type_group(ent.get('type', 'concept'))
                })
            # 关系（从本地图读取）
            mem = self.memory
            if mem is None:
                mw = self.window()
                mem = getattr(mw, 'memory', None)
            if mem and hasattr(mem, 'knowledge_graph') and hasattr(mem.knowledge_graph, 'graph'):
                G = mem.knowledge_graph.graph

                # 调试：检查知识图谱中的关系数量
                total_edges = len(G.edges())
                total_nodes = len(G.nodes())
                logger.info(f"🔍 生成HTML时：知识图谱有 {total_nodes} 个节点，{total_edges} 条关系")

                for s, t, attrs in G.edges(data=True):
                    links.append({
                        'source': s,
                        'target': t,
                        'relation': attrs.get('relationship', '关联')
                    })

                logger.info(f"🔍 HTML生成：创建了 {len(nodes)} 个节点，{len(links)} 条关系")
            else:
                logger.warning("🔍 无法获取知识图谱或知识图谱为空")

            nodes_json = json.dumps(nodes, ensure_ascii=False)
            links_json = json.dumps(links, ensure_ascii=False)
            self.html_generator.generate_graph_html(nodes_json, links_json, str(self.graph_file_path))
        except Exception as e:
            logger.error(f"[Graph] 生成图谱HTML失败: {e}\n{traceback.format_exc()}")
            self.html_generator._generate_fallback_html(str(self.graph_file_path))

    # 兼容方法名（bak 中存在）
    def update_entity_list(self, filter_type: str = "全部"):
        self.update_entity_list_with_data(self.get_all_entities(), filter_type)

    def update_stats(self):
        self.update_stats_with_data(self.get_all_entities())

    def refresh_from_api_server(self, session_id: str):
        """酒馆模式：直接从 API 拉取 nodes/links 并渲染"""
        try:
            logger.info(f"📡 从API服务器获取会话 {session_id} 的知识图谱数据...")

            # 检查是否在酒馆模式
            if not getattr(self, 'tavern_mode', False):
                logger.warning("⚠️ 不在酒馆模式，跳过API刷新")
                return

            import requests
            api_base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:9543")
            export_url = f"{api_base_url}/sessions/{session_id}/export"
            api_timeout = int(os.getenv("API_TIMEOUT", "15"))

            logger.debug(f"📋 请求URL: {export_url}")
            resp = requests.get(export_url, timeout=api_timeout)

            if resp.status_code != 200:
                raise RuntimeError(f"API 返回码 {resp.status_code}, 响应: {resp.text[:200]}")

            graph_json = resp.json().get('graph_data', {})
            # 直接按 API 返回的格式映射
            nodes = []
            for n in graph_json.get('nodes', []):
                nodes.append({
                    'id': n.get('id', ''),
                    'name': n.get('id', ''),
                    'type': n.get('type', 'concept'),
                    'description': n.get('description', ''),
                    'group': self._get_type_group(n.get('type', 'concept'))
                })
            links = []
            for e in graph_json.get('links', []):
                links.append({
                    'source': e.get('source'),
                    'target': e.get('target'),
                    'relation': e.get('relation', '关联')
                })
            self.html_generator.generate_graph_html(json.dumps(nodes, ensure_ascii=False),
                                                    json.dumps(links, ensure_ascii=False),
                                                    str(self.graph_file_path))
            if self.graph_file_path.exists() and WEBENGINE_AVAILABLE:
                self.graph_view.load(QUrl.fromLocalFile(str(self.graph_file_path)))

            # 更新右侧UI组件（实体列表和统计信息）
            self._update_ui_from_api_data(nodes, links)

            logger.info(f"✅ API刷新成功: {len(nodes)} 个节点, {len(links)} 个关系")

        except Exception as e:
            logger.error(f"❌ [Graph] API 刷新失败: {e}")

            # 显示错误状态
            self.stats_label.setText("API连接失败")
            self.entity_list.clear()
            self.entity_list.addItem(f"API错误: {str(e)[:50]}...")

            # 不显示弹窗，避免干扰用户体验
            # QMessageBox.warning(self, "错误", f"从API刷新失败：{e}")

    def enter_tavern_mode(self, session_id: str):
        """进入酒馆模式并绑定会话（与集成页联动一致）"""
        try:
            logger.info(f"🏛️ GraphPage进入酒馆模式，会话ID: {session_id}")

            # 如果已经在酒馆模式且会话ID相同，强制刷新以确保数据同步
            if getattr(self, 'tavern_mode', False) and getattr(self, 'tavern_session_id', None) == session_id:
                logger.info(f"📋 已在酒馆模式且会话ID相同，强制刷新确保数据同步: {session_id}")
                try:
                    self.refresh_from_api_server(session_id)
                except Exception as refresh_error:
                    logger.error(f"强制刷新失败: {refresh_error}")
                return

            # 如果之前在酒馆模式但会话ID不同，先清理
            if getattr(self, 'tavern_mode', False) and getattr(self, 'tavern_session_id', None) != session_id:
                logger.info(f"🔄 会话ID变化，清理之前的酒馆模式数据: {getattr(self, 'tavern_session_id', None)} -> {session_id}")
                self.clear_graph_display()

            # 如果从本地模式切换到酒馆模式，也需要清理
            if not getattr(self, 'tavern_mode', False):
                logger.info("🏠➡️🏛️ 从本地模式切换到酒馆模式，清理本地显示数据")
                self.clear_graph_display()

            self.tavern_mode = True
            self.tavern_session_id = session_id

            # 立即刷新一次，显示API返回的图谱
            self.refresh_from_api_server(session_id)
            logger.info(f"✅ GraphPage已进入酒馆模式: {session_id}")

        except Exception as e:
            logger.error(f"[Graph] 进入酒馆模式失败: {e}")
            # 重置状态以防止状态不一致
            self.tavern_mode = False
            self.tavern_session_id = None

    def exit_tavern_mode(self):
        """退出酒馆模式，切换回本地数据源"""
        logger.info("🏠 GraphPage正在退出酒馆模式...")

        self.tavern_mode = False
        self.tavern_session_id = None

        # 清理酒馆模式的数据显示
        self.clear_graph_display()

        # 确保使用主窗口的本地内存对象
        try:
            main_window = self.window()
            if main_window and hasattr(main_window, 'memory'):
                self.memory = main_window.memory
                logger.info("✅ 已切换到主窗口的本地内存对象")
            else:
                logger.warning("⚠️ 无法获取主窗口的内存对象")
        except Exception as e:
            logger.error(f"切换内存对象失败: {e}")

        # 重新加载本地模式的数据
        try:
            self.refresh_graph()
            logger.info("✅ GraphPage已退出酒馆模式，切换回本地数据源")
        except Exception as e:
            logger.error(f"刷新本地图谱失败: {e}")

    def edit_node_with_python_dialog(self, entity_name: str, entity_type: str, is_new_node: bool = False):
        """使用Python/Qt的完整编辑对话框，支持动态属性"""
        try:
            if is_new_node:
                # 新增模式：创建空实体
                current_entity = {
                    'name': entity_name or '',
                    'type': entity_type or 'character',
                    'description': '',
                    'attributes': {},
                    'created_time': time.time()
                }
                dialog_title = "新增节点"
                success_msg = "节点创建成功"
            else:
                # 编辑模式：获取现有实体数据
                all_entities = self.get_all_entities()
                current_entity = None

                for entity in all_entities:
                    if entity['name'] == entity_name and entity['type'] == entity_type:
                        current_entity = entity
                        break

                if not current_entity:
                    QMessageBox.warning(self, "错误", f"找不到实体: {entity_name}")
                    return

                dialog_title = f"编辑节点: {entity_name}"
                success_msg = "节点更新成功"

            # 创建增强的编辑对话框
            dialog = QDialog(self)
            dialog.setWindowTitle(dialog_title)
            dialog.setMinimumSize(500, 400)
            dialog.setMaximumSize(800, 600)

            # 主布局
            main_layout = QVBoxLayout(dialog)

            # 基本信息分组
            basic_group = QGroupBox("基本信息")
            basic_layout = QFormLayout(basic_group)

            # 名称
            name_edit = QLineEdit(current_entity['name'])
            name_edit.setPlaceholderText("请输入节点名称")
            basic_layout.addRow("名称 *:", name_edit)

            # 类型
            type_combo = QComboBox()
            type_combo.addItems(["character", "location", "item", "event", "concept"])
            type_combo.setCurrentText(current_entity['type'])
            basic_layout.addRow("类型:", type_combo)

            # 描述
            desc_edit = QTextEdit(current_entity.get('description', ''))
            desc_edit.setMaximumHeight(80)
            desc_edit.setPlaceholderText("描述该节点的特征、属性等...")
            basic_layout.addRow("描述:", desc_edit)

            main_layout.addWidget(basic_group)

            # 动态属性分组
            attr_group = QGroupBox("动态属性")
            attr_layout = QVBoxLayout(attr_group)

            # 创建滚动区域
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setMaximumHeight(200)
            scroll_area.setMinimumHeight(120)
            scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll_area.setStyleSheet("""
                QScrollArea {
                    border: 1px solid #444;
                    border-radius: 5px;
                    background-color: #2b2b2b;
                }
                QScrollBar:vertical {
                    background-color: #3c3c3c;
                    width: 12px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background-color: #666;
                    border-radius: 6px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background-color: #888;
                }
            """)

            # 属性列表容器widget
            attr_scroll = QWidget()
            attr_scroll.setStyleSheet("""
                QWidget {
                    background-color: #2b2b2b;
                }
            """)
            scroll_area.setWidget(attr_scroll)
            attr_scroll_layout = QVBoxLayout(attr_scroll)

            # 当前属性行列表
            attr_rows = []

            def add_attribute_row(key='', value=''):
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(2, 2, 2, 2)

                key_edit = QLineEdit(key)
                key_edit.setPlaceholderText("属性名")
                key_edit.setMaximumWidth(120)

                value_edit = QLineEdit(value)
                value_edit.setPlaceholderText("属性值")

                def remove_row():
                    if row_widget in [r[2] for r in attr_rows]:
                        # 移除引用
                        attr_rows[:] = [r for r in attr_rows if r[2] != row_widget]
                        # 移除UI
                        row_widget.setParent(None)
                        row_widget.deleteLater()

                def rebuild_layout():
                    # 强制重新布局
                    attr_scroll_layout.update()
                    attr_scroll.update()
                    scroll_area.update()

                remove_btn = QPushButton("×")
                remove_btn.setFixedSize(25, 25)
                remove_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #e74c3c;
                        border: none;
                        border-radius: 12px;
                        font-weight: bold;
                        color: white;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background-color: #c0392b;
                    }
                """)
                remove_btn.clicked.connect(remove_row)

                row_layout.addWidget(key_edit)
                row_layout.addWidget(value_edit)
                row_layout.addWidget(remove_btn)

                attr_scroll_layout.addWidget(row_widget)
                attr_rows.append((key_edit, value_edit, row_widget))

                # 自动聚焦到新添加的键输入框
                if not key:
                    key_edit.setFocus()

                return key_edit, value_edit, row_widget

            # 加载现有属性
            for key, value in current_entity.get('attributes', {}).items():
                add_attribute_row(key, str(value))

            # 添加空行供用户输入新属性
            add_attribute_row()

            # 添加新属性按钮
            add_attr_btn = QPushButton("+ 添加属性")
            add_attr_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60;
                    border: none;
                    padding: 8px;
                    border-radius: 4px;
                    font-weight: bold;
                    color: white;
                }
                QPushButton:hover {
                    background-color: #229954;
                }
            """)
            add_attr_btn.clicked.connect(lambda: add_attribute_row())

            attr_layout.addWidget(scroll_area)
            attr_layout.addWidget(add_attr_btn)
            main_layout.addWidget(attr_group)

            # 按钮区域
            button_layout = QHBoxLayout()
            button_layout.addStretch()

            cancel_btn = QPushButton("取消")
            cancel_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton))
            cancel_btn.clicked.connect(dialog.reject)

            save_btn = QPushButton("保存" if not is_new_node else "创建")
            save_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
            save_btn.setStyleSheet("QPushButton { background-color: #4a90e2; font-weight: bold; }")

            def save_changes():
                try:
                    # 验证输入
                    new_name = name_edit.text().strip()
                    new_type = type_combo.currentText()
                    new_desc = desc_edit.toPlainText().strip()

                    if not new_name:
                        QMessageBox.warning(dialog, "输入错误", "节点名称不能为空！")
                        name_edit.setFocus()
                        return

                    # 收集动态属性
                    new_attributes = {}
                    for key_edit, value_edit, _ in attr_rows:
                        key = key_edit.text().strip()
                        value = value_edit.text().strip()
                        if key and value:  # 只保存非空的属性
                            new_attributes[key] = value

                    # 创建更新后的实体数据
                    updated_entity = {
                        'name': new_name,
                        'type': new_type,
                        'description': new_desc,
                        'attributes': new_attributes,
                        'created_time': current_entity.get('created_time', time.time()),
                        'last_modified': time.time()
                    }

                    # 根据模式选择保存方式（与原版一致）
                    if getattr(self, 'tavern_mode', False) and getattr(self, 'tavern_session_id', None):
                        # 酒馆模式：通过API保存
                        try:
                            import requests
                            api_base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:9543")
                            response = requests.post(
                                f"{api_base_url}/sessions/{self.tavern_session_id}/nodes",
                                json=updated_entity,
                                timeout=30
                            )
                            if response.status_code == 200:
                                logger.info(f"✅ [酒馆模式] 节点保存成功: {new_name}")
                            else:
                                raise RuntimeError(f"API保存失败: {response.status_code}")
                        except Exception as api_err:
                            logger.error(f"❌ [酒馆模式] 保存节点API调用失败: {api_err}")
                            QMessageBox.critical(dialog, "保存失败", f"保存节点失败：\n\n{str(api_err)}")
                            return
                    else:
                        # 本地模式：使用原版逻辑
                        if is_new_node:
                            # 添加新实体（先不保存，等知识图谱更新后再统一保存）
                            all_entities = self.get_all_entities()
                            all_entities.append(updated_entity)
                            logger.info(f"新节点数据已准备: {new_name} (类型: {new_type})")
                        else:
                            # 更新现有实体
                            all_entities = self.get_all_entities()

                            # 找到并更新对应的实体
                            entity_updated = False
                            for i, entity in enumerate(all_entities):
                                if entity['name'] == entity_name and entity['type'] == entity_type:
                                    # 更新找到的实体
                                    all_entities[i] = updated_entity
                                    entity_updated = True
                                    logger.info(f"找到并更新实体: {entity_name} -> {new_name}")
                                    break

                            if not entity_updated:
                                logger.warning(f"未找到要更新的实体: {entity_name} ({entity_type})")
                                QMessageBox.warning(dialog, "更新失败", f"未找到要更新的实体: {entity_name}")
                                return

                            # 先不保存entities.json，等知识图谱更新后再统一保存
                            logger.info(f"实体数据已准备更新: {new_name} (类型: {new_type})")

                        # 同步更新知识图谱中的节点（直接更新属性，保留关系）
                        try:
                            # 获取主窗口实例
                            main_window = None
                            widget = self.parent()
                            while widget is not None:
                                if hasattr(widget, '__class__') and 'MainWindow' in widget.__class__.__name__:
                                    main_window = widget
                                    break
                                widget = widget.parent()

                            if main_window and hasattr(main_window, 'memory'):
                                kg = main_window.memory.knowledge_graph

                                # 调试：检查保存前的关系数量
                                if hasattr(kg, 'graph'):
                                    edges_before = len(kg.graph.edges())
                                    nodes_before = len(kg.graph.nodes())
                                    logger.info(f"🔍 保存前：{nodes_before} 个节点，{edges_before} 条关系")

                                # 如果是重命名节点，使用专门的重命名方法
                                if not is_new_node and entity_name != new_name:
                                    if hasattr(main_window.memory, 'rename_node') and entity_name in kg.graph.nodes:
                                        # 使用GRAGMemory的rename_node方法，它会正确保留所有关系
                                        success = main_window.memory.rename_node(entity_name, new_name)
                                        if success:
                                            # 重命名成功后，更新节点属性
                                            kg.graph.nodes[new_name].update({
                                                'type': new_type,
                                                'description': new_desc,
                                                **new_attributes
                                            })
                                            logger.info(f"✅ 节点重命名成功: {entity_name} -> {new_name}")
                                        else:
                                            logger.error(f"❌ 节点重命名失败: {entity_name} -> {new_name}")
                                            QMessageBox.critical(dialog, "重命名失败", f"节点重命名失败：{entity_name} -> {new_name}")
                                            return
                                    else:
                                        # 旧节点不存在，直接创建新节点
                                        kg.graph.add_node(new_name,
                                                         type=new_type,
                                                         description=new_desc,
                                                         **new_attributes)
                                        logger.info(f"🆕 创建新节点: {new_name}")
                                else:
                                    # 新增或更新现有节点（不重命名）
                                    if hasattr(kg, 'graph'):
                                        # 直接更新节点属性，NetworkX会保留现有关系
                                        kg.graph.add_node(new_name,
                                                         type=new_type,
                                                         description=new_desc,
                                                         **new_attributes)
                                        logger.info(f"✅ 节点属性已更新: {new_name}")

                                # 调试：检查更新后的关系数量
                                if hasattr(kg, 'graph'):
                                    edges_after = len(kg.graph.edges())
                                    nodes_after = len(kg.graph.nodes())
                                    logger.info(f"🔍 保存后：{nodes_after} 个节点，{edges_after} 条关系")

                                # 标记数据已变化并保存知识图谱（包括关系）
                                if hasattr(main_window.memory, 'save_all_memory'):
                                    main_window.memory._data_changed = True  # 确保数据会被保存
                                    main_window.memory.save_all_memory()
                                    logger.info("✅ 知识图谱已保存（包含所有关系）")

                        except Exception as e:
                            logger.error(f"⚠️ 同步到知识图谱失败: {e}")
                            # 即使同步失败，实体数据已经保存

                    # 刷新界面
                    self.refresh_graph()

                    QMessageBox.information(dialog, "成功", success_msg)
                    dialog.accept()

                except Exception as e:
                    logger.error(f"保存节点失败: {e}")
                    logger.error(f"详细错误: {traceback.format_exc()}")
                    QMessageBox.critical(dialog, "保存失败", f"节点保存失败：\n\n{str(e)}")

            save_btn.clicked.connect(save_changes)

            button_layout.addWidget(cancel_btn)
            button_layout.addWidget(save_btn)
            main_layout.addLayout(button_layout)

            # 显示对话框
            dialog.exec()

        except Exception as e:
            logger.error(f"编辑节点对话框失败: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")
            QMessageBox.critical(self, "错误", f"无法打开编辑对话框：\n\n{str(e)}")

    def edit_node(self):
        """编辑选中的节点"""
        try:
            current_item = self.entity_list.currentItem()
            if not current_item:
                QMessageBox.information(self, "提示", "请先选择要编辑的节点")
                return

            # 从item data获取实体信息
            entity_data = current_item.data(Qt.UserRole)
            if not entity_data:
                QMessageBox.warning(self, "错误", "无法获取节点信息")
                return

            entity_name = entity_data.get('name', '')
            entity_type = entity_data.get('type', 'character')

            self.edit_node_with_python_dialog(entity_name, entity_type)

        except Exception as e:
            logger.error(f"编辑节点失败: {e}")
            QMessageBox.critical(self, "错误", f"编辑节点失败：\n\n{str(e)}")

    def add_node(self):
        """添加新节点"""
        try:
            self.edit_node_with_python_dialog("", "character", is_new_node=True)
        except Exception as e:
            logger.error(f"添加节点失败: {e}")
            QMessageBox.critical(self, "错误", f"添加节点失败：\n\n{str(e)}")

    def delete_node(self):
        """删除节点（支持酒馆模式和本地模式）"""
        try:
            current_item = self.entity_list.currentItem()
            if not current_item:
                QMessageBox.warning(self, "提示", "请先选择要删除的节点")
                return

            # 从item data获取实体信息
            entity_data = current_item.data(Qt.UserRole)
            if not entity_data:
                QMessageBox.warning(self, "错误", "无法获取节点信息")
                return

            entity_name = entity_data.get('name', '')
            entity_type = entity_data.get('type', 'character')

            reply = QMessageBox.question(
                self,
                "确认删除",
                f"确定要删除节点 '{entity_name}' 吗？\n此操作不可撤销。",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                # 根据模式选择删除方式
                if getattr(self, 'tavern_mode', False) and getattr(self, 'tavern_session_id', None):
                    # 酒馆模式：通过API删除
                    logger.info(f"🗑️ [酒馆模式] 删除节点: {entity_name}")
                    try:
                        import requests
                        api_base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:9543")
                        response = requests.delete(
                            f"{api_base_url}/sessions/{self.tavern_session_id}/nodes/{entity_name}",
                            timeout=30
                        )
                        if response.status_code == 200:
                            logger.info(f"✅ [酒馆模式] 节点删除成功: {entity_name}")
                            success_msg = f"节点 '{entity_name}' 删除成功"
                        else:
                            logger.error(f"❌ [酒馆模式] API删除节点失败: {response.status_code}")
                            QMessageBox.critical(self, "删除失败", f"API删除失败: {response.status_code}")
                            return
                    except Exception as api_err:
                        logger.error(f"❌ [酒馆模式] 删除节点API调用失败: {api_err}")
                        QMessageBox.critical(self, "删除失败", f"删除节点失败：\n\n{str(api_err)}")
                        return
                else:
                    # 本地模式：删除实体
                    logger.info(f"🗑️ [本地模式] 删除节点: {entity_name}")

                    # 从实体文件中删除
                    all_entities = self.get_all_entities()
                    entity_index = -1
                    for i, entity in enumerate(all_entities):
                        if entity['name'] == entity_name and entity['type'] == entity_type:
                            entity_index = i
                            break

                    if entity_index >= 0:
                        # 删除实体
                        removed_entity = all_entities.pop(entity_index)
                        self.save_entities(all_entities)

                        # 从知识图谱中删除节点（这会自动删除相关关系）
                        try:
                            main_window = None
                            widget = self.parent()
                            while widget is not None:
                                if hasattr(widget, '__class__') and 'MainWindow' in widget.__class__.__name__:
                                    main_window = widget
                                    break
                                widget = widget.parent()

                            if main_window and hasattr(main_window, 'memory'):
                                kg = main_window.memory.knowledge_graph
                                if hasattr(kg, 'graph') and entity_name in kg.graph.nodes:
                                    # 删除节点（NetworkX会自动删除相关边）
                                    kg.graph.remove_node(entity_name)
                                    logger.info(f"✅ 已从知识图谱删除节点: {entity_name}")

                                # 保存知识图谱
                                if hasattr(main_window.memory, 'save_all_memory'):
                                    main_window.memory.save_all_memory()
                                    logger.info("✅ 知识图谱已保存")

                        except Exception as e:
                            logger.warning(f"⚠️ 从知识图谱删除节点失败: {e}")

                        success_msg = f"节点 '{entity_name}' 删除成功"
                        logger.info(f"✅ [本地模式] 节点删除成功: {entity_name}")
                    else:
                        QMessageBox.warning(self, "错误", "找不到要删除的节点")
                        return

                # 清除详情显示
                self.detail_text.clear()
                self.detail_text.setPlaceholderText("选择一个节点查看详细信息...")

                # 刷新界面
                self.refresh_graph()

                QMessageBox.information(self, "成功", success_msg)

        except Exception as e:
            logger.error(f"❌ 删除节点失败: {e}")
            QMessageBox.critical(self, "删除失败", f"删除节点时发生错误：\n\n{str(e)}")

    def save_entities(self, entities):
        """保存实体数据（根据模式选择保存方式）- 与原版一致"""
        try:
            # 在酒馆模式下，通过API保存到后端
            if getattr(self, 'tavern_mode', False) and getattr(self, 'tavern_session_id', None):
                logger.info(f"💾 [酒馆模式] 通过API保存实体数据到会话: {self.tavern_session_id}")

                import requests
                api_base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:9543")

                # 构建实体更新数据
                update_data = {
                    'entities': entities,
                    'last_modified': time.time()
                }

                # 调用API更新实体
                response = requests.post(
                    f"{api_base_url}/sessions/{self.tavern_session_id}/entities",
                    json=update_data,
                    timeout=30
                )

                if response.status_code == 200:
                    logger.info("✅ [酒馆模式] 实体数据已通过API保存")
                else:
                    logger.error(f"❌ [酒馆模式] API保存实体失败: {response.status_code}")
                    raise Exception(f"API保存失败: {response.status_code}")

            else:
                # 本地模式：保存到本地文件
                logger.info("💾 [本地模式] 保存实体数据到本地文件")

                # 获取仓库根目录的data目录
                repo_root = Path(__file__).resolve().parents[3]
                entities_file = repo_root / "data" / "local_mode" / "entities.json"
                entities_file.parent.mkdir(parents=True, exist_ok=True)

                # 获取关系数据（从知识图谱中）
                relationships = []
                main_window = self.window()
                if main_window and hasattr(main_window, 'memory') and hasattr(main_window.memory, 'knowledge_graph'):
                    kg = main_window.memory.knowledge_graph
                    if hasattr(kg, 'graph'):
                        for source, target, attrs in kg.graph.edges(data=True):
                            relationship = {
                                'source': source,
                                'target': target,
                                'relationship': attrs.get('relationship', 'related_to'),
                                'description': attrs.get('description', ''),
                                'attributes': {k: v for k, v in attrs.items() if k not in ['relationship', 'description']}
                            }
                            relationships.append(relationship)

                data = {
                    'entities': entities,
                    'relationships': relationships,  # 确保保存关系数据
                    'last_modified': time.time()
                }

                with open(entities_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                logger.info(f"✅ [本地模式] 实体数据已保存到: {entities_file}，包含 {len(relationships)} 个关系")

        except Exception as e:
            logger.error(f"保存实体数据失败: {e}")
            raise e

    def _update_ui_from_api_data(self, nodes: list, links: list):
        """从API数据更新右侧UI组件（实体列表和统计信息）"""
        try:
            # 更新统计信息
            node_count = len(nodes)
            edge_count = len(links)

            from datetime import datetime
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            stats_text = f"""节点数量: {node_count}
关系数量: {edge_count}
最后更新: {current_time}
数据源: API服务器"""

            self.stats_label.setText(stats_text)

            # 更新实体列表
            self.entity_list.clear()

            # 类型映射
            type_display_map = {
                'character': '角色',
                'location': '地点',
                'item': '物品',
                'event': '事件',
                'concept': '概念'
            }

            for node in nodes:
                node_type = node.get('type', 'concept')
                node_name = node.get('name', node.get('id', ''))
                node_desc = node.get('description', '')

                display_type = type_display_map.get(node_type, node_type)

                # 创建显示文本
                item_text = f"【{display_type}】{node_name}"
                if node_desc:
                    # 截断描述以适应显示
                    desc_preview = node_desc[:50] + '...' if len(node_desc) > 50 else node_desc
                    item_text += f" - {desc_preview}"

                # 创建列表项并存储完整数据
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, {
                    'name': node_name,
                    'type': node_type,
                    'description': node_desc,
                    'attributes': {}
                })
                self.entity_list.addItem(item)

            logger.info(f"✅ [酒馆模式] UI已更新: {node_count} 个实体, {edge_count} 个关系")

        except Exception as e:
            logger.error(f"从API数据更新UI失败: {e}")
            # 显示错误状态
            self.stats_label.setText("更新失败")
            self.entity_list.clear()
            self.entity_list.addItem("数据加载失败")

    def clear_graph_display(self):
        """清理图谱显示数据"""
        try:
            logger.info("🧹 清理图谱显示数据...")

            # 清空图谱显示
            if WEBENGINE_AVAILABLE and hasattr(self, 'graph_view'):
                self.graph_view.setHtml("<html><body><p>Loading...</p></body></html>")

            # 清空实体列表
            if hasattr(self, 'entity_list'):
                self.entity_list.clear()

            # 重置统计信息
            if hasattr(self, 'stats_label'):
                self.stats_label.setText("节点数量: 0\n关系数量: 0\n最后更新: 未知")

            # 清空节点详情
            if hasattr(self, 'detail_text'):
                self.detail_text.clear()
                self.detail_text.setPlaceholderText("选择一个节点查看详细信息...")

            logger.info("✅ 图谱显示数据已清理")

        except Exception as e:
            logger.error(f"清理图谱显示失败: {e}")

    def show_attention_analysis(self):
        """显示注意力机制分析对话框"""
        try:
            from loguru import logger
            logger.info("🧠 开始注意力机制分析...")

            if not self.memory:
                QMessageBox.warning(self, "错误", "记忆系统未初始化，无法进行注意力分析")
                return

            # 检查是否有注意力机制功能
            if not hasattr(self.memory, 'get_entity_importance_report'):
                QMessageBox.warning(self, "功能不可用", "当前记忆系统不支持注意力机制分析")
                return

            # 创建分析对话框
            dialog = QDialog(self)
            dialog.setWindowTitle("🧠 注意力机制分析报告")
            dialog.setMinimumSize(900, 700)
            dialog.setModal(True)
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #2b2b2b;
                    color: #ffffff;
                }
                QLabel {
                    color: #ffffff;
                }
                QComboBox {
                    background-color: #3c3c3c;
                    color: #ffffff;
                    border: 1px solid #555555;
                    border-radius: 4px;
                    padding: 5px;
                    min-height: 20px;
                }
                QComboBox::drop-down {
                    border: none;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 5px solid #ffffff;
                    margin-right: 5px;
                }
                QComboBox QAbstractItemView {
                    background-color: #3c3c3c;
                    color: #ffffff;
                    selection-background-color: #ff6b35;
                }
            """)

            layout = QVBoxLayout(dialog)

            # 标题
            title_label = QLabel("EchoGraph 注意力机制分析")
            title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #ff6b35; margin: 10px;")
            title_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(title_label)

            # 说明文本
            desc_label = QLabel("此功能分析知识图谱中实体的重要性，帮助解决LLM注意力分散问题。\n"
                              "通过过滤低重要性实体，可以显著提升对话质量和响应准确性。")
            desc_label.setStyleSheet("""
                color: #cccccc;
                margin: 10px;
                padding: 15px;
                background-color: #3c3c3c;
                border-radius: 8px;
                border-left: 4px solid #ff6b35;
                font-size: 14px;
                line-height: 1.4;
            """)
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

            # 角色选择
            character_layout = QHBoxLayout()
            character_layout.addWidget(QLabel("分析角色:"))
            character_combo = QComboBox()

            # 获取可用角色列表
            try:
                entities_data = {}
                if hasattr(self.memory, 'entities_json_path') and os.path.exists(self.memory.entities_json_path):
                    with open(self.memory.entities_json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for entity in data.get('entities', []):
                            if entity.get('type') == 'character':
                                character_combo.addItem(entity.get('name', ''))

                if character_combo.count() == 0:
                    character_combo.addItem("未找到角色")

            except Exception as e:
                character_combo.addItem("加载角色失败")
                logger.error(f"加载角色列表失败: {e}")

            character_layout.addWidget(character_combo)
            character_layout.addStretch()
            layout.addLayout(character_layout)

            # 分析结果显示区域
            result_text = QTextEdit()
            result_text.setReadOnly(True)
            result_text.setMinimumHeight(300)
            result_text.setStyleSheet("""
                QTextEdit {
                    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                    font-size: 13px;
                    background-color: #1e1e1e;
                    color: #d4d4d4;
                    border: 2px solid #404040;
                    border-radius: 8px;
                    padding: 15px;
                    selection-background-color: #264f78;
                    selection-color: #ffffff;
                }
                QTextEdit:focus {
                    border-color: #ff6b35;
                }
            """)
            layout.addWidget(result_text)

            # 按钮区域
            button_layout = QHBoxLayout()

            analyze_btn = QPushButton("🔍 开始分析")
            analyze_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ff6b35;
                    color: white;
                    font-weight: bold;
                    padding: 10px 20px;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #e55a2b;
                }
                QPushButton:pressed {
                    background-color: #d14d20;
                }
            """)

            optimize_btn = QPushButton("⚡ 获取优化上下文")
            optimize_btn.setStyleSheet("""
                QPushButton {
                    background-color: #28a745;
                    color: white;
                    font-weight: bold;
                    padding: 10px 20px;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #218838;
                }
                QPushButton:pressed {
                    background-color: #1e7e34;
                }
            """)

            close_btn = QPushButton("关闭")
            close_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6c757d;
                    color: white;
                    font-weight: bold;
                    padding: 10px 20px;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #5a6268;
                }
                QPushButton:pressed {
                    background-color: #545b62;
                }
            """)
            close_btn.clicked.connect(dialog.accept)

            button_layout.addWidget(analyze_btn)
            button_layout.addWidget(optimize_btn)
            button_layout.addStretch()
            button_layout.addWidget(close_btn)
            layout.addLayout(button_layout)

            def run_analysis():
                """运行注意力分析"""
                try:
                    character_name = character_combo.currentText()
                    if not character_name or character_name in ["未找到角色", "加载角色失败"]:
                        result_text.setText("❌ 请选择有效的角色进行分析")
                        return

                    result_text.setText("🔄 正在分析中，请稍候...")
                    dialog.repaint()  # 强制刷新界面

                    # 为测试添加一些模拟对话历史（如果当前没有对话历史）
                    if len(self.memory.basic_memory.conversation_history) == 0:
                        logger.info("添加模拟对话历史用于注意力分析测试")
                        self.memory.add_conversation(
                            f"告诉我关于{character_name}的信息",
                            f"{character_name}是一个复杂的角色，有很多相关的背景信息"
                        )
                        self.memory.add_conversation(
                            "还有什么特别的地方吗？",
                            "确实有很多独特的特征和关联实体"
                        )

                    # 获取分析报告
                    report = self.memory.get_entity_importance_report(character_name)

                    if "error" in report:
                        result_text.setText(f"❌ 分析失败: {report['error']}")
                        return

                    # 格式化显示结果 - 使用HTML格式以支持颜色
                    result_html = []
                    result_html.append('<div style="font-family: Consolas, Monaco, monospace; font-size: 13px; line-height: 1.4;">')
                    result_html.append('<div style="color: #ff6b35; font-weight: bold; font-size: 16px; text-align: center; margin-bottom: 15px;">')
                    result_html.append('🧠 EchoGraph 注意力机制分析报告')
                    result_html.append('</div>')

                    result_html.append('<div style="color: #4fc3f7; font-weight: bold; margin-bottom: 10px;">📊 基本统计</div>')
                    result_html.append(f'<div style="color: #81c784;">🎯 分析角色: <span style="color: #ffb74d;">{report["character_name"]}</span></div>')
                    result_html.append(f'<div style="color: #81c784;">📊 总实体数: <span style="color: #ffb74d;">{report["total_entities"]}</span></div>')
                    result_html.append(f'<div style="color: #81c784;">✨ 重要实体数: <span style="color: #ffb74d;">{report["entities_above_threshold"]}</span></div>')
                    result_html.append(f'<div style="color: #81c784;">🔥 过滤比例: <span style="color: #f48fb1;">{report["filter_ratio"]:.1%}</span></div>')
                    result_html.append(f'<div style="color: #81c784;">⚡ 重要性阈值: <span style="color: #ffb74d;">{report["threshold"]}</span></div>')
                    result_html.append(f'<div style="color: #81c784;">📝 最大上下文实体数: <span style="color: #ffb74d;">{report["max_context_entities"]}</span></div>')
                    result_html.append('<br>')

                    result_html.append('<div style="color: #4fc3f7; font-weight: bold; margin-bottom: 10px;">🏆 实体重要性排序 (前15个)</div>')
                    result_html.append('<table style="width: 100%; border-collapse: collapse; margin-bottom: 15px;">')
                    result_html.append('<tr style="background-color: #404040; color: #ffffff; font-weight: bold;">')
                    result_html.append('<td style="padding: 8px; border: 1px solid #555;">实体名称</td>')
                    result_html.append('<td style="padding: 8px; border: 1px solid #555;">类型</td>')
                    result_html.append('<td style="padding: 8px; border: 1px solid #555;">总分</td>')
                    result_html.append('<td style="padding: 8px; border: 1px solid #555;">集体</td>')
                    result_html.append('<td style="padding: 8px; border: 1px solid #555;">整体</td>')
                    result_html.append('<td style="padding: 8px; border: 1px solid #555;">通过</td>')
                    result_html.append('</tr>')

                    for i, entity in enumerate(report['entity_scores'][:15]):
                        name = entity['name'][:30]
                        entity_type = entity['type']
                        importance = entity['importance_score']
                        collective = entity['collective_score']
                        holistic = entity['holistic_score']
                        passed = "✅" if entity['above_threshold'] else "❌"

                        # 交替行颜色
                        bg_color = "#3c3c3c" if i % 2 == 0 else "#2b2b2b"

                        # 根据重要性评分设置颜色
                        if importance >= 0.7:
                            score_color = "#4caf50"  # 绿色 - 高重要性
                        elif importance >= 0.4:
                            score_color = "#ff9800"  # 橙色 - 中等重要性
                        else:
                            score_color = "#f44336"  # 红色 - 低重要性

                        result_html.append(f'<tr style="background-color: {bg_color};">')
                        result_html.append(f'<td style="padding: 6px; border: 1px solid #555; color: #e0e0e0;">{name}</td>')
                        result_html.append(f'<td style="padding: 6px; border: 1px solid #555; color: #81c784;">{entity_type}</td>')
                        result_html.append(f'<td style="padding: 6px; border: 1px solid #555; color: {score_color}; font-weight: bold;">{importance:.3f}</td>')
                        result_html.append(f'<td style="padding: 6px; border: 1px solid #555; color: #90caf9;">{collective:.3f}</td>')
                        result_html.append(f'<td style="padding: 6px; border: 1px solid #555; color: #ce93d8;">{holistic:.3f}</td>')
                        result_html.append(f'<td style="padding: 6px; border: 1px solid #555; text-align: center;">{passed}</td>')
                        result_html.append('</tr>')

                    result_html.append('</table>')

                    result_html.append('<div style="color: #4fc3f7; font-weight: bold; margin-bottom: 10px;">📈 配置参数</div>')
                    config = report['config']
                    result_html.append(f'<div style="color: #81c784; margin-left: 15px;">集体重要性权重: <span style="color: #ffb74d;">{config["collective_weight"]}</span></div>')
                    result_html.append(f'<div style="color: #81c784; margin-left: 15px;">整体重要性权重: <span style="color: #ffb74d;">{config["holistic_weight"]}</span></div>')
                    result_html.append(f'<div style="color: #81c784; margin-left: 15px;">重要性阈值: <span style="color: #ffb74d;">{config["importance_threshold"]}</span></div>')
                    result_html.append(f'<div style="color: #81c784; margin-left: 15px;">最大上下文实体数: <span style="color: #ffb74d;">{config["max_context_entities"]}</span></div>')
                    result_html.append('<br>')

                    result_html.append('<div style="color: #4fc3f7; font-weight: bold; margin-bottom: 10px;">💡 分析说明</div>')
                    result_html.append('<div style="color: #b0bec5; margin-left: 15px; line-height: 1.6;">')
                    result_html.append('• <span style="color: #81c784;">总分</span> = 集体重要性 × 权重 + 整体重要性 × 权重<br>')
                    result_html.append('• <span style="color: #90caf9;">集体重要性</span>基于对话历史中的提及频率和相关性<br>')
                    result_html.append('• <span style="color: #ce93d8;">整体重要性</span>基于实体类型、关系数量和质量<br>')
                    result_html.append('• 只有通过阈值的实体才会包含在优化上下文中')
                    result_html.append('</div>')
                    result_html.append('</div>')

                    result_text.setHtml("".join(result_html))
                    logger.info(f"✅ 注意力分析完成: {character_name}")

                except Exception as e:
                    result_text.setText(f"❌ 分析过程中发生错误:\n{str(e)}")
                    logger.error(f"注意力分析失败: {e}")

            def get_optimized_context():
                """获取优化后的上下文"""
                try:
                    character_name = character_combo.currentText()
                    if not character_name or character_name in ["未找到角色", "加载角色失败"]:
                        result_text.setText("❌ 请选择有效的角色获取优化上下文")
                        return

                    result_text.setText("⚡ 正在生成优化上下文...")
                    dialog.repaint()

                    # 确保有对话历史用于上下文优化
                    if len(self.memory.basic_memory.conversation_history) == 0:
                        logger.info("添加模拟对话历史用于上下文优化")
                        self.memory.add_conversation(
                            f"我想了解{character_name}",
                            f"让我为你介绍{character_name}的相关信息"
                        )

                    # 获取优化上下文
                    optimized_context = self.memory.get_optimized_character_context(character_name)

                    # 显示优化上下文 - 使用HTML格式
                    context_html = []
                    context_html.append('<div style="font-family: Consolas, Monaco, monospace; font-size: 13px; line-height: 1.4;">')

                    context_html.append('<div style="color: #ff6b35; font-weight: bold; font-size: 16px; text-align: center; margin-bottom: 15px;">')
                    context_html.append('⚡ 优化后的角色上下文')
                    context_html.append('</div>')

                    context_html.append('<div style="color: #4fc3f7; font-weight: bold; margin-bottom: 10px;">📊 上下文统计</div>')
                    context_html.append(f'<div style="color: #81c784;">角色: <span style="color: #ffb74d;">{character_name}</span></div>')
                    context_html.append(f'<div style="color: #81c784;">字符数: <span style="color: #ffb74d;">{len(optimized_context)}</span></div>')
                    context_html.append(f'<div style="color: #81c784;">行数: <span style="color: #ffb74d;">{optimized_context.count(chr(10)) + 1}</span></div>')
                    context_html.append('<br>')

                    context_html.append('<div style="color: #4fc3f7; font-weight: bold; margin-bottom: 10px;">� 优化上下文内容</div>')
                    context_html.append('<div style="background-color: #1a1a1a; border: 2px solid #404040; border-radius: 8px; padding: 15px; margin: 10px 0; white-space: pre-wrap; font-family: Consolas, Monaco, monospace;">')

                    # 处理上下文内容，添加基本的语法高亮
                    import html
                    escaped_context = html.escape(optimized_context)

                    # 简单的语法高亮
                    highlighted_context = escaped_context
                    highlighted_context = highlighted_context.replace('【', '<span style="color: #ff6b35; font-weight: bold;">【')
                    highlighted_context = highlighted_context.replace('】', '】</span>')
                    highlighted_context = highlighted_context.replace('- ', '<span style="color: #81c784;">- </span>')

                    context_html.append(f'<span style="color: #e0e0e0;">{highlighted_context}</span>')
                    context_html.append('</div>')

                    context_html.append('<div style="color: #4fc3f7; font-weight: bold; margin-bottom: 10px;">💡 使用说明</div>')
                    context_html.append('<div style="color: #b0bec5; margin-left: 15px; line-height: 1.6;">')
                    context_html.append('• 此上下文已通过<span style="color: #ff6b35;">注意力机制</span>优化，过滤了低重要性实体<br>')
                    context_html.append('• 可直接用于<span style="color: #81c784;">LLM对话</span>，提升响应质量和准确性<br>')
                    context_html.append('• 保留了角色的<span style="color: #90caf9;">核心特征</span>和<span style="color: #ce93d8;">重要关联</span>')
                    context_html.append('</div>')
                    context_html.append('</div>')

                    result_text.setHtml("".join(context_html))
                    logger.info(f"✅ 优化上下文生成完成: {character_name}")

                except Exception as e:
                    result_text.setText(f"❌ 生成优化上下文时发生错误:\n{str(e)}")
                    logger.error(f"生成优化上下文失败: {e}")

            # 连接按钮事件
            analyze_btn.clicked.connect(run_analysis)
            optimize_btn.clicked.connect(get_optimized_context)

            # 显示对话框
            dialog.exec()

        except Exception as e:
            logger.error(f"显示注意力分析对话框失败: {e}")
            QMessageBox.critical(self, "错误", f"无法显示注意力分析对话框:\n{str(e)}")
