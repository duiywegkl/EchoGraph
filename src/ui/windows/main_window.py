"""
主窗口模块
"""

import sys
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QVBoxLayout,
    QWidget, QMenuBar, QStatusBar, QMessageBox,
    QFileDialog
)
from PySide6.QtCore import Signal, QTimer, Qt  # [OK] 修正导入
from PySide6.QtGui import QIcon, QAction
from loguru import logger
from dotenv import dotenv_values
import requests
from version import get_version_info

from ..components import (
    ComponentManager
)
from ..pages.integrated_play_page import IntegratedPlayPage
from ..pages.graph_page import GraphPage
from ..pages.config_page import ConfigPage

# 引入记忆系统和管理器（按 bak 的方式接回本地模式）
from src.memory.grag_memory import GRAGMemory
from src.ui.managers.scenario_manager import ScenarioManager

class MainWindow(QMainWindow):
    """主窗口类"""

    # 窗口信号 - 使用Signal替代pyqtSignal
    window_closing = Signal()  # [OK] 修正信号声明
    config_changed = Signal(dict)
    status_update = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # API服务器相关配置
        repo_root = Path(__file__).resolve().parents[3]
        env_path = repo_root / ".env"
        config = dotenv_values(env_path) if env_path.exists() else {}
        self.api_server_port = int(config.get("API_SERVER_PORT", "9543"))
        self.api_server_process = None

        self.component_manager = ComponentManager()

        # 启动API服务器
        self.start_api_server()

        # 在启动或连接到已有API服务器后，强制关闭酒馆模式，确保默认本地隔离
        try:
            requests.post(f"http://localhost:{self.api_server_port}/system/tavern_mode", json={"active": False}, timeout=3)
        except Exception:
            pass

        self.setup_ui()
        self.connect_signals()

    def init_components(self):
        """初始化核心组件"""
        logger.info("初始化EchoGraph核心组件...")

        try:
            # 初始化核心系统 - 本地模式使用独立目录
            repo_root = Path(__file__).resolve().parents[3]
            base_path = repo_root / "data"
            local_mode_path = base_path / "local_mode"  # 本地模式专用目录
            local_mode_path.mkdir(exist_ok=True, parents=True)

            self.memory = GRAGMemory(
                hot_memory_size=10,
                graph_save_path=str(local_mode_path / "knowledge_graph.graphml"),
                entities_json_path=str(local_mode_path / "entities.json"),  # 本地模式专用路径
                auto_load_entities=True  # 本地模式需要加载已有的对话数据
            )

            # 初始化其他核心组件
            from src.core.perception import PerceptionModule
            from src.core.rpg_text_processor import RPGTextProcessor
            from src.core.validation import ValidationLayer
            from src.core.game_engine import GameEngine

            self.perception = PerceptionModule()
            self.rpg_processor = RPGTextProcessor()
            self.validation_layer = ValidationLayer()

            # 创建游戏引擎
            self.game_engine = GameEngine(
                self.memory,
                self.perception,
                self.rpg_processor,
                self.validation_layer
            )

            # 初始化酒馆模式管理器
            from src.tavern.tavern_connector import TavernModeManager
            self.tavern_manager = TavernModeManager(self.game_engine)

            logger.info("核心组件初始化完成")

        except Exception as e:
            logger.error(f"核心组件初始化失败: {e}")
            QMessageBox.critical(self, "初始化错误", f"无法初始化核心组件：\n{e}")
            sys.exit(1)

    def init_managers(self):
        """初始化管理器组件"""
        try:
            # 场景管理器
            self.scenario_manager = ScenarioManager(
                self.memory,
                self.perception,
                self.rpg_processor,
                self.validation_layer
            )

            # 资源清理管理器
            from src.ui.managers.resource_cleanup_manager import ResourceCleanupManager
            self.cleanup_manager = ResourceCleanupManager(self)

            logger.info("管理器组件初始化完成")

        except Exception as e:
            logger.error(f"管理器初始化失败: {e}")
            QMessageBox.critical(self, "初始化错误", f"无法初始化管理器组件：\n{e}")
            sys.exit(1)

    def setup_ui(self):
        """设置UI界面"""
        # 获取版本信息并设置窗口标题
        version_info = get_version_info()
        self.setWindowTitle(f"EchoGraph v{version_info['version']} - 智能角色扮演助手")
        self.setGeometry(100, 100, 1200, 800)

        # 设置图标（如果存在）
        self._set_application_icon()

        # 原始布局不包含顶部菜单栏，此处不创建菜单栏

        # 初始化核心组件（按 run_ui.bak 的完整逻辑）
        self.init_components()

        # 初始化管理器
        self.init_managers()

        # 创建中心widget
        self._create_central_widget()

        # 创建状态栏
        self._create_status_bar()

        # 注册组件
        self._register_components()

    def _set_application_icon(self):
        """设置应用程序图标"""
        try:
            # 尝试多个可能的图标路径，优先使用ICO格式（Windows兼容性更好）
            icon_paths = [
                Path("assets/icon.ico"),
                Path("assets/icons/OIG1.png"),
                Path("assets/icon.png"),
                Path("icon.ico"),
                Path("icon.png")
            ]

            for icon_path in icon_paths:
                if icon_path.exists():
                    logger.info(f"🎨 尝试加载应用图标: {icon_path}")
                    try:
                        # 先测试文件是否可读
                        with open(icon_path, 'rb') as f:
                            f.read(10)  # 读取前10字节测试

                        icon = QIcon(str(icon_path.resolve()))  # 使用绝对路径
                        if not icon.isNull():
                            self.setWindowIcon(icon)
                            # 同时设置应用程序级别的图标
                            from PySide6.QtWidgets import QApplication
                            app = QApplication.instance()
                            if app:
                                app.setWindowIcon(icon)
                            logger.info(f"✅ 应用图标设置成功: {icon_path}")
                            return True
                        else:
                            logger.warning(f"⚠️ 图标文件无法解析: {icon_path}")
                    except Exception as e:
                        logger.warning(f"⚠️ 加载图标失败 {icon_path}: {e}")
                        continue

            logger.warning("⚠️ 未找到有效的应用图标文件")
            return False

        except Exception as e:
            logger.error(f"❌ 设置应用图标失败: {e}")
            return False

    def _create_menu_bar(self):
        """创建菜单栏"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件")

        # 新建配置
        new_config_action = QAction("新建配置", self)
        new_config_action.triggered.connect(self._new_config)
        file_menu.addAction(new_config_action)

        # 加载配置
        load_config_action = QAction("加载配置", self)
        load_config_action.triggered.connect(self._load_config)
        file_menu.addAction(load_config_action)

        # 保存配置
        save_config_action = QAction("保存配置", self)
        save_config_action.triggered.connect(self._save_config)
        file_menu.addAction(save_config_action)

        file_menu.addSeparator()

        # 退出
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 工具菜单
        tools_menu = menubar.addMenu("工具")

        # 清空日志
        clear_logs_action = QAction("清空日志", self)
        clear_logs_action.triggered.connect(self._clear_logs)
        tools_menu.addAction(clear_logs_action)

        # 导出日志
        export_logs_action = QAction("导出日志", self)
        export_logs_action.triggered.connect(self._export_logs)
        tools_menu.addAction(export_logs_action)

        tools_menu.addSeparator()

        # 系统信息
        system_info_action = QAction("系统信息", self)
        system_info_action.triggered.connect(self._show_system_info)
        tools_menu.addAction(system_info_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助")

        # 关于
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_central_widget(self):
        """创建中心widget"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 标签页布局（与原始布局一致：对话 / 知识图谱 / 系统配置）
        main_layout = QVBoxLayout(central_widget)
        self.tabs = QTabWidget()

        # 智能对话页面 - 使用已初始化的game_engine
        try:
            self.play_page = IntegratedPlayPage(self.game_engine)
        except Exception as e:
            logger.error(f"创建IntegratedPlayPage失败: {e}")
            # 使用简化版本作为备用
            self.play_page = IntegratedPlayPage(None)

        self.tabs.addTab(self.play_page, "智能对话")

        # 知识图谱页面
        self.graph_page = GraphPage(self.memory)
        self.tabs.addTab(self.graph_page, "知识图谱")

        # 系统配置页面
        self.config_page = ConfigPage()
        self.tabs.addTab(self.config_page, "系统配置")

        main_layout.addWidget(self.tabs)

        # 页面联动：当对话切换时，处理知识图谱的初始化或刷新
        try:
            conv_mgr = getattr(self.play_page, "conv_manager", None)
            if conv_mgr is not None:
                conv_mgr.conversation_changed.connect(self._on_conversation_changed)
        except Exception as e:
            logger.warning(f"注册对话切换联动失败: {e}")


    def _create_status_bar(self):
        """创建状态栏"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # 获取版本信息并显示在状态栏
        version_info = get_version_info()
        self.status_bar.showMessage(f"EchoGraph v{version_info['version']} ({version_info['codename']}) - 已启动")

        # 定时更新状态
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status_bar)
        self.status_timer.start(30000)  # 每30秒更新一次

    def _register_components(self):
        """注册组件（仅注册可用组件）"""
        # 注册对话界面的底层组件，便于统一初始化/清理
        if hasattr(self.play_page, "chat"):
            self.component_manager.register_component("chat_interface", self.play_page.chat)
        # 注册配置面板组件
        if hasattr(self.config_page, "config_panel"):
            self.component_manager.register_component("config_panel", self.config_page.config_panel)

        # 初始化所有组件（若已初始化将被跳过）
        self.component_manager.initialize_all_components()

    def connect_signals(self):
        """连接信号和槽"""
        # 配置面板信号
        if hasattr(self.config_page, "config_panel"):
            self.config_page.config_panel.config_updated.connect(self._on_config_updated)
            self.config_page.config_panel.config_saved.connect(self._on_config_saved)

        # 对话界面信号
        self.play_page.message_sent.connect(self._on_message_sent)

        # 原布局中无"状态监控"页，故不绑定相关信号

    def _on_config_updated(self, config: Dict[str, Any]):
        """配置更新处理"""
        logger.info("[Config] 配置已更新")
        self.config_changed.emit(config)

    def _on_config_saved(self):
        """配置保存处理"""
        self.status_bar.showMessage("配置已保存", 3000)

    def _on_message_sent(self, message: str):
        """消息发送处理"""
        logger.debug(f"[Chat] 用户发送消息: {message[:50]}...")

        # 这里可以添加消息处理逻辑
        # 例如调用LLM API等

    def _on_system_alert(self, level: str, message: str):
        """系统警报处理"""
        if level == "ERROR":
            QMessageBox.critical(self, "系统错误", message)
        elif level == "WARNING":
            QMessageBox.warning(self, "系统警告", message)

    def _new_config(self):
        """新建配置"""
        reply = QMessageBox.question(
            self, "确认", "确定要创建新配置吗？当前配置将被重置。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,  # [OK] 修正枚举语法
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.config_page.reset_config()
            self.status_bar.showMessage("新配置已创建", 3000)

    def _load_config(self):
        """加载配置"""
        self.config_page.load_config()

    def _save_config(self):
        """保存配置"""
        self.config_page.save_config()

    def _clear_logs(self):
        """清空日志"""
        reply = QMessageBox.question(
            self, "确认", "确定要清空所有日志吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # 原布局无独立状态监控日志，这里仅提示
            QMessageBox.information(self, "提示", "当前布局未启用状态日志面板")

    def _export_logs(self):
        """导出日志"""
        QMessageBox.information(self, "提示", "当前布局未启用状态日志面板")

    def _show_system_info(self):
        """显示系统信息"""
        import platform
        import psutil

        info = f"""
