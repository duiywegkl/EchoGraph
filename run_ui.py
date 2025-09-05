"""
ChronoForge 主UI程序
智能角色扮演助手 - 集成对话系统和关系图谱
"""
import sys
import os
import time
import traceback
import subprocess
import json
import requests
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QFormLayout, QLineEdit, QPushButton, QCheckBox, QTabWidget, 
    QMessageBox, QSplitter, QListWidget, QLabel, QTextEdit,
    QGroupBox, QComboBox, QInputDialog, QStyle
)
from PySide6.QtCore import Qt, QObject, Signal as pyqtSignal, QIntValidator
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtGui import QIcon, QFont, QColor
from dotenv import dotenv_values, set_key
from loguru import logger

sys.path.append(str(Path(__file__).parent))
from src.memory import GRAGMemory
from src.core.perception import PerceptionModule
from src.core.rpg_text_processor import RPGTextProcessor
from src.core.game_engine import GameEngine
from src.core.validation import ValidationLayer

from typing import Dict, List, Optional


class ConversationManager(QObject):
    """对话管理器，处理本地对话的CRUD操作"""
    
    conversation_changed = pyqtSignal(str)  # 当前对话改变
    conversation_list_updated = pyqtSignal(list)  # 对话列表更新
    
    def __init__(self, storage_path: Path):
        super().__init__()
        self.storage_path = storage_path / "conversations"
        self.storage_path.mkdir(exist_ok=True, parents=True)
        self.current_conversation_id: Optional[str] = None
        self.conversations: Dict[str, Dict] = {}
        self.load_conversations()
    
    def load_conversations(self):
        """加载所有对话"""
        self.conversations.clear()
        
        for conv_file in self.storage_path.glob("*.json"):
            try:
                with open(conv_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.conversations[data['id']] = data
            except Exception as e:
                logger.error(f"Failed to load conversation {conv_file}: {e}")
        
        # 按最后修改时间排序
        sorted_conversations = sorted(
            self.conversations.values(), 
            key=lambda x: x.get('last_modified', 0), 
            reverse=True
        )
        
        self.conversation_list_updated.emit(sorted_conversations)
        
        # 如果没有当前对话，选择最新的
        if not self.current_conversation_id and sorted_conversations:
            self.current_conversation_id = sorted_conversations[0]['id']
            self.conversation_changed.emit(self.current_conversation_id)
    
    def create_conversation(self, name: str = None) -> str:
        """创建新对话"""
        import uuid
        import time
        
        conv_id = str(uuid.uuid4())
        if not name:
            name = f"新对话 {len(self.conversations) + 1}"
        
        conversation = {
            'id': conv_id,
            'name': name,
            'messages': [],
            'created_time': time.time(),
            'last_modified': time.time(),
            'metadata': {}
        }
        
        self.conversations[conv_id] = conversation
        self._save_conversation(conversation)
        self.load_conversations()  # 重新加载更新列表
        
        # 切换到新对话
        self.current_conversation_id = conv_id
        self.conversation_changed.emit(conv_id)
        
        return conv_id
    
    def delete_conversation(self, conv_id: str) -> bool:
        """删除对话"""
        if conv_id not in self.conversations:
            return False
        
        try:
            conv_file = self.storage_path / f"{conv_id}.json"
            if conv_file.exists():
                conv_file.unlink()
            
            del self.conversations[conv_id]
            
            # 如果删除的是当前对话，切换到其他对话
            if self.current_conversation_id == conv_id:
                remaining_convs = list(self.conversations.keys())
                if remaining_convs:
                    self.current_conversation_id = remaining_convs[0]
                    self.conversation_changed.emit(self.current_conversation_id)
                else:
                    self.current_conversation_id = None
                    self.conversation_changed.emit("")
            
            self.load_conversations()
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete conversation {conv_id}: {e}")
            return False
    
    def rename_conversation(self, conv_id: str, new_name: str) -> bool:
        """重命名对话"""
        if conv_id not in self.conversations:
            return False
        
        try:
            import time
            self.conversations[conv_id]['name'] = new_name
            self.conversations[conv_id]['last_modified'] = time.time()
            self._save_conversation(self.conversations[conv_id])
            self.load_conversations()
            return True
            
        except Exception as e:
            logger.error(f"Failed to rename conversation {conv_id}: {e}")
            return False
    
    def switch_conversation(self, conv_id: str):
        """切换对话"""
        if conv_id in self.conversations:
            self.current_conversation_id = conv_id
            self.conversation_changed.emit(conv_id)
    
    def get_current_conversation(self) -> Optional[Dict]:
        """获取当前对话"""
        if self.current_conversation_id and self.current_conversation_id in self.conversations:
            return self.conversations[self.current_conversation_id]
        return None
    
    def add_message(self, message: Dict):
        """添加消息到当前对话"""
        conv = self.get_current_conversation()
        if conv:
            import time
            message['timestamp'] = time.time()
            conv['messages'].append(message)
            conv['last_modified'] = time.time()
            self._save_conversation(conv)
    
    def clear_current_conversation(self):
        """清空当前对话的消息"""
        conv = self.get_current_conversation()
        if conv:
            import time
            conv['messages'] = []
            conv['last_modified'] = time.time()
            self._save_conversation(conv)
    
    def _save_conversation(self, conversation: Dict):
        """保存对话到文件"""
        conv_file = self.storage_path / f"{conversation['id']}.json"
        try:
            with open(conv_file, 'w', encoding='utf-8') as f:
                json.dump(conversation, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save conversation: {e}")


class IntegratedPlayPage(QWidget):
    """集成的智能对话页面"""
    
    def __init__(self, engine: GameEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.api_base_url = "http://127.0.0.1:9543"
        self.is_test_mode = True  # 默认测试模式
        self.is_connected_to_api = False
        
        # 对话管理器
        self.conversation_manager = ConversationManager(Path(__file__).parent / "data" / "local_conversations")
        
        self.init_ui()
        self.connect_signals()
        self.check_api_connection()
    
    def init_ui(self):
        """初始化UI"""
        layout = QHBoxLayout(self)
        layout.setSpacing(10)
        
        # 左侧：对话区域
        left_panel = self.create_chat_panel()
        
        # 右侧：关系图谱
        right_panel = self.create_graph_panel()
        
        # 使用分割器
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 2)  # 对话区域占2/3
        splitter.setStretchFactor(1, 1)  # 图谱区域占1/3
        
        layout.addWidget(splitter)
    
    def create_chat_panel(self) -> QWidget:
        """创建对话面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 顶部工具栏
        toolbar = self.create_toolbar()
        layout.addWidget(toolbar)
        
        # 对话管理区域
        conv_management = self.create_conversation_management()
        layout.addWidget(conv_management)
        
        # 对话显示区域
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setMinimumHeight(400)
        layout.addWidget(self.chat_display)
        
        # 输入区域
        input_area = self.create_input_area()
        layout.addWidget(input_area)
        
        return panel
    
    def create_toolbar(self) -> QWidget:
        """创建顶部工具栏"""
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        
        # 模式切换
        mode_group = QGroupBox("本地测试模式")
        mode_layout = QHBoxLayout(mode_group)
        
        self.mode_toggle = QCheckBox()
        self.mode_toggle.setChecked(self.is_test_mode)
        self.mode_label = QLabel("本地测试模式")
        
        mode_layout.addWidget(self.mode_toggle)
        mode_layout.addWidget(self.mode_label)
        mode_layout.addStretch()
        
        # 连接状态指示器
        self.status_label = QLabel("API未连接")
        self.status_label.setStyleSheet("""
            QLabel {
                padding: 5px 10px;
                border-radius: 3px;
                background-color: #e74c3c;
                color: white;
                font-weight: bold;
            }
        """)
        
        layout.addWidget(mode_group)
        layout.addStretch()
        layout.addWidget(self.status_label)
        
        return toolbar
    
    def create_conversation_management(self) -> QWidget:
        """创建对话管理区域"""
        group = QGroupBox("对话管理")
        layout = QHBoxLayout(group)
        
        # 对话选择下拉框
        self.conversation_combo = QComboBox()
        self.conversation_combo.setMinimumWidth(200)
        
        # 对话管理按钮
        self.new_conv_btn = QPushButton("新建对话")
        self.new_conv_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        
        self.delete_conv_btn = QPushButton("删除对话")
        self.delete_conv_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        
        self.rename_conv_btn = QPushButton("重命名")
        self.rename_conv_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        
        layout.addWidget(QLabel("当前对话："))
        layout.addWidget(self.conversation_combo)
        layout.addWidget(self.new_conv_btn)
        layout.addWidget(self.rename_conv_btn)
        layout.addWidget(self.delete_conv_btn)
        layout.addStretch()
        
        return group
    
    def create_input_area(self) -> QWidget:
        """创建输入区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 输入框
        self.input_text = QTextEdit()
        self.input_text.setMaximumHeight(100)
        self.input_text.setPlaceholderText("输入你的消息...")
        
        # 按钮行
        button_layout = QHBoxLayout()
        
        self.send_btn = QPushButton("发送")
        self.send_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        
        self.clear_btn = QPushButton("清空对话")
        self.clear_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))
        
        button_layout.addStretch()
        button_layout.addWidget(self.clear_btn)
        button_layout.addWidget(self.send_btn)
        
        layout.addWidget(self.input_text)
        layout.addLayout(button_layout)
        
        return widget
    
    def create_graph_panel(self) -> QWidget:
        """创建关系图谱面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 图谱标题和控制
        header = QHBoxLayout()
        title = QLabel("知识关系图谱")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        
        self.refresh_graph_btn = QPushButton("刷新图谱")
        self.refresh_graph_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.refresh_graph_btn)
        
        layout.addLayout(header)
        
        # 图谱显示
        self.graph_view = QWebEngineView()
        self.graph_view.setMinimumHeight(300)
        layout.addWidget(self.graph_view)
        
        # 实体列表
        self.entity_list = QListWidget()
        self.entity_list.setMaximumHeight(150)
        layout.addWidget(QLabel("实体列表"))
        layout.addWidget(self.entity_list)
        
        return panel
    
    def connect_signals(self):
        """连接信号"""
        # 模式切换
        self.mode_toggle.stateChanged.connect(self.on_mode_toggle)
        
        # 对话管理
        self.new_conv_btn.clicked.connect(self.create_new_conversation)
        self.delete_conv_btn.clicked.connect(self.delete_current_conversation)
        self.rename_conv_btn.clicked.connect(self.rename_current_conversation)
        self.conversation_combo.currentTextChanged.connect(self.switch_conversation)
        
        # 对话交互
        self.send_btn.clicked.connect(self.send_message)
        self.clear_btn.clicked.connect(self.clear_conversation)
        self.input_text.installEventFilter(self)  # 监听快捷键
        
        # 图谱刷新
        self.refresh_graph_btn.clicked.connect(self.refresh_graph)
        
        # 对话管理器信号
        self.conversation_manager.conversation_list_updated.connect(self.update_conversation_combo)
        self.conversation_manager.conversation_changed.connect(self.load_conversation)
    
    def eventFilter(self, obj, event):
        """事件过滤器，处理快捷键"""
        if obj == self.input_text and event.type() == event.KeyPress:
            if event.key() == Qt.Key_Return and event.modifiers() == Qt.ControlModifier:
                self.send_message()
                return True
        return super().eventFilter(obj, event)
    
    def on_mode_toggle(self, state):
        """模式切换处理"""
        self.is_test_mode = not bool(state)
        
        if self.is_test_mode:
            self.mode_label.setText("本地测试模式")
            self.update_status_display("本地测试模式已激活")
        else:
            self.mode_label.setText("酒馆插件模式")
            self.update_status_display("酒馆插件模式已激活")
        
        # 检查对应模式的连接状态
        self.check_api_connection()
    
    def update_status_display(self, status_text: str):
        """更新状态显示"""
        self.status_label.setText(status_text)
        
        if "已连接" in status_text or "已激活" in status_text:
            self.status_label.setStyleSheet("""
                QLabel {
                    padding: 5px 10px;
                    border-radius: 3px;
                    background-color: #27ae60;
                    color: white;
                    font-weight: bold;
                }
            """)
        else:
            self.status_label.setStyleSheet("""
                QLabel {
                    padding: 5px 10px;
                    border-radius: 3px;
                    background-color: #e74c3c;
                    color: white;
                    font-weight: bold;
                }
            """)
    
    def check_api_connection(self):
        """检查API连接状态"""
        try:
            response = requests.get(f"{self.api_base_url}/health", timeout=3)
            if response.status_code == 200:
                self.is_connected_to_api = True
                if self.is_test_mode:
                    self.update_status_display("API已连接")
                else:
                    self.update_status_display("酒馆已连接")
            else:
                self.is_connected_to_api = False
                self.update_status_display("API未连接")
        except:
            self.is_connected_to_api = False
            self.update_status_display("API未连接")
    
    def create_new_conversation(self):
        """创建新对话"""
        name, ok = QInputDialog.getText(
            self, 
            "新建对话",
            "请输入对话名称：",
            text=f"新对话 {len(self.conversation_manager.conversations) + 1}"
        )
        
        if ok and name.strip():
            conv_id = self.conversation_manager.create_conversation(name.strip())
            QMessageBox.information(self, "成功", "对话创建成功")
    
    def delete_current_conversation(self):
        """删除当前对话"""
        current_conv = self.conversation_manager.get_current_conversation()
        if not current_conv:
            return
        
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除对话 \"{current_conv['name']}\" 吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self.conversation_manager.delete_conversation(current_conv['id']):
                QMessageBox.information(self, "成功", "对话删除成功")
    
    def rename_current_conversation(self):
        """重命名当前对话"""
        current_conv = self.conversation_manager.get_current_conversation()
        if not current_conv:
            return
        
        name, ok = QInputDialog.getText(
            self,
            "重命名对话",
            "请输入新的对话名称：",
            text=current_conv['name']
        )
        
        if ok and name.strip():
            if self.conversation_manager.rename_conversation(current_conv['id'], name.strip()):
                QMessageBox.information(self, "成功", "对话重命名成功")
    
    def switch_conversation(self, conv_name: str):
        """切换对话"""
        # 根据名称找到对话ID
        for conv_id, conv_data in self.conversation_manager.conversations.items():
            if conv_data['name'] == conv_name:
                self.conversation_manager.switch_conversation(conv_id)
                break
    
    def update_conversation_combo(self, conversations: List[Dict]):
        """更新对话下拉框"""
        self.conversation_combo.clear()
        for conv in conversations:
            self.conversation_combo.addItem(conv['name'])
        
        # 选中当前对话
        current_conv = self.conversation_manager.get_current_conversation()
        if current_conv:
            index = self.conversation_combo.findText(current_conv['name'])
            if index >= 0:
                self.conversation_combo.setCurrentIndex(index)
    
    def load_conversation(self, conv_id: str):
        """加载对话内容"""
        self.chat_display.clear()
        
        if not conv_id:
            return
        
        conv = self.conversation_manager.get_current_conversation()
        if not conv:
            return
        
        # 显示消息历史
        for msg in conv.get('messages', []):
            if msg['role'] == 'user':
                self.append_message(f"用户: {msg['content']}", "#2c3e50")
            elif msg['role'] == 'assistant':
                self.append_message(f"助手: {msg['content']}", "#27ae60")
            elif msg['role'] == 'system':
                self.append_message(f"系统: {msg['content']}", "#8e44ad")
    
    def append_message(self, message: str, color: str = "#2c3e50"):
        """添加消息到显示区域"""
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        
        # 设置颜色
        format = cursor.charFormat()
        format.setForeground(QColor(color))
        cursor.setCharFormat(format)
        
        cursor.insertText(message + "\n\n")
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()
    
    def send_message(self):
        """发送消息"""
        message = self.input_text.toPlainText().strip()
        if not message:
            return
        
        if not self.is_connected_to_api:
            QMessageBox.warning(self, "错误", "连接失败，请检查配置")
            return
        
        # 清空输入框
        self.input_text.clear()
        
        # 显示用户消息
        self.append_message(f"用户: {message}", "#2c3e50")
        
        # 添加到对话历史
        self.conversation_manager.add_message({
            'role': 'user',
            'content': message
        })
        
        # 显示思考状态
        self.append_message("思考中...", "#7f8c8d")
        
        # 发送到API
        self.process_message(message)
    
    def process_message(self, message: str):
        """处理消息（发送到API）"""
        if self.is_test_mode:
            self.process_test_message(message)
        else:
            self.process_tavern_message(message)
    
    def process_test_message(self, message: str):
        """处理测试模式消息"""
        try:
            # 使用本地引擎处理
            response = f"测试回复: {message}的处理结果"  # 简化实现
            
            self.append_message(f"助手: {response}", "#27ae60")
            
            # 添加到对话历史
            self.conversation_manager.add_message({
                'role': 'assistant',
                'content': response
            })
            
            # 刷新图谱
            self.refresh_graph()
            
        except Exception as e:
            logger.error(f"Test message processing failed: {e}")
            self.append_message(f"错误: {str(e)}", "#e74c3c")
    
    def process_tavern_message(self, message: str):
        """处理酒馆模式消息"""
        # TODO: 实现与SillyTavern的交互
        pass
    
    def clear_conversation(self):
        """清空当前对话"""
        reply = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空当前对话吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.conversation_manager.clear_current_conversation()
            self.chat_display.clear()
    
    def refresh_graph(self):
        """刷新关系图谱"""
        logger.info("Refreshing knowledge graph...")
        self.update_entity_list()
    
    def update_entity_list(self):
        """更新实体列表"""
        self.entity_list.clear()
        # TODO: 从knowledge graph获取实体列表
        entities = ["角色1", "地点1", "物品1", "事件1"]
        for entity in entities:
            self.entity_list.addItem(entity)


class ConfigPage(QWidget):
    """系统配置页面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.env_path = Path(__file__).parent / '.env'
        self.init_ui()
        self.load_config()
    
    def init_ui(self):
        layout = QFormLayout(self)
        
        # LLM配置
        self.api_base_url_input = QLineEdit()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.model_input = QLineEdit()
        self.stream_checkbox = QCheckBox("启用流式输出")
        
        # 服务器配置
        self.api_server_port_input = QLineEdit()
        self.api_server_port_input.setValidator(QIntValidator(1024, 65535, self))
        
        # 保存按钮
        self.save_button = QPushButton("保存配置")
        self.save_button.clicked.connect(self.save_config)
        
        # 添加到布局
        layout.addRow("API接口地址:", self.api_base_url_input)
        layout.addRow("API密钥:", self.api_key_input)
        layout.addRow("默认模型:", self.model_input)
        layout.addRow("", self.stream_checkbox)
        layout.addRow("API服务器端口:", self.api_server_port_input)
        layout.addRow("", self.save_button)
    
    def load_config(self):
        """加载配置"""
        if not self.env_path.exists():
            self.env_path.touch()
        
        config = dotenv_values(self.env_path)
        self.api_base_url_input.setText(config.get("OPENAI_API_BASE_URL", ""))
        self.api_key_input.setText(config.get("OPENAI_API_KEY", ""))
        self.model_input.setText(config.get("DEFAULT_MODEL", "deepseek-v3.1"))
        
        stream_val = config.get("LLM_STREAM_OUTPUT", "false").lower()
        self.stream_checkbox.setChecked(stream_val in ('true', '1', 't'))
        
        self.api_server_port_input.setText(config.get("API_SERVER_PORT", "9543"))
    
    def save_config(self):
        """保存配置"""
        try:
            set_key(self.env_path, "OPENAI_API_BASE_URL", self.api_base_url_input.text())
            set_key(self.env_path, "OPENAI_API_KEY", self.api_key_input.text())
            set_key(self.env_path, "DEFAULT_MODEL", self.model_input.text())
            set_key(self.env_path, "LLM_STREAM_OUTPUT", str(self.stream_checkbox.isChecked()).lower())
            set_key(self.env_path, "API_SERVER_PORT", self.api_server_port_input.text())
            
            QMessageBox.information(self, "成功", "配置保存成功")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"配置保存失败：{str(e)}")