EchoGraph 系统信息

版本: 2.0.0
Python版本: {platform.python_version()}
系统: {platform.system()} {platform.release()}
CPU使用率: {psutil.cpu_percent()}%
内存使用率: {psutil.virtual_memory().percent}%

组件状态:
{self._get_component_status()}
"""
        QMessageBox.information(self, "系统信息", info.strip())

    def _get_component_status(self) -> str:
        """获取组件状态（原布局无状态卡片）"""
        return "N/A"

    def _show_about(self):
        """显示关于信息"""
        version_info = get_version_info()
        about_text = f"""
EchoGraph - 智能角色扮演助手

版本: {version_info['version']} ({version_info['codename']})
发布日期: {version_info['release_date']}
发布类型: {version_info['release_type']}
开发者: EchoGraph Team

{version_info['description']}

© 2024 EchoGraph Team. All rights reserved.
"""
        QMessageBox.about(self, f"关于 EchoGraph v{version_info['version']}", about_text.strip())

    def _update_status_bar(self):
        """更新状态栏（简化）"""
        version_info = get_version_info()
        self.status_bar.showMessage(f"EchoGraph v{version_info['version']} ({version_info['codename']}) - 运行中")

    def closeEvent(self, event):
        """关闭事件处理 - 完整的资源清理流程"""
        logger.info("🔄 程序退出中，正在保存数据...")

        # 保存当前会话数据
        try:
            if hasattr(self, 'memory') and self.memory:
                logger.info("💾 保存知识图谱和记忆数据...")
                self.memory.save_all_memory()
                logger.info("✅ 数据保存完成")
        except Exception as e:
            logger.error(f"❌ 保存数据失败: {e}")

        # 关闭API日志文件
        if hasattr(self, 'api_log_file') and self.api_log_file:
            try:
                logger.info("📝 Closing API log file...")
                self.api_log_file.close()
                self.api_log_file = None
            except Exception as e:
                logger.error(f"❌ Error closing API log file: {e}")

        # 使用资源清理管理器进行完整清理
        if hasattr(self, 'cleanup_manager') and self.cleanup_manager:
            success = self.cleanup_manager.cleanup_all_resources()
            if success:
                event.accept()
            else:
                event.accept()  # 即使出错也要关闭
        else:
            # 备用清理逻辑
            self.window_closing.emit()

            # 清理组件（先清理页面组件）
            if hasattr(self, 'play_page') and self.play_page:
                self.play_page.cleanup()

            # 清理组件管理器
            self.component_manager.cleanup_all_components()

            # 清理API服务器进程
            if hasattr(self, 'api_server_process') and self.api_server_process and self.api_server_process.poll() is None:
                try:
                    logger.info("🛑 正在关闭API服务器...")
                    self.api_server_process.terminate()
                    self.api_server_process.wait(timeout=5)
                    logger.info("✅ API服务器已关闭")
                except Exception as e:
                    logger.error(f"❌ 关闭API服务器失败: {e}")
                    # 强制终止
                    try:
                        self.api_server_process.kill()
                    except Exception:
                        pass

            logger.info("[Window] EchoGraph 主窗口关闭")
            event.accept()

    def show_message(self, message: str, duration: int = 3000):
        """在状态栏显示消息"""
        self.status_bar.showMessage(message, duration)

    def add_system_message(self, message: str):
        """添加系统消息到对话界面"""
        self.play_page.add_system_message(message)

    def add_assistant_message(self, message: str):
        """添加助手消息到对话界面"""
        self.play_page.add_assistant_message(message)

    # -------- 对话切换联动知识图谱 --------
    def _on_conversation_changed(self, conv_id: str):
        try:
            logger.info(f"[UI] 对话切换: {conv_id}")

            # 如果conv_id为空，说明没有剩余对话
            if not conv_id:
                logger.info("没有剩余对话，保持当前状态")
                return

            conv_mgr = getattr(self.play_page, "conv_manager", None)
            if conv_mgr is None:
                return
            conv = conv_mgr.get_current_conversation()

            # 检查对话是否有消息内容
            if not conv:
                logger.warning(f"对话 {conv_id} 不存在")
                return

            messages = conv.get('messages', [])
            if not messages:
                # 新对话或空对话 - 询问是否创建默认开局（与原版逻辑一致）
                logger.info("这是一个空对话，询问是否创建默认开局")
                self._prompt_initialize_knowledge_graph(conv_id)
            else:
                # 有内容的对话 - 不做任何操作，保持当前知识图谱
                logger.info("切换到有内容的对话，保持当前知识图谱状态")
        except Exception as e:
            logger.warning(f"处理对话切换失败: {e}")

    def _prompt_initialize_knowledge_graph(self, conv_id: str):
        try:
            # 防止重复调用的标志（与原版一致）
            if hasattr(self, '_initializing_knowledge_graph') and self._initializing_knowledge_graph:
                logger.info("知识图谱正在初始化中，跳过重复调用")
                return

            try:
                self._initializing_knowledge_graph = True

                # 获取对话名称以便更好地提示用户（与原版一致）
                conv_mgr = getattr(self.play_page, "conv_manager", None)
                if conv_mgr:
                    conv = conv_mgr.conversations.get(conv_id)
                    conv_name = conv.get('name', '当前对话') if conv else '当前对话'
                else:
                    conv_name = '当前对话'

                reply = QMessageBox.question(
                    self,
                    "知识图谱初始化",
                    f"对话 \"{conv_name}\" 还没有开始。\n\n是否要创建默认的奇幻游戏开局来开始你的冒险？\n\n点击\"否\"将保持当前知识图谱状态。",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
            finally:
                self._initializing_knowledge_graph = False

            if reply != QMessageBox.Yes:
                return
            if not self.memory:
                QMessageBox.warning(self, "初始化失败", "未找到记忆系统，无法初始化图谱。")
                return
            scenario_manager = ScenarioManager(self.memory, None, None, None)
            opening_story, entity_count, relationship_count = scenario_manager.create_chrono_trigger_scenario()
            # 保存并刷新
            if hasattr(self.memory, 'save_all_memory'):
                self.memory.save_all_memory()
            if hasattr(self, 'graph_page'):
                self.graph_page.refresh_graph()
            # 将开场故事写入对话
            conv_mgr = getattr(self.play_page, "conv_manager", None)
            if conv_mgr:
                conv_mgr.add_message({'role': 'assistant', 'content': opening_story})
            self.play_page.add_assistant_message(opening_story)
            QMessageBox.information(self, "初始化完成", f"已创建默认世界：{entity_count} 个实体，{relationship_count} 条关系。")
        except Exception as e:
            logger.error(f"初始化知识图谱失败: {e}")

    def get_current_config(self):
        """获取当前配置"""
        return self.config_page.get_current_config()

    def set_config(self, config: Dict[str, Any]):
        """设置配置"""
        self.config_page.set_config(config)

    def update_status_card(self, card_name: str, status: str, progress: Optional[int] = None):
        """更新状态卡片（原布局无状态卡片）"""
        pass

    # ============= API服务器管理方法 =============

    def check_api_server_running(self):
        """检查API服务器是否已经在运行"""
        try:
            # 尝试连接到健康检查端点
            response = requests.get(f"http://localhost:{self.api_server_port}/system/liveness", timeout=2)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            # 连接失败，说明服务器没有运行
            return False
        except Exception as e:
            logger.warning(f"检查API服务器状态时出错: {e}")
            return False

    def start_api_server(self):
        """启动API服务器"""
        try:
            # 首先检查API服务器是否已经在运行
            if self.check_api_server_running():
                logger.error(f"❌ API服务器已在端口 {self.api_server_port} 运行！")
                logger.error("请先关闭现有的API服务器进程，然后重新启动UI。")

                # 尝试自动清理僵尸进程
                cleaned = self._try_cleanup_zombie_api_server()

                if not cleaned:
                    # 显示错误对话框
                    QMessageBox.critical(
                        self,
                        "API服务器冲突",
                        f"检测到API服务器已在端口 {self.api_server_port} 运行！\n\n"
                        f"这可能是之前异常退出留下的僵尸进程。\n\n"
                        f"请先关闭现有的API服务器进程，然后重新启动UI。\n\n"
                        f"如果不确定如何关闭，请重启计算机后再试。"
                    )

                    # 退出程序
                    sys.exit(1)
                else:
                    logger.info("✅ 已清理僵尸API服务器进程，继续启动...")
                    # 等待端口释放
                    time.sleep(2)

            api_server_path = str(Path(__file__).resolve().parents[3] / "api_server.py")
            command = [sys.executable, api_server_path, "--port", str(self.api_server_port)]

            logger.info(f"🚀 启动API服务器: {' '.join(command)}")

            # Windows上创建独立进程组
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

            self.api_server_process = subprocess.Popen(
                command,
                creationflags=creation_flags
            )

            logger.info(f"✅ API服务器已启动，PID: {self.api_server_process.pid}")

            # 等待服务器启动
            time.sleep(3)

        except Exception as e:
            logger.error(f"❌ API服务器启动失败: {e}")
            QMessageBox.critical(self, "启动错误", f"无法启动API服务器：\n{e}\n请检查日志获取详细信息。")

    def _try_cleanup_zombie_api_server(self):
        """尝试清理僵尸API服务器进程"""
        try:
            logger.info("🔍 尝试清理僵尸API服务器进程...")
            port = self.api_server_port

            if sys.platform == "win32":
                # Windows: 查找占用端口的进程
                result = subprocess.run(
                    ["netstat", "-ano", "-p", "TCP"],
                    capture_output=True, text=True, check=False
                )

                for line in result.stdout.split('\n'):
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            logger.info(f"🎯 发现占用端口{port}的进程 PID: {pid}")

                            # 检查是否是Python进程（可能是我们的API服务器）
                            try:
                                tasklist_result = subprocess.run(
                                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                                    capture_output=True, text=True, check=False
                                )

                                if "python" in tasklist_result.stdout.lower():
                                    logger.info(f"🔨 终止Python进程 PID {pid}")
                                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                                 check=False, capture_output=True)

                                    # 等待进程终止
                                    time.sleep(1)

                                    # 验证端口是否已释放
                                    if not self.check_api_server_running():
                                        logger.info("✅ 僵尸进程已清理，端口已释放")
                                        return True
                                    else:
                                        logger.warning("⚠️ 进程已终止但端口仍被占用")
                                        return False
                                else:
                                    logger.warning(f"⚠️ 占用端口的进程不是Python进程")
                                    return False

                            except Exception as e:
                                logger.error(f"检查进程信息失败: {e}")
                                return False
            else:
                # Linux/macOS: 使用lsof查找占用端口的进程
                result = subprocess.run(
                    ["lsof", "-ti", f":{port}"],
                    capture_output=True, text=True, check=False
                )

                if result.stdout.strip():
                    pids = result.stdout.strip().split()
                    for pid in pids:
                        logger.info(f"🔨 终止进程 PID {pid}")
                        subprocess.run(["kill", "-9", pid], check=False)

                    # 等待进程终止
                    time.sleep(1)

                    # 验证端口是否已释放
                    if not self.check_api_server_running():
                        logger.info("✅ 僵尸进程已清理，端口已释放")
                        return True

            return False

        except Exception as e:
            logger.error(f"清理僵尸进程失败: {e}")
            return False