class ChronoForgeMainWindow(QMainWindow):
    """ChronoForge主窗口"""
    
    def __init__(self):
        super().__init__()
        
        # 读取配置
        self.env_path = Path(__file__).parent / '.env'
        config = dotenv_values(self.env_path) if self.env_path.exists() else {}
        self.api_server_port = int(config.get("API_SERVER_PORT", "9543"))
        
        # 初始化核心组件
        self.init_components()
        
        # 启动API服务器
        self.start_api_server()
        
        # 初始化UI
        self.init_ui()
        
        # 设置窗口属性
        self.setup_window()
    
    def init_components(self):
        """初始化核心组件"""
        logger.info("初始化ChronoForge核心组件...")
        
        try:
            # 初始化核心系统
            self.memory = GRAGMemory()
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
            
            logger.info("核心组件初始化完成")
            
        except Exception as e:
            logger.error(f"核心组件初始化失败: {e}")
            QMessageBox.critical(self, "初始化错误", f"无法初始化核心组件：\n{e}")
            sys.exit(1)
    
    def start_api_server(self):
        """启动API服务器"""
        try:
            api_server_path = str(Path(__file__).parent / "api_server.py")
            command = [sys.executable, api_server_path, "--port", str(self.api_server_port)]
            
            logger.info(f"启动API服务器: {' '.join(command)}")
            
            # Windows上创建独立进程组
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            
            self.api_server_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creation_flags
            )
            
            logger.info(f"API服务器已启动，PID: {self.api_server_process.pid}")
            
            # 等待服务器启动
            time.sleep(3)
            
        except Exception as e:
            logger.error(f"API服务器启动失败: {e}")
            QMessageBox.critical(self, "启动错误", f"无法启动API服务器：\n{e}\n请检查日志获取详细信息。")
    
    def init_ui(self):
        """初始化用户界面"""
        # 创建标签页
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # 智能对话页面（集成了对话和图谱）
        self.play_page = IntegratedPlayPage(self.game_engine)
        self.tabs.addTab(self.play_page, "智能对话")
        
        # 系统配置页面
        self.config_page = ConfigPage()
        self.tabs.addTab(self.config_page, "系统配置")
    
    def setup_window(self):
        """设置窗口属性"""
        self.setWindowTitle("ChronoForge - 智能角色扮演助手")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        # 设置应用图标
        icon_path = Path(__file__).parent / "assets" / "icons" / "chronoforge.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        # 居中显示
        self.center_window()
    
    def center_window(self):
        """窗口居中显示"""
        frame_geometry = self.frameGeometry()
        screen = QApplication.primaryScreen().availableGeometry().center()
        frame_geometry.moveCenter(screen)
        self.move(frame_geometry.topLeft())
    
    def closeEvent(self, event):
        """关闭事件处理"""
        try:
            # 终止API服务器进程
            if hasattr(self, 'api_server_process') and self.api_server_process:
                logger.info("正在关闭API服务器...")
                self.api_server_process.terminate()
                
                # 等待进程结束，最多等待5秒
                try:
                    self.api_server_process.wait(timeout=5)
                    logger.info("API服务器已正常关闭")
                except subprocess.TimeoutExpired:
                    logger.warning("API服务器未响应，强制终止...")
                    self.api_server_process.kill()
                    self.api_server_process.wait()
            
            # 保存任何需要保存的数据
            if hasattr(self, 'memory') and self.memory:
                self.memory.save_graph()
                logger.info("知识图谱已保存")
            
            event.accept()
            
        except Exception as e:
            logger.error(f"关闭程序时发生错误: {e}")
            event.accept()  # 即使出错也要关闭


def main():
    """主函数"""
    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("ChronoForge")
    app.setApplicationVersion("1.0.0")
    
    # 设置深色主题
    app.setStyleSheet("""
        QMainWindow {
            background-color: #2b2b2b;
            color: #ffffff;
        }
        QTabWidget::pane {
            border: 1px solid #555555;
            background-color: #363636;
        }
        QTabBar::tab {
            background-color: #404040;
            color: #ffffff;
            padding: 8px 15px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #4a90e2;
        }
        QTextEdit, QLineEdit, QComboBox {
            background-color: #404040;
            color: #ffffff;
            border: 1px solid #555555;
            padding: 5px;
        }
        QPushButton {
            background-color: #4a90e2;
            color: #ffffff;
            border: none;
            padding: 8px 15px;
            border-radius: 4px;
        }
        QPushButton:hover {
            background-color: #357abd;
        }
        QPushButton:pressed {
            background-color: #2e5f99;
        }
        QGroupBox {
            color: #ffffff;
            border: 1px solid #555555;
            border-radius: 5px;
            margin-top: 1ex;
            padding-top: 5px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
    """)
    
    # 创建主窗口
    try:
        window = ChronoForgeMainWindow()
        window.show()
        
        logger.info("ChronoForge应用启动完成")
        
        # 运行应用
        sys.exit(app.exec())
        
    except Exception as e:
        logger.error(f"应用启动失败: {e}")
        logger.error(traceback.format_exc())
        
        QMessageBox.critical(None, "启动错误", f"ChronoForge启动失败：\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()