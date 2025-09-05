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
    QGroupBox, QComboBox, QInputDialog, QStyle, QDialog, QFileDialog,
    QRadioButton, QButtonGroup
)
from PySide6.QtCore import Qt, QObject, Signal as pyqtSignal, QUrl, Slot
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtGui import QIcon, QFont, QColor, QIntValidator
from dotenv import dotenv_values, set_key
from loguru import logger

sys.path.append(str(Path(__file__).parent))
from src.memory import GRAGMemory
from src.core.perception import PerceptionModule
from src.core.rpg_text_processor import RPGTextProcessor
from src.core.game_engine import GameEngine
from src.core.validation import ValidationLayer

from typing import Dict, List, Optional


class GraphBridge(QObject):
    """JavaScript和Python之间的桥接类"""
    
    def __init__(self, graph_page):
        super().__init__()
        self.graph_page = graph_page
    
    @Slot(str, str)
    def editNode(self, entity_name, entity_type):
        """JavaScript直接调用此方法编辑节点"""
        try:
            logger.info(f"通过WebChannel编辑节点: {entity_name} ({entity_type})")
            self.graph_page.edit_node_with_python_dialog(entity_name, entity_type)
        except Exception as e:
            logger.error(f"WebChannel编辑节点失败: {e}")
    
    @Slot(str, str, str)
    def createRelation(self, source_name, target_name, relation_type):
        """JavaScript直接调用此方法创建关系"""
        try:
            logger.info(f"通过WebChannel创建关系: {source_name} -> {target_name} ({relation_type})")
            # 可以在这里添加创建关系的逻辑
        except Exception as e:
            logger.error(f"WebChannel创建关系失败: {e}")
    
    @Slot(str)
    def log(self, message):
        """JavaScript日志输出到Python"""
        logger.debug(f"JS: {message}")


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
        
        # 设置初始状态 - 本地测试模式默认激活
        self.update_status_display("本地测试模式已选择")
        self.is_connected_to_api = True
        # 设置初始按钮状态
        self.local_mode_radio.setEnabled(False)  # 当前选中的模式变灰
        self.tavern_mode_radio.setEnabled(True)
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        
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
    
    def create_toolbar(self) -> QWidget:
        """创建顶部工具栏"""
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        
        # 模式选择组
        mode_group = QGroupBox("测试模式")
        mode_layout = QVBoxLayout(mode_group)
        
        # 单选按钮组
        self.mode_button_group = QButtonGroup()
        
        self.local_mode_radio = QRadioButton("本地测试模式")
        self.tavern_mode_radio = QRadioButton("酒馆模式") 
        
        # 默认选择本地测试模式
        self.local_mode_radio.setChecked(True)
        self.is_test_mode = True
        
        # 添加到按钮组
        self.mode_button_group.addButton(self.local_mode_radio, 0)
        self.mode_button_group.addButton(self.tavern_mode_radio, 1)
        
        mode_layout.addWidget(self.local_mode_radio)
        mode_layout.addWidget(self.tavern_mode_radio)
        
        # 连接状态指示器
        self.status_label = QLabel("本地测试模式已选择")
        self.status_label.setStyleSheet("""
            QLabel {
                padding: 5px 10px;
                border-radius: 3px;
                background-color: #27ae60;
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
    
    def connect_signals(self):
        """连接信号"""
        # 模式切换 - 使用单选按钮组
        self.mode_button_group.idClicked.connect(self.on_mode_change)
        
        # 对话管理
        self.new_conv_btn.clicked.connect(self.create_new_conversation)
        self.delete_conv_btn.clicked.connect(self.delete_current_conversation)
        self.rename_conv_btn.clicked.connect(self.rename_current_conversation)
        self.conversation_combo.currentTextChanged.connect(self.switch_conversation)
        
        # 对话交互
        self.send_btn.clicked.connect(self.send_message)
        self.clear_btn.clicked.connect(self.clear_conversation)
        self.input_text.installEventFilter(self)  # 监听快捷键
        
        # 对话管理器信号
        self.conversation_manager.conversation_list_updated.connect(self.update_conversation_combo)
        self.conversation_manager.conversation_changed.connect(self.load_conversation)
    
    def eventFilter(self, obj, event):
        """事件过滤器，处理快捷键"""
        if obj == self.input_text and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key_Return and event.modifiers() == Qt.ControlModifier:
                self.send_message()
                return True
        return super().eventFilter(obj, event)
    
    def on_mode_change(self, mode_id):
        """模式切换处理"""
        if mode_id == 0:  # 本地测试模式
            self.is_test_mode = True
            self.tavern_mode_radio.setEnabled(True)  # 酒馆模式可选
            self.local_mode_radio.setEnabled(False)  # 本地模式变灰
            
            self.update_status_display("本地测试模式已选择")
            self.is_connected_to_api = True
            
        elif mode_id == 1:  # 酒馆模式
            self.is_test_mode = False  
            self.local_mode_radio.setEnabled(True)  # 本地模式可选
            self.tavern_mode_radio.setEnabled(False)  # 酒馆模式变灰
            
            # 开始检查酒馆连接
            self.update_status_display("等待酒馆连接...")
            # 使用定时器异步检查连接，避免界面卡顿
            QApplication.processEvents()
            self.check_api_connection()
    
    def check_api_connection(self):
        """检查API连接状态"""
        if self.is_test_mode:
            # 本地测试模式不需要检查API
            self.is_connected_to_api = True
            self.update_status_display("本地测试模式已选择")
            return
        
        # 只有酒馆模式才检查API连接
        try:
            # 显示正在连接状态
            self.update_status_display("正在连接酒馆...")
            QApplication.processEvents()
            
            response = requests.get(f"{self.api_base_url}/health", timeout=5)
            if response.status_code == 200:
                self.is_connected_to_api = True
                self.update_status_display("酒馆API已连接")
            else:
                self.is_connected_to_api = False
                self.update_status_display("酒馆API连接失败")
        except Exception as e:
            self.is_connected_to_api = False
            self.update_status_display("酒馆API未连接")
            logger.warning(f"酒馆API连接失败: {e}")
    
    def update_status_display(self, status_text: str):
        """更新状态显示"""
        self.status_label.setText(status_text)
        
        # 根据状态文本设置不同的样式
        if ("已连接" in status_text or "已选择" in status_text):
            # 成功状态 - 绿色
            self.status_label.setStyleSheet("""
                QLabel {
                    padding: 5px 10px;
                    border-radius: 3px;
                    background-color: #27ae60;
                    color: white;
                    font-weight: bold;
                }
            """)
        elif ("正在连接" in status_text or "等待" in status_text):
            # 等待状态 - 蓝色
            self.status_label.setStyleSheet("""
                QLabel {
                    padding: 5px 10px;
                    border-radius: 3px;
                    background-color: #3498db;
                    color: white;
                    font-weight: bold;
                }
            """)
        else:
            # 错误/失败状态 - 红色
            self.status_label.setStyleSheet("""
                QLabel {
                    padding: 5px 10px;
                    border-radius: 3px;
                    background-color: #e74c3c;
                    color: white;
                    font-weight: bold;
                }
            """)
    
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


class GraphPage(QWidget):
    """知识关系图谱页面"""
    
    def __init__(self, memory_system, parent=None):
        super().__init__(parent)
        self.memory = memory_system
        self.graph_file_path = Path(__file__).parent / "graph.html"
        self.current_selected_node = None
        
        # 创建WebChannel桥接
        self.bridge = GraphBridge(self)
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        
        self.init_ui()
        self.connect_signals()
        self.refresh_graph()
    
    def init_ui(self):
        """初始化UI"""
        layout = QHBoxLayout(self)
        layout.setSpacing(10)
        
        # 左侧：图谱显示区域
        left_panel = self.create_graph_panel()
        
        # 右侧：控制和信息面板
        right_panel = self.create_control_panel()
        
        # 使用分割器
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)  # 图谱区域占3/4
        splitter.setStretchFactor(1, 1)  # 控制区域占1/4
        
        layout.addWidget(splitter)
    
    def create_graph_panel(self) -> QWidget:
        """创建图谱显示面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 标题和快速操作
        header = QHBoxLayout()
        title = QLabel("知识关系图谱")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet("color: #4a90e2; margin-bottom: 10px;")
        
        # 快速操作按钮
        self.refresh_btn = QPushButton("刷新图谱")
        self.refresh_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        
        self.export_btn = QPushButton("导出图谱")
        self.export_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        
        self.reset_view_btn = QPushButton("重置视图")
        self.reset_view_btn.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.refresh_btn)
        header.addWidget(self.export_btn)
        header.addWidget(self.reset_view_btn)
        
        layout.addLayout(header)
        
        # 图谱显示区域
        self.graph_view = QWebEngineView()
        self.graph_view.setMinimumHeight(500)
        
        # 设置WebChannel
        self.graph_view.page().setWebChannel(self.channel)
        
        # 启用开发者工具 - 方便调试JavaScript
        try:
            from PySide6.QtWebEngineCore import QWebEngineSettings
            settings = self.graph_view.settings()
            # 尝试不同的属性名
            dev_attr = None
            for attr_name in ['DeveloperExtrasEnabled', 'WebAttribute.DeveloperExtrasEnabled', 'JavascriptEnabled']:
                if hasattr(QWebEngineSettings, attr_name):
                    dev_attr = getattr(QWebEngineSettings, attr_name)
                    break
                elif hasattr(QWebEngineSettings, 'WebAttribute') and hasattr(QWebEngineSettings.WebAttribute, 'DeveloperExtrasEnabled'):
                    dev_attr = QWebEngineSettings.WebAttribute.DeveloperExtrasEnabled
                    break
            
            if dev_attr is not None:
                settings.setAttribute(dev_attr, True)
                logger.info("开发者工具已启用")
            else:
                # 尝试直接设置常见的开发者工具属性
                try:
                    settings.setAttribute(settings.DeveloperExtrasEnabled, True)
                    logger.info("开发者工具已启用(直接属性)")
                except:
                    logger.warning("无法启用开发者工具，但程序继续运行")
        except Exception as e:
            logger.warning(f"启用开发者工具失败: {e}")
            # 即使失败也继续运行
        
        # 添加右键菜单来打开开发者工具
        from PySide6.QtWidgets import QMenu
        from PySide6.QtCore import Qt
        
        def show_context_menu(point):
            menu = QMenu(self.graph_view)
            
            # 添加开发者工具选项
            dev_action = menu.addAction("打开开发者工具 (F12)")
            dev_action.triggered.connect(self.open_dev_tools)
            
            # 添加其他调试选项
            reload_action = menu.addAction("重新加载图谱")
            reload_action.triggered.connect(self.refresh_graph)
            
            debug_action = menu.addAction("调试信息")
            debug_action.triggered.connect(self.show_debug_info)
            
            menu.exec(self.graph_view.mapToGlobal(point))
        
        self.graph_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.graph_view.customContextMenuRequested.connect(show_context_menu)
        
        layout.addWidget(self.graph_view)
        
        return panel
    
    def create_control_panel(self) -> QWidget:
        """创建控制面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 搜索区域
        search_group = QGroupBox("搜索与过滤")
        search_layout = QVBoxLayout(search_group)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索节点或关系...")
        self.search_btn = QPushButton("搜索")
        self.clear_search_btn = QPushButton("清除")
        
        search_button_layout = QHBoxLayout()
        search_button_layout.addWidget(self.search_btn)
        search_button_layout.addWidget(self.clear_search_btn)
        
        search_layout.addWidget(self.search_input)
        search_layout.addLayout(search_button_layout)
        
        layout.addWidget(search_group)
        
        # 实体列表
        entity_group = QGroupBox("实体列表")
        entity_layout = QVBoxLayout(entity_group)
        
        # 实体类型过滤
        filter_layout = QHBoxLayout()
        self.filter_all_btn = QPushButton("全部")
        self.filter_character_btn = QPushButton("角色")
        self.filter_location_btn = QPushButton("地点")
        self.filter_item_btn = QPushButton("物品")
        self.filter_event_btn = QPushButton("事件")
        
        # 设置过滤按钮样式
        filter_buttons = [self.filter_all_btn, self.filter_character_btn, 
                         self.filter_location_btn, self.filter_item_btn, self.filter_event_btn]
        
        for btn in filter_buttons:
            btn.setCheckable(True)
            btn.setMaximumHeight(30)
            filter_layout.addWidget(btn)
        
        self.filter_all_btn.setChecked(True)  # 默认选中全部
        
        entity_layout.addLayout(filter_layout)
        
        # 实体列表
        self.entity_list = QListWidget()
        self.entity_list.setMinimumHeight(200)
        entity_layout.addWidget(self.entity_list)
        
        layout.addWidget(entity_group)
        
        # 节点详情
        detail_group = QGroupBox("节点详情")
        detail_layout = QVBoxLayout(detail_group)
        
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(150)
        self.detail_text.setPlaceholderText("选择一个节点查看详细信息...")
        
        detail_layout.addWidget(self.detail_text)
        
        # 节点操作按钮
        node_actions = QHBoxLayout()
        self.add_node_btn = QPushButton("添加节点")
        self.edit_node_btn = QPushButton("编辑节点")
        self.delete_node_btn = QPushButton("删除节点")
        
        self.add_node_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        self.edit_node_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.delete_node_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        
        node_actions.addWidget(self.add_node_btn)
        node_actions.addWidget(self.edit_node_btn)
        node_actions.addWidget(self.delete_node_btn)
        
        detail_layout.addLayout(node_actions)
        layout.addWidget(detail_group)
        
        # 图谱统计
        stats_group = QGroupBox("图谱统计")
        stats_layout = QVBoxLayout(stats_group)
        
        self.stats_label = QLabel("节点数量: 0\n关系数量: 0\n最后更新: 未知")
        self.stats_label.setStyleSheet("color: #cccccc; font-size: 12px;")
        
        stats_layout.addWidget(self.stats_label)
        layout.addWidget(stats_group)
        
        layout.addStretch()
        
        return panel
    
    def connect_signals(self):
        """连接信号"""
        # 图谱操作
        self.refresh_btn.clicked.connect(self.refresh_graph)
        self.export_btn.clicked.connect(self.export_graph)
        self.reset_view_btn.clicked.connect(self.reset_view)
        
        # 搜索功能
        self.search_btn.clicked.connect(self.search_nodes)
        self.clear_search_btn.clicked.connect(self.clear_search)
        self.search_input.returnPressed.connect(self.search_nodes)
        
        # 实体过滤
        filter_buttons = [self.filter_all_btn, self.filter_character_btn, 
                         self.filter_location_btn, self.filter_item_btn, self.filter_event_btn]
        
        for btn in filter_buttons:
            btn.clicked.connect(self.filter_entities)
        
        # 实体列表
        self.entity_list.itemClicked.connect(self.on_entity_selected)
        self.entity_list.itemDoubleClicked.connect(self.focus_on_node)
        
        # 节点操作
        self.add_node_btn.clicked.connect(self.add_node)
        self.edit_node_btn.clicked.connect(self.edit_node)
        self.delete_node_btn.clicked.connect(self.delete_node)
    
    def refresh_graph(self):
        """刷新关系图谱"""
        logger.info("刷新知识关系图谱...")
        
        try:
            # TODO: 实现真实的图谱刷新逻辑
            # 这里先添加一些示例数据
            self.update_entity_list()
            self.update_stats()
            
            # 生成图谱HTML（简化实现）
            self.generate_graph_html()
            
            # 加载到WebView
            if self.graph_file_path.exists():
                self.graph_view.load(QUrl.fromLocalFile(str(self.graph_file_path)))
            
        except Exception as e:
            logger.error(f"刷新图谱失败: {e}")
            QMessageBox.warning(self, "错误", f"刷新图谱失败：{str(e)}")
    
    def generate_graph_html(self):
        """生成图谱HTML文件"""
        try:
            entities = self.get_all_entities()
            
            # 构建节点和边的数据
            nodes = []
            links = []
            
            for i, entity in enumerate(entities):
                nodes.append({
                    'id': entity['name'],
                    'name': entity['name'],
                    'type': entity['type'],
                    'description': entity.get('description', ''),
                    'group': self._get_type_group(entity['type'])
                })
            
            # 创建合理的关系连接
            relationships = [
                # 直接的角色-物品关系
                {"source": "主角", "target": "魔法剑", "relation": "拥有"},
                
                # 角色-事件关系（事件作为中介）
                {"source": "主角", "target": "初次相遇", "relation": "参与"},
                {"source": "智者", "target": "初次相遇", "relation": "参与"},
                {"source": "初次相遇", "target": "神秘村庄", "relation": "发生于"},
                
                # 角色-地点的长期关系
                {"source": "智者", "target": "古老神殿", "relation": "守护"},
                {"source": "主角", "target": "神秘村庄", "relation": "到达"}
            ]
            
            # 将预定义关系添加到links数组
            entity_names = {entity['name'] for entity in entities}
            for rel in relationships:
                if rel["source"] in entity_names and rel["target"] in entity_names:
                    links.append(rel)
            
            # 将数据转换为JSON字符串
            nodes_json = json.dumps(nodes, ensure_ascii=False)
            links_json = json.dumps(links, ensure_ascii=False)
            
            # 生成HTML内容
            html_content = self._create_html_template(nodes_json, links_json)
            
            with open(self.graph_file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
                
        except Exception as e:
            logger.error(f"生成图谱HTML失败: {e}")
            logger.error(f"错误详情: {traceback.format_exc()}")
            # 如果失败，使用简化版本
            self._generate_fallback_html()
    
    def _create_html_template(self, nodes_json, links_json):
        """创建HTML模板"""
        return f"""<!DOCTYPE html>
<html>
<head>
    <title>ChronoForge Knowledge Graph</title>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
        body {{
            background-color: #2d2d2d;
            color: white;
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
        }}
        
        .loading {{
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            flex-direction: column;
        }}
        
        .spinner {{
            border: 4px solid #3c3c3c;
            border-top: 4px solid #4a90e2;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin-bottom: 20px;
        }}
        
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
        
        .graph-container {{
            width: 100%;
            height: 100vh;
            overflow: hidden;
            display: none;
        }}
        
        /* 确保SVG不产生滚动条 */
        #graph {{
            display: block;
            overflow: hidden;
        }}
        
        .node {{
            stroke: #fff;
            stroke-width: 2px;
            cursor: pointer;
        }}
        
        .node.character {{ fill: #4a90e2; }}
        .node.location {{ fill: #27ae60; }}
        .node.item {{ fill: #f39c12; }}
        .node.event {{ fill: #e74c3c; }}
        .node.concept {{ fill: #9b59b6; }}
        
        .link {{
            stroke: #999;
            stroke-opacity: 0.6;
            stroke-width: 2px;
        }}
        
        .node-label {{
            font-size: 12px;
            fill: white;
            text-anchor: middle;
            pointer-events: none;
            font-weight: bold;
        }}
        
        /* 关系编辑模式样式 */
        .editing-mode {{
            cursor: crosshair !important;
        }}
        
        .temp-line {{
            stroke: #ff6b6b;
            stroke-width: 3px;
            stroke-dasharray: 5,5;
            opacity: 0.7;
        }}
        
        .selected-node {{
            stroke: #ff6b6b !important;
            stroke-width: 4px !important;
            filter: brightness(1.2);
        }}
        
        .editable-link {{
            cursor: pointer;
        }}
        
        .editable-link:hover {{
            stroke-width: 4px !important;
            stroke: #ff6b6b !important;
        }}
        
        .relation-label {{
            font-size: 10px;
            fill: #ccc;
            text-anchor: middle;
            pointer-events: none;
            opacity: 0.8;
        }}
        
        .tooltip {{
            position: absolute;
            background-color: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 10px;
            border-radius: 5px;
            font-size: 14px;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.3s;
            max-width: 200px;
            z-index: 1000;
        }}
        
        .controls {{
            position: absolute;
            top: 10px;
            left: 10px;
            background-color: rgba(0, 0, 0, 0.7);
            padding: 10px;
            border-radius: 5px;
            z-index: 100;
            display: none;
        }}
        
        .controls button {{
            background-color: #4a90e2;
            color: white;
            border: none;
            padding: 5px 10px;
            margin: 2px;
            border-radius: 3px;
            cursor: pointer;
        }}
        
        .controls button:hover {{
            background-color: #357abd;
        }}
        
        .fallback {{
            display: none;
            justify-content: center;
            align-items: center;
            height: 100vh;
            flex-direction: column;
        }}
        
        .entity-card {{
            background: #3c3c3c;
            border: 2px solid #5a5a5a;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
            transition: transform 0.2s;
            margin: 10px;
            min-width: 180px;
        }}
        
        .entity-card:hover {{
            transform: translateY(-2px);
            border-color: #4a90e2;
        }}
        
        .entity-type {{
            font-size: 12px;
            opacity: 0.7;
            margin-bottom: 5px;
        }}
        
        .entity-name {{
            font-size: 16px;
            font-weight: bold;
            margin-bottom: 8px;
        }}
        
        .entity-desc {{
            font-size: 13px;
            opacity: 0.8;
            line-height: 1.3;
        }}
        
        .entity-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            max-width: 1000px;
            margin: 30px 0;
        }}
    </style>
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
            <small>已尝试从CDN和本地文件加载D3.js</small><br>
            <small>本地文件路径: ./assets/js/d3.v7.min.js</small>
        </p>
        <button onclick="location.reload()" style="
            background: #4a90e2; color: white; border: none; 
            padding: 10px 20px; border-radius: 5px; cursor: pointer; margin-top: 15px;
        ">重新加载</button>
    </div>
    
    <script>
        const nodes = {nodes_json};
        const links = {links_json};
        
        // WebChannel桥接对象
        var bridge = null;
        
        // 初始化WebChannel
        function initWebChannel() {{
            console.log('初始化WebChannel...');
            if (typeof QWebChannel !== 'undefined') {{
                new QWebChannel(qt.webChannelTransport, function (channel) {{
                    bridge = channel.objects.bridge;
                    console.log('✅ WebChannel初始化成功');
                    console.log('Bridge对象:', bridge);
                    
                    // 测试连接
                    if (bridge && bridge.log) {{
                        bridge.log('WebChannel连接测试成功');
                    }}
                }});
            }} else {{
                console.error('❌ QWebChannel不可用');
            }}
        }}
        
        console.log('页面加载开始');
        console.log('节点数据:', nodes);
        console.log('连接数据:', links);
        
        // CDN列表 - 如果网络受限，可以考虑下载到本地
        const cdnUrls = [
            'https://d3js.org/d3.v7.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js',
            'https://unpkg.com/d3@7/dist/d3.min.js',
            'https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js'
        ];
        
        // 检查是否有本地D3.js文件
        const localD3Path = './assets/js/d3.v7.min.js';
        
        let currentCdnIndex = 0;
        let loadStartTime = Date.now();
        
        // 添加一个函数来检查CDN内容
        function checkCdnContent(url) {{
            console.log(`🔍 检查CDN内容: ${{url}}`);
            
            fetch(url, {{
                method: 'GET',
                mode: 'cors',
                cache: 'no-cache'
            }})
            .then(response => {{
                console.log(`📡 CDN响应状态: ${{response.status}} ${{response.statusText}}`);
                console.log(`📡 Content-Type: ${{response.headers.get('content-type')}}`);
                console.log(`📡 Content-Length: ${{response.headers.get('content-length')}}`);
                
                return response.text();
            }})
            .then(content => {{
                console.log(`📄 CDN内容长度: ${{content.length}} 字符`);
                console.log(`📄 前100字符:`, content.substring(0, 100));
                
                // 检查是否是HTML内容
                if (content.toLowerCase().includes('<html') || content.toLowerCase().includes('<!doctype')) {{
                    console.error(`❌ CDN返回HTML而非JavaScript: ${{url}}`);
                    console.log('完整HTML内容:', content);
                }} else if (content.includes('d3') && content.includes('function')) {{
                    console.log(`✅ CDN内容看起来是有效的JavaScript: ${{url}}`);
                }} else {{
                    console.warn(`⚠️  CDN内容类型未知: ${{url}}`);
                    console.log('内容预览:', content.substring(0, 500));
                }}
            }})
            .catch(error => {{
                console.error(`❌ 无法获取CDN内容: ${{url}}`, error);
                console.error('Fetch错误类型:', error.name);
                console.error('Fetch错误信息:', error.message);
            }});
        }}

        // 尝试加载本地D3.js文件
        function tryLoadLocalD3() {{
            console.log('🏠 尝试加载本地D3.js文件:', localD3Path);
            
            const script = document.createElement('script');
            script.src = localD3Path;
            script.timeout = 5000;
            
            const loadTimer = setTimeout(() => {{
                console.warn('本地D3.js加载超时');
                script.onerror();
            }}, 5000);
            
            script.onload = function() {{
                clearTimeout(loadTimer);
                console.log('✅ 本地D3.js加载成功！');
                console.log('D3版本:', typeof d3 !== 'undefined' ? d3.version : 'undefined');
                
                if (typeof d3 === 'undefined') {{
                    console.error('本地脚本加载了但是d3对象未定义');
                    showFallback();
                    return;
                }}
                
                hideLoading();
                try {{
                    initializeGraph();
                }} catch (error) {{
                    console.error('初始化图谱失败:', error);
                    showFallback();
                }}
            }};
            
            script.onerror = function() {{
                clearTimeout(loadTimer);
                console.error('❌ 本地D3.js文件不存在或加载失败');
                console.log('💡 建议: 下载D3.js到', localD3Path);
                
                // 如果本地文件也失败，显示简化版本
                console.log('🎨 显示简化版本图谱...');
                showFallback();
            }};
            
            document.head.appendChild(script);
        }}
        
        function loadD3Script() {{
            // 由于网络受限，直接尝试本地文件
            console.log('⚠️  检测到网络访问受限，CDN无法访问');
            console.log('🔄 跳过CDN，直接尝试本地D3.js文件');
            
            tryLoadLocalD3();
            return;
            
            /* 原CDN加载代码（网络受限时不执行）
            if (currentCdnIndex >= cdnUrls.length) {{
                console.error('所有CDN都失败了，尝试本地文件');
                tryLoadLocalD3();
                return;
            }}
            
            const currentUrl = cdnUrls[currentCdnIndex];
            console.log(`尝试加载CDN ${{currentCdnIndex + 1}}/${{cdnUrls.length}}: ${{currentUrl}}`);
            
            // 首先检查CDN内容
            checkCdnContent(currentUrl);
            
            const script = document.createElement('script');
            script.src = currentUrl;
            script.timeout = 10000; // 10秒超时
            
            const loadTimer = setTimeout(() => {{
                console.warn(`CDN ${{currentUrl}} 加载超时`);
                script.onerror();
            }}, 10000);
            
            script.onload = function() {{
                clearTimeout(loadTimer);
                const loadTime = Date.now() - loadStartTime;
                console.log(`✅ D3.js加载成功！来源: ${{currentUrl}}, 耗时: ${{loadTime}}ms`);
                console.log('D3版本:', typeof d3 !== 'undefined' ? d3.version : 'undefined');
                
                if (typeof d3 === 'undefined') {{
                    console.error('脚本加载了但是d3对象未定义');
                    console.log('🔍 检查window对象中的d3:', window.d3);
                    console.log('🔍 检查全局变量:', Object.keys(window).filter(key => key.includes('d3')));
                    script.onerror();
                    return;
                }}
                
                hideLoading();
                try {{
                    initializeGraph();
                }} catch (error) {{
                    console.error('初始化图谱失败:', error);
                    console.error('错误堆栈:', error.stack);
                    showFallback();
                }}
            }};
            
            script.onerror = function(error) {{
                clearTimeout(loadTimer);
                console.error(`❌ CDN失败: ${{currentUrl}}`);
                console.error('错误详情:', error);
                console.error('错误事件:', event);
                console.error('错误类型:', event ? event.type : 'unknown');
                console.error('脚本标签:', script);
                console.error('脚本src:', script.src);
                console.error('脚本readyState:', script.readyState);
                
                // 再次检查CDN内容以进行对比
                console.log('🔄 脚本失败后重新检查CDN内容...');
                checkCdnContent(currentUrl);
                
                currentCdnIndex++;
                setTimeout(() => {{
                    console.log(`等待1秒后尝试下一个CDN...`);
                    loadD3Script();
                }}, 1000);
            }};
            
            console.log('添加script标签到head');
            document.head.appendChild(script);
            */
        }}
        
        function hideLoading() {{
            console.log('隐藏加载动画，显示图谱');
            document.getElementById('loading').style.display = 'none';
            document.getElementById('graphContainer').style.display = 'block';
            document.getElementById('controls').style.display = 'block';
        }}
        
        function showFallback() {{
            console.log('显示简化版本');
            document.getElementById('loading').style.display = 'none';
            document.getElementById('fallback').style.display = 'flex';
            
            // 生成实体卡片
            generateEntityCards();
        }}
        
        function generateEntityCards() {{
            const entityGrid = document.getElementById('entityGrid');
            const typeColors = {{
                'character': '#4a90e2',
                'location': '#27ae60', 
                'item': '#f39c12',
                'event': '#e74c3c',
                'concept': '#9b59b6'
            }};
            
            let cardsHtml = '';
            nodes.forEach(node => {{
                const color = typeColors[node.type] || '#9b59b6';
                cardsHtml += `
                    <div class="entity-card" style="border-color: ${{color}};">
                        <div class="entity-type" style="color: ${{color}};">[${{node.type}}]</div>
                        <div class="entity-name">${{node.name}}</div>
                        <div class="entity-desc">${{node.description || '暂无描述'}}</div>
                    </div>
                `;
            }});
            
            entityGrid.innerHTML = cardsHtml;
            console.log('实体卡片生成完成');
        }}
        
        function initializeGraph() {{
            console.log('开始初始化图谱');
            
            try {{
                const svg = d3.select("#graph");
                console.log('SVG元素选择成功');
                
                const width = window.innerWidth;
                const height = window.innerHeight;
                console.log(`画布尺寸: ${{width}}x${{height}}`);
                
                svg.attr("width", width).attr("height", height);
                
                const g = svg.append("g");
                console.log('创建SVG组元素');
                
                // 缩放行为
                const zoom = d3.zoom()
                    .scaleExtent([0.1, 4])
                    .on("zoom", (event) => {{
                        g.attr("transform", event.transform);
                    }});
                
                svg.call(zoom);
                console.log('缩放行为设置完成');
                
                // 力导向布局
                let simulation = d3.forceSimulation(nodes)
                    .force("link", d3.forceLink(links).id(d => d.id).distance(100))
                    .force("charge", d3.forceManyBody().strength(-300))
                    .force("center", d3.forceCenter(width / 2, height / 2));
                
                console.log('力导向布局创建完成');
                
                // 创建连线
                const link = g.append("g")
                    .selectAll("line")
                    .data(links)
                    .join("line")
                    .attr("class", "link editable-link");
                
                console.log(`创建了 ${{links.length}} 条连线`);
                
                // 添加关系标签
                const linkLabel = g.append("g")
                    .selectAll("text")
                    .data(links)
                    .join("text")
                    .attr("class", "relation-label")
                    .text(d => d.relation || "关联")
                    .style("cursor", "pointer"); // 让标签可点击
                
                // 关系连线点击编辑（任何时候都可以点击连线编辑）
                link.on("click", function(event, d) {{
                    event.stopPropagation();
                    openRelationEditDialog(d);
                }});
                
                // 关系标签点击编辑（任何时候都可以点击标签编辑）
                linkLabel.on("click", function(event, d) {{
                    event.stopPropagation();
                    openRelationEditDialog(d);
                }});
                
                // 创建节点
                const node = g.append("g")
                    .selectAll("circle")
                    .data(nodes)
                    .join("circle")
                    .attr("class", d => `node ${{d.type}}`)
                    .attr("r", 20)
                    .call(d3.drag()
                        .on("start", dragstarted)
                        .on("drag", dragged)
                        .on("end", dragended));
                
                console.log(`创建了 ${{nodes.length}} 个节点`);
                
                // 节点标签
                const label = g.append("g")
                    .selectAll("text")
                    .data(nodes)
                    .join("text")
                    .attr("class", "node-label")
                    .attr("dy", ".35em")
                    .text(d => d.name);
                
                console.log('节点标签创建完成');
                
                // 工具提示
                const tooltip = d3.select("#tooltip");
                
                node.on("mouseover", (event, d) => {{
                    tooltip.style("opacity", 1)
                        .html(`<strong>${{d.name}}</strong><br/>
                               类型: ${{d.type}}<br/>
                               描述: ${{d.description || '暂无描述'}}`)
                        .style("left", (event.pageX + 10) + "px")
                        .style("top", (event.pageY - 10) + "px");
                }})
                .on("mouseout", () => {{
                    tooltip.style("opacity", 0);
                }});
                
                console.log('工具提示事件绑定完成');
                
                // 更新位置
                simulation.on("tick", () => {{
                    link.attr("x1", d => d.source.x)
                        .attr("y1", d => d.source.y)
                        .attr("x2", d => d.target.x)
                        .attr("y2", d => d.target.y);
                    
                    // 更新关系标签位置（在连线中点）
                    linkLabel.attr("x", d => (d.source.x + d.target.x) / 2)
                             .attr("y", d => (d.source.y + d.target.y) / 2 - 5);
                    
                    node.attr("cx", d => d.x)
                        .attr("cy", d => d.y);
                    
                    label.attr("x", d => d.x)
                         .attr("y", d => d.y);
                }});
                
                // 拖拽函数（支持物理效果开关）
                function dragstarted(event, d) {{
                    if (physicsEnabled) {{
                        if (!event.active) simulation.alphaTarget(0.3).restart();
                    }}
                    d.fx = d.x;
                    d.fy = d.y;
                }}
                
                function dragged(event, d) {{
                    d.fx = event.x;
                    d.fy = event.y;
                    
                    // 如果物理效果关闭，手动更新节点和标签位置
                    if (!physicsEnabled) {{
                        d.x = event.x;
                        d.y = event.y;
                        
                        // 手动更新节点位置
                        node.filter(n => n.id === d.id)
                            .attr("cx", d.x)
                            .attr("cy", d.y);
                        
                        // 手动更新标签位置    
                        label.filter(n => n.id === d.id)
                            .attr("x", d.x)
                            .attr("y", d.y);
                        
                        // 手动更新连接的边
                        link.filter(l => l.source.id === d.id || l.target.id === d.id)
                            .attr("x1", l => l.source.x)
                            .attr("y1", l => l.source.y)
                            .attr("x2", l => l.target.x)
                            .attr("y2", l => l.target.y);
                            
                        // 手动更新关系标签位置
                        linkLabel.filter(l => l.source.id === d.id || l.target.id === d.id)
                            .attr("x", l => (l.source.x + l.target.x) / 2)
                            .attr("y", l => (l.source.y + l.target.y) / 2 - 5);
                    }}
                }}
                
                function dragended(event, d) {{
                    if (physicsEnabled) {{
                        // 物理效果开启：释放固定，让节点继续受力影响
                        if (!event.active) simulation.alphaTarget(0);
                        d.fx = null;
                        d.fy = null;
                    }} else {{
                        // 物理效果关闭：保持当前位置固定，不再移动
                        d.fx = event.x;
                        d.fy = event.y;
                        console.log(`节点 ${{d.name}} 固定在位置: (${{event.x}}, ${{event.y}})`);
                    }}
                }}
                
                // 关系编辑功能
                let editMode = false;
                let selectedNode = null;
                let tempLine = null;
                
                // 编辑模式切换
                window.toggleEditMode = function() {{
                    console.log('=== toggleEditMode 函数被调用 ===');
                    console.log('当前 editMode 值:', editMode);
                    console.log('即将切换为:', !editMode);
                    
                    editMode = !editMode;
                    console.log('新的 editMode 值:', editMode);
                    
                    const btn = document.getElementById('editModeBtn');
                    console.log('找到按钮元素:', btn);
                    
                    if (!btn) {{
                        console.error('❌ 找不到编辑按钮元素！');
                        return;
                    }}
                    
                    if (editMode) {{
                        console.log('✅ 进入关系编辑模式');
                        btn.textContent = '退出编辑';
                        btn.style.backgroundColor = '#e74c3c';
                        svg.classed('editing-mode', true);
                        console.log('按钮文本已更改为: 退出编辑');
                        console.log('按钮背景色已更改为: 红色');
                        console.log('SVG已添加editing-mode类');
                        
                        // 检查SVG和节点是否存在
                        console.log('SVG元素:', svg.node());
                        console.log('节点数量:', node ? node.size() : '节点未定义');
                        console.log('selectedNode:', selectedNode);
                        
                    }} else {{
                        console.log('✅ 退出关系编辑模式');
                        btn.textContent = '编辑关系';
                        btn.style.backgroundColor = '#4a90e2';
                        svg.classed('editing-mode', false);
                        clearSelection();
                        console.log('按钮文本已更改为: 编辑关系');
                        console.log('按钮背景色已更改为: 蓝色');
                        console.log('SVG已移除editing-mode类');
                        console.log('选择状态已清除');
                    }}
                    
                    console.log('=== toggleEditMode 函数执行完成 ===');
                }}
                
                // 清除选择状态
                function clearSelection() {{
                    if (selectedNode) {{
                        selectedNode.classed('selected-node', false);
                        selectedNode = null;
                    }}
                    if (tempLine) {{
                        tempLine.remove();
                        tempLine = null;
                    }}
                }}
                
                // 节点点击事件
                node.on("click", function(event, d) {{
                    event.stopPropagation();
                    
                    console.log('节点被点击:', d.name, '编辑模式:', editMode, '已选中节点:', selectedNode ? selectedNode.datum().name : 'none');
                    
                    if (editMode) {{
                        // 编辑模式：既可以编辑节点，也可以创建关系
                        // 如果没有选中节点，直接调用Python编辑方法
                        // 如果已有选中节点，则创建关系
                        if (!selectedNode) {{
                            console.log('通过WebChannel编辑节点:', d.name, '类型:', d.type);
                            // 直接调用Python方法
                            if (typeof bridge !== 'undefined' && bridge.editNode) {{
                                bridge.editNode(d.name, d.type);
                            }} else {{
                                console.warn('WebChannel bridge不可用');
                            }}
                        }} else {{
                            console.log('进入关系编辑模式');
                            handleRelationEdit(d, d3.select(this));
                        }}
                    }} else {{
                        console.log('普通模式，不执行任何操作');
                    }}
                    // 默认状态：点击节点不做任何操作，只有通过右侧面板的编辑按钮才能编辑节点
                }});
                
                // 移除双击事件，避免意外触发编辑
                
                // 处理关系编辑
                function handleRelationEdit(nodeData, nodeElement) {{
                    if (!selectedNode) {{
                        // 选择第一个节点
                        selectedNode = nodeElement;
                        selectedNode.classed('selected-node', true);
                        console.log('选择了源节点:', nodeData.name);
                    }} else {{
                        // 选择第二个节点，创建关系
                        const sourceData = selectedNode.datum();
                        const targetData = nodeData;
                        
                        if (sourceData.id === targetData.id) {{
                            console.log('不能连接到自己');
                            clearSelection();
                            return;
                        }}
                        
                        // 检查是否已存在关系
                        const existingLink = links.find(link => 
                            (link.source.id === sourceData.id && link.target.id === targetData.id) ||
                            (link.source.id === targetData.id && link.target.id === sourceData.id)
                        );
                        
                        if (existingLink) {{
                            console.log('节点间已存在关系，打开关系编辑对话框');
                            openRelationEditDialog(existingLink);
                            clearSelection();
                            return;
                        }}
                        
                        // 弹窗询问关系类型
                        const relation = prompt('请输入关系类型:', '关联');
                        if (relation && relation.trim()) {{
                            createNewRelation(sourceData, targetData, relation.trim());
                        }}
                        
                        clearSelection();
                    }}
                }}
                
                // 打开节点编辑对话框（支持新增和编辑模式）
                function openNodeEditDialog(nodeData, isNewNode = false) {{
                    console.log(isNewNode ? '打开新增节点对话框' : '打开节点编辑对话框:', nodeData.name);
                    
                    // 为新增模式创建默认数据
                    if (isNewNode) {{
                        nodeData = {{
                            id: 'new_' + Date.now(),
                            name: '',
                            type: 'character',
                            description: '',
                            attributes: {{}}
                        }};
                    }}
                    
                    // 创建模态对话框
                    const dialog = document.createElement('div');
                    dialog.style.cssText = `
                        position: fixed;
                        top: 50%;
                        left: 50%;
                        transform: translate(-50%, -50%);
                        background: #2d2d2d;
                        color: white;
                        border: 2px solid #4a90e2;
                        border-radius: 10px;
                        padding: 20px;
                        min-width: 400px;
                        max-height: 80vh;
                        overflow-y: auto;
                        z-index: 1000;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.5);
                    `;
                    
                    // 创建背景遮罩
                    const overlay = document.createElement('div');
                    overlay.style.cssText = `
                        position: fixed;
                        top: 0;
                        left: 0;
                        width: 100%;
                        height: 100%;
                        background: rgba(0,0,0,0.7);
                        z-index: 999;
                    `;
                    
                    // 构建对话框内容
                    let dialogHTML = `
                        <h3 style="margin-top: 0; color: #4a90e2;">${{isNewNode ? '新增节点' : '编辑节点: ' + nodeData.name}}</h3>
                        <hr style="border-color: #4a90e2;">
                        
                        <div style="margin-bottom: 15px;">
                            <label>节点名称: <span style="color: #e74c3c;">*</span></label><br>
                            <input type="text" id="nodeName" value="${{nodeData.name}}" style="
                                width: 100%;
                                padding: 8px;
                                background: #3c3c3c;
                                color: white;
                                border: 1px solid #5a5a5a;
                                border-radius: 4px;
                                margin-top: 5px;
                            " placeholder="请输入节点名称">
                        </div>
                        
                        <div style="margin-bottom: 15px;">
                            <label>类型:</label><br>
                            <select id="nodeType" style="
                                width: 100%;
                                padding: 8px;
                                background: #3c3c3c;
                                color: white;
                                border: 1px solid #5a5a5a;
                                border-radius: 4px;
                                margin-top: 5px;
                            ">
                                <option value="character" ${{nodeData.type === 'character' ? 'selected' : ''}}>角色</option>
                                <option value="location" ${{nodeData.type === 'location' ? 'selected' : ''}}>地点</option>
                                <option value="item" ${{nodeData.type === 'item' ? 'selected' : ''}}>物品</option>
                                <option value="event" ${{nodeData.type === 'event' ? 'selected' : ''}}>事件</option>
                                <option value="concept" ${{nodeData.type === 'concept' ? 'selected' : ''}}>概念</option>
                            </select>
                        </div>
                        
                        <div style="margin-bottom: 15px;">
                            <label>描述:</label><br>
                            <textarea id="nodeDescription" style="
                                width: 100%;
                                height: 80px;
                                padding: 8px;
                                background: #3c3c3c;
                                color: white;
                                border: 1px solid #5a5a5a;
                                border-radius: 4px;
                                margin-top: 5px;
                                resize: vertical;
                            " placeholder="描述该节点的特征、属性等...">${{nodeData.description || ''}}</textarea>
                        </div>
                        
                        <h4 style="color: #4a90e2;">动态属性</h4>
                        <div id="attributesContainer">
                            <!-- 动态属性将在这里生成 -->
                        </div>
                        
                        <button id="addAttributeBtn" style="
                            background: #27ae60;
                            color: white;
                            border: none;
                            padding: 8px 16px;
                            border-radius: 4px;
                            cursor: pointer;
                            margin: 10px 5px 20px 0;
                        ">+ 添加属性</button>
                        
                        <div style="text-align: right; margin-top: 20px;">
                            <button id="cancelBtn" style="
                                background: #95a5a6;
                                color: white;
                                border: none;
                                padding: 10px 20px;
                                border-radius: 4px;
                                cursor: pointer;
                                margin-right: 10px;
                            ">取消</button>
                            <button id="saveBtn" style="
                                background: #4a90e2;
                                color: white;
                                border: none;
                                padding: 10px 20px;
                                border-radius: 4px;
                                cursor: pointer;
                            ">${{isNewNode ? '创建' : '保存'}}</button>
                        </div>
                    `;
                    
                    dialog.innerHTML = dialogHTML;
                    
                    // 添加到页面
                    document.body.appendChild(overlay);
                    document.body.appendChild(dialog);
                    
                    // 生成动态属性
                    generateAttributeInputs(nodeData, document.getElementById('attributesContainer'));
                    
                    // 绑定事件
                    document.getElementById('addAttributeBtn').onclick = () => addAttributeRow();
                    document.getElementById('cancelBtn').onclick = () => closeDialog();
                    document.getElementById('saveBtn').onclick = () => saveNodeData(nodeData, isNewNode);
                    overlay.onclick = () => closeDialog();
                    
                    // 自动聚焦名称输入框
                    setTimeout(() => {{
                        document.getElementById('nodeName').focus();
                    }}, 100);
                    
                    function closeDialog() {{
                        document.body.removeChild(overlay);
                        document.body.removeChild(dialog);
                    }}
                    
                    function addAttributeRow(key = '', value = '') {{
                        const container = document.getElementById('attributesContainer');
                        const row = document.createElement('div');
                        row.style.cssText = 'display: flex; gap: 10px; margin-bottom: 10px; align-items: center;';
                        
                        row.innerHTML = `
                            <input type="text" placeholder="属性名" value="${{key}}" style="
                                flex: 1;
                                padding: 6px;
                                background: #3c3c3c;
                                color: white;
                                border: 1px solid #5a5a5a;
                                border-radius: 4px;
                            ">
                            <input type="text" placeholder="属性值" value="${{value}}" style="
                                flex: 2;
                                padding: 6px;
                                background: #3c3c3c;
                                color: white;
                                border: 1px solid #5a5a5a;
                                border-radius: 4px;
                            ">
                            <button onclick="this.parentElement.remove()" style="
                                background: #e74c3c;
                                color: white;
                                border: none;
                                padding: 6px 10px;
                                border-radius: 4px;
                                cursor: pointer;
                            ">删除</button>
                        `;
                        
                        container.appendChild(row);
                    }}
                    
                    function generateAttributeInputs(data, container) {{
                        container.innerHTML = '';
                        
                        // 显示现有属性
                        if (data.attributes) {{
                            Object.entries(data.attributes).forEach(([key, value]) => {{
                                addAttributeRow(key, value);
                            }});
                        }}
                        
                        // 如果没有属性，添加一个空行
                        if (!data.attributes || Object.keys(data.attributes).length === 0) {{
                            addAttributeRow();
                        }}
                    }}
                    
                    function saveNodeData(originalData, isNew) {{
                        // 获取基本信息
                        const newName = document.getElementById('nodeName').value.trim();
                        const newType = document.getElementById('nodeType').value;
                        const newDescription = document.getElementById('nodeDescription').value.trim();
                        
                        if (!newName) {{
                            alert('节点名称不能为空');
                            document.getElementById('nodeName').focus();
                            return;
                        }}
                        
                        // 收集动态属性
                        const newAttributes = {{}};
                        const attributeRows = document.querySelectorAll('#attributesContainer > div');
                        
                        attributeRows.forEach(row => {{
                            const inputs = row.querySelectorAll('input');
                            const key = inputs[0].value.trim();
                            const value = inputs[1].value.trim();
                            
                            if (key && value) {{
                                newAttributes[key] = value;
                            }}
                        }});
                        
                        if (isNew) {{
                            // 创建新节点
                            const newNode = {{
                                id: newName, // 使用名称作为ID
                                name: newName,
                                type: newType,
                                description: newDescription,
                                attributes: newAttributes,
                                group: getTypeGroup(newType)
                            }};
                            
                            // 添加到nodes数组
                            nodes.push(newNode);
                            
                            console.log('创建新节点:', newNode);
                        }} else {{
                            // 更新现有节点数据
                            originalData.name = newName;
                            originalData.type = newType;
                            originalData.description = newDescription;
                            originalData.attributes = newAttributes;
                            
                            console.log('节点数据已更新:', originalData);
                        }}
                        
                        // 更新可视化
                        updateNodeVisualization();
                        
                        closeDialog();
                    }}
                    
                    function getTypeGroup(entityType) {{
                        const typeGroups = {{
                            'character': 1,
                            'location': 2,
                            'item': 3,
                            'event': 4,
                            'concept': 5
                        }};
                        return typeGroups[entityType] || 5;
                    }}
                    
                    function updateNodeVisualization() {{
                        // 重新绑定节点数据
                        const nodeSelection = g.selectAll('.node')
                            .data(nodes, d => d.id);
                        
                        // 添加新节点
                        const newNodes = nodeSelection.enter()
                            .append('circle')
                            .attr('class', d => `node ${{d.type}}`)
                            .attr('r', 20)
                            .call(d3.drag()
                                .on("start", dragstarted)
                                .on("drag", dragged)
                                .on("end", dragended));
                        
                        // 为新节点添加事件
                        newNodes.on("click", function(event, d) {{
                            event.stopPropagation();
                            console.log('新节点被点击:', d.name, '编辑模式:', editMode, '已选中节点:', selectedNode ? selectedNode.datum().name : 'none');
                            
                            if (editMode) {{
                                // 编辑模式：既可以编辑节点，也可以创建关系
                                if (!selectedNode) {{
                                    console.log('通过WebChannel编辑新节点:', d.name, '类型:', d.type);
                                    // 直接调用Python方法
                                    if (typeof bridge !== 'undefined' && bridge.editNode) {{
                                        bridge.editNode(d.name, d.type);
                                    }} else {{
                                        console.warn('WebChannel bridge不可用');
                                    }}
                                }} else {{
                                    console.log('进入关系编辑模式');
                                    handleRelationEdit(d, d3.select(this));
                                }}
                            }} else {{
                                console.log('普通模式，不执行任何操作');
                            }}
                            // 默认状态：点击节点不做任何操作，只有通过右侧面板的编辑按钮才能编辑节点
                        }});
                        
                        // 移除双击事件，避免意外触发编辑
                        
                        // 更新节点标签
                        const labelSelection = g.selectAll('.node-label')
                            .data(nodes, d => d.id);
                        
                        labelSelection.enter()
                            .append('text')
                            .attr('class', 'node-label')
                            .attr('dy', '.35em')
                            .merge(labelSelection)
                            .text(d => d.name);
                        
                        // 更新现有节点
                        nodeSelection.merge(newNodes)
                            .attr("class", d => `node ${{d.type}}`);
                        
                        // 重启力导向布局
                        simulation.nodes(nodes);
                        simulation.alpha(0.3).restart();
                    }}
                }}
                
                // 打开关系编辑对话框
                function openRelationEditDialog(linkData) {{
                    const newRelation = prompt(
                        `编辑关系: ${{linkData.source.name}} -> ${{linkData.target.name}}\\n当前关系: ${{linkData.relation}}\\n\\n请输入新的关系类型:`,
                        linkData.relation
                    );
                    
                    if (newRelation && newRelation.trim() && newRelation.trim() !== linkData.relation) {{
                        linkData.relation = newRelation.trim();
                        
                        // 更新关系标签
                        g.selectAll('.relation-label')
                            .text(d => d.relation || '关联');
                        
                        console.log('关系已更新:', newRelation);
                    }}
                }}
                
                // 创建新关系
                function createNewRelation(source, target, relation) {{
                    const newLink = {{
                        source: source,
                        target: target,
                        relation: relation
                    }};
                    
                    links.push(newLink);
                    
                    // 重新绑定数据并更新可视化
                    updateVisualization();
                    
                    console.log(`创建新关系: ${{source.name}} -> ${{target.name}} (${{relation}})`);
                }}
                
                // 更新可视化
                function updateVisualization() {{
                    // 更新连线
                    const linkSelection = g.select("g").selectAll("line")
                        .data(links);
                    
                    const newLinks = linkSelection.enter()
                        .append("line")
                        .attr("class", "link editable-link");
                    
                    // 为新连线添加事件
                    newLinks.on("click", function(event, d) {{
                        if (editMode) return;
                        event.stopPropagation();
                        openRelationEditDialog(d);
                    }});
                    
                    newLinks.on("contextmenu", function(event, d) {{
                        if (!editMode) return;
                        event.preventDefault();
                        const confirmed = confirm(`确定要删除关系 "${{d.source.name}} -> ${{d.target.name}} (${{d.relation}})" 吗？`);
                        if (confirmed) {{
                            deleteRelation(d);
                        }}
                    }});
                    
                    linkSelection.merge(newLinks);
                    
                    // 更新关系标签
                    const labelSelection = g.selectAll(".relation-label")
                        .data(links);
                    
                    const newLabels = labelSelection.enter()
                        .append("text")
                        .attr("class", "relation-label")
                        .style("cursor", "pointer");
                    
                    // 为新标签添加事件
                    newLabels.on("click", function(event, d) {{
                        if (editMode) return;
                        event.stopPropagation();
                        openRelationEditDialog(d);
                    }});
                    
                    labelSelection.merge(newLabels)
                        .text(d => d.relation || "关联");
                    
                    // 重启力导向布局
                    simulation.nodes(nodes);
                    simulation.force("link").links(links);
                    simulation.alpha(0.3).restart();
                }}
                link.on("contextmenu", function(event, d) {{
                    if (!editMode) return;
                    
                    event.preventDefault();
                    
                    const confirmed = confirm(`确定要删除关系 "${{d.source.name}} -> ${{d.target.name}} (${{d.relation}})" 吗？`);
                    if (confirmed) {{
                        deleteRelation(d);
                    }}
                }});
                
                // 删除关系
                function deleteRelation(linkData) {{
                    const index = links.findIndex(link => 
                        link.source.id === linkData.source.id && 
                        link.target.id === linkData.target.id &&
                        link.relation === linkData.relation
                    );
                    
                    if (index > -1) {{
                        links.splice(index, 1);
                        updateVisualization();
                        console.log('删除关系:', linkData.relation);
                    }}
                }}
                
                // SVG点击取消选择
                svg.on("click", function(event) {{
                    if (editMode && event.target === this) {{
                        clearSelection();
                    }}
                }});
                
                // 控制函数
                window.resetZoom = function() {{
                    console.log('重置视图');
                    svg.transition().duration(750).call(
                        zoom.transform,
                        d3.zoomIdentity.translate(0, 0).scale(1)
                    );
                }}
                
                let physicsEnabled = true;
                window.togglePhysics = function() {{
                    const btn = document.querySelector('button[onclick="togglePhysics()"]');
                    
                    if (physicsEnabled) {{
                        console.log('关闭物理效果（仍可拖动但不弹跳）');
                        physicsEnabled = false;
                        btn.textContent = '启动物理效果';
                        btn.style.backgroundColor = '#95a5a6';
                        
                        // 停止力的作用，但保持拖拽功能
                        simulation.stop();
                        
                    }} else {{
                        console.log('启动物理效果');
                        physicsEnabled = true;
                        btn.textContent = '关闭物理效果';
                        btn.style.backgroundColor = '#4a90e2';
                        
                        // 重新启动物理模拟
                        simulation.alpha(0.3).restart();
                    }}
                }}
                
                // 窗口大小改变时调整
                window.addEventListener('resize', () => {{
                    const newWidth = window.innerWidth;
                    const newHeight = window.innerHeight;
                    console.log(`窗口大小改变: ${{newWidth}}x${{newHeight}}`);
                    svg.attr("width", newWidth).attr("height", newHeight);
                    simulation.force("center", d3.forceCenter(newWidth / 2, newHeight / 2));
                    simulation.alpha(0.3).restart();
                }});
                
                console.log('D3版本:', typeof d3 !== 'undefined' ? d3.version : 'undefined');
        console.log('nodes数组是否存在:', typeof nodes !== 'undefined');
        console.log('links数组是否存在:', typeof links !== 'undefined');
        console.log('svg是否存在:', typeof svg !== 'undefined');
        console.log('simulation是否存在:', typeof simulation !== 'undefined');
        console.log('toggleEditMode是否存在:', typeof window.toggleEditMode !== 'undefined');
        
        // 添加全局调试函数
        window.debugGraph = function() {{
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
        }};
        
        console.log('✅ 调试函数已注册，可以在控制台调用 window.debugGraph() 查看状态');
        console.log('✅ 图谱初始化完成！');
                
            }} catch (error) {{
                console.error('图谱初始化过程中发生错误:', error);
                console.error('错误堆栈:', error.stack);
                throw error;
            }}
        }}
        
        // 页面加载完成后开始
        if (document.readyState === 'loading') {{
            console.log('等待DOM加载完成...');
            document.addEventListener('DOMContentLoaded', () => {{
                console.log('DOM加载完成，初始化WebChannel和D3');
                initWebChannel();
                loadD3Script();
            }});
        }} else {{
            console.log('DOM已加载，立即初始化WebChannel和D3');
            initWebChannel();
            loadD3Script();
        }}
        
        // 超时保护
        setTimeout(() => {{
            if (document.getElementById('loading').style.display !== 'none') {{
                console.warn('30秒超时，强制显示简化版本');
                showFallback();
            }}
        }}, 30000);
    </script>
</body>
</html>"""
    
    def _get_type_group(self, entity_type):
        """获取实体类型的分组ID"""
        type_groups = {
            'character': 1,
            'location': 2,
            'item': 3,
            'event': 4,
            'concept': 5
        }
        return type_groups.get(entity_type, 5)
    
    def _generate_fallback_html(self):
        """生成备用的简化HTML"""
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>ChronoForge Knowledge Graph</title>
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
        
        with open(self.graph_file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def update_entity_list(self, filter_type: str = "全部"):
        """更新实体列表"""
        self.entity_list.clear()
        
        # 从实际的知识图谱获取数据
        try:
            all_entities = self.get_all_entities()
            
            # 根据筛选条件过滤实体
            filtered_entities = []
            for entity in all_entities:
                if filter_type == "全部":
                    filtered_entities.append(entity)
                elif filter_type == "角色" and entity['type'] == "character":
                    filtered_entities.append(entity)
                elif filter_type == "地点" and entity['type'] == "location":
                    filtered_entities.append(entity)
                elif filter_type == "物品" and entity['type'] == "item":
                    filtered_entities.append(entity)
                elif filter_type == "事件" and entity['type'] == "event":
                    filtered_entities.append(entity)
            
            # 添加到列表
            for entity in filtered_entities:
                item_text = f"[{entity['type']}] {entity['name']}"
                self.entity_list.addItem(item_text)
                
        except Exception as e:
            logger.error(f"更新实体列表失败: {e}")
            # 如果获取失败，显示示例数据
            self._add_sample_entities()
    
    def get_all_entities(self):
        """获取所有实体（从实际存储获取）"""
        # 从文件系统加载实体数据
        entities_file = Path(__file__).parent / "data" / "entities.json"
        entities_file.parent.mkdir(exist_ok=True, parents=True)
        
        if entities_file.exists():
            try:
                with open(entities_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('entities', [])
            except Exception as e:
                logger.error(f"加载实体数据失败: {e}")
        
        # 如果文件不存在或加载失败，返回默认数据
        default_entities = [
            {"name": "主角", "type": "character", "description": "故事的主要角色", "created_time": time.time(), 
             "attributes": {"性别": "男", "年龄": "20", "职业": "冒险者"}},
            {"name": "神秘村庄", "type": "location", "description": "一个充满秘密的村庄", "created_time": time.time(),
             "attributes": {"人口": "200", "特色": "古老传说", "位置": "森林深处"}},
            {"name": "魔法剑", "type": "item", "description": "拥有神奇力量的武器", "created_time": time.time(),
             "attributes": {"攻击力": "150", "魔法属性": "火焰", "重量": "轻"}},
            {"name": "初次相遇", "type": "event", "description": "角色之间的第一次见面", "created_time": time.time(),
             "attributes": {"时间": "黄昏", "地点": "村庄广场", "天气": "晴朗"}},
            {"name": "智者", "type": "character", "description": "拥有古老智慧的长者", "created_time": time.time(),
             "attributes": {"年龄": "70", "智慧": "博学", "性格": "慈祥"}},
            {"name": "古老神殿", "type": "location", "description": "古代文明的遗迹", "created_time": time.time(),
             "attributes": {"建造年代": "千年前", "守护者": "智者", "秘密": "封印之力"}},
        ]
        
        # 保存默认数据
        self.save_entities(default_entities)
        return default_entities
    
    def save_entities(self, entities):
        """保存实体数据"""
        entities_file = Path(__file__).parent / "data" / "entities.json"
        entities_file.parent.mkdir(exist_ok=True, parents=True)
        
        try:
            data = {
                'entities': entities,
                'last_modified': time.time()
            }
            with open(entities_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存实体数据失败: {e}")
    
    def _add_sample_entities(self):
        """添加示例实体（备用方案）"""
        sample_entities = [
            {"name": "主角", "type": "character"},
            {"name": "神秘村庄", "type": "location"},
            {"name": "魔法剑", "type": "item"},
            {"name": "初次相遇", "type": "event"},
            {"name": "智者", "type": "character"},
            {"name": "古老神殿", "type": "location"},
        ]
        
        for entity in sample_entities:
            item_text = f"[{entity['type']}] {entity['name']}"
            self.entity_list.addItem(item_text)
    
    def update_stats(self):
        """更新图谱统计信息"""
        try:
            entities = self.get_all_entities()
            node_count = len(entities)
            
            # 计算关系数量（简单估算：每个实体平均2个关系）
            relation_count = node_count * 2
            
            import datetime
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            stats_text = f"""节点数量: {node_count}
关系数量: {relation_count}
最后更新: {current_time}"""
            
            self.stats_label.setText(stats_text)
            
        except Exception as e:
            logger.error(f"更新统计信息失败: {e}")
            import datetime
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            stats_text = f"""节点数量: 6
关系数量: 8
最后更新: {current_time}"""
            
            self.stats_label.setText(stats_text)
    
    def search_nodes(self):
        """搜索节点"""
        search_term = self.search_input.text().strip()
        if not search_term:
            return
        
        try:
            all_entities = self.get_all_entities()
            matching_entities = []
            
            # 搜索匹配的实体
            for entity in all_entities:
                if (search_term.lower() in entity['name'].lower() or 
                    search_term.lower() in entity.get('description', '').lower() or
                    search_term.lower() in entity['type'].lower()):
                    matching_entities.append(entity)
            
            # 更新实体列表显示搜索结果
            self.entity_list.clear()
            for entity in matching_entities:
                item_text = f"[{entity['type']}] {entity['name']}"
                self.entity_list.addItem(item_text)
            
            if not matching_entities:
                self.entity_list.addItem("未找到匹配的节点")
                
            logger.info(f"搜索节点: {search_term}, 找到 {len(matching_entities)} 个结果")
            
        except Exception as e:
            logger.error(f"搜索节点失败: {e}")
            QMessageBox.warning(self, "搜索错误", f"搜索失败：{str(e)}")
    
    def clear_search(self):
        """清除搜索"""
        self.search_input.clear()
        self.update_entity_list()
    
    def filter_entities(self):
        """过滤实体"""
        sender = self.sender()
        
        # 取消其他过滤按钮的选中状态
        filter_buttons = [self.filter_all_btn, self.filter_character_btn, 
                         self.filter_location_btn, self.filter_item_btn, self.filter_event_btn]
        
        for btn in filter_buttons:
            if btn != sender:
                btn.setChecked(False)
        
        sender.setChecked(True)
        
        # 获取过滤类型并更新列表
        filter_type = sender.text()
        logger.info(f"过滤实体类型: {filter_type}")
        
        # 清除搜索框并应用过滤
        self.search_input.clear()
        self.update_entity_list(filter_type)
    
    def on_entity_selected(self, item):
        """实体被选中"""
        entity_name = item.text()
        
        # 如果是搜索结果为空的提示，不处理
        if entity_name == "未找到匹配的节点":
            self.detail_text.clear()
            return
        
        try:
            # 解析实体信息
            if '] ' in entity_name:
                entity_type = entity_name.split('[')[1].split(']')[0]
                entity_display_name = entity_name.split('] ', 1)[1]
            else:
                entity_type = "未知"
                entity_display_name = entity_name
            
            # 从存储中获取完整实体信息
            all_entities = self.get_all_entities()
            selected_entity = None
            
            for entity in all_entities:
                if entity['name'] == entity_display_name and entity['type'] == entity_type:
                    selected_entity = entity
                    break
            
            if selected_entity:
                import datetime
                created_time = datetime.datetime.fromtimestamp(
                    selected_entity.get('created_time', time.time())
                ).strftime("%Y-%m-%d %H:%M:%S")
                
                detail_text = f"""节点信息:
名称: {selected_entity['name']}
类型: {selected_entity['type']}
描述: {selected_entity.get('description', '暂无描述')}
创建时间: {created_time}
属性: {len(selected_entity.get('attributes', {}))} 个
关系: 开发中..."""
                
            else:
                # 备用显示
                detail_text = f"""节点信息:
名称: {entity_display_name}
类型: {entity_type}
创建时间: 未知
描述: 暂无描述
属性: 开发中...
关系: 开发中..."""
            
            self.detail_text.setText(detail_text)
            self.current_selected_node = entity_name
            
        except Exception as e:
            logger.error(f"显示节点详情失败: {e}")
            self.detail_text.setText(f"显示详情时出错：{str(e)}")
            self.current_selected_node = entity_name
    
    def focus_on_node(self, item):
        """聚焦到节点"""
        entity_name = item.text()
        
        if entity_name == "未找到匹配的节点":
            return
            
        # 在WebView中执行JavaScript来高亮节点
        try:
            if '] ' in entity_name:
                node_name = entity_name.split('] ', 1)[1]
            else:
                node_name = entity_name
                
            # 执行JavaScript来聚焦节点
            js_code = f"""
            // 查找并高亮节点
            const targetNode = d3.selectAll('.node').filter(d => d.name === '{node_name}');
            if (!targetNode.empty()) {{
                const nodeData = targetNode.datum();
                
                // 将视图中心移动到节点位置
                const svg = d3.select('#graph');
                const transform = d3.zoomTransform(svg.node());
                const scale = Math.max(1, transform.k);
                
                svg.transition().duration(1000).call(
                    zoom.transform,
                    d3.zoomIdentity
                        .translate(width / 2 - nodeData.x * scale, height / 2 - nodeData.y * scale)
                        .scale(scale)
                );
                
                // 高亮节点
                targetNode.transition().duration(300)
                    .attr('r', 30)
                    .style('stroke-width', '4px')
                    .style('stroke', '#ff6b6b');
                
                // 恢复正常大小
                setTimeout(() => {{
                    targetNode.transition().duration(300)
                        .attr('r', 20)
                        .style('stroke-width', '2px')
                        .style('stroke', '#fff');
                }}, 1500);
            }}
            """
            
            self.graph_view.page().runJavaScript(js_code)
            logger.info(f"聚焦到节点: {node_name}")
            
        except Exception as e:
            logger.error(f"聚焦节点失败: {e}")
    
    def add_node(self):
        """添加节点 - 使用Qt原生对话框"""
        try:
            # 直接使用Qt编辑对话框，isNewNode=True表示新增模式
            self.edit_node_with_python_dialog("", "character", is_new_node=True)
            logger.info("打开Qt新增节点对话框")
        except Exception as e:
            logger.error(f"打开Qt新增节点对话框失败: {e}")
            QMessageBox.warning(self, "错误", f"打开对话框失败：{str(e)}")
    
    def edit_node(self):
        """编辑节点 - 直接使用Python备用编辑对话框"""
        if not self.current_selected_node:
            QMessageBox.information(
                self, 
                "提示", 
                "请先在实体列表中选择一个节点。"
            )
            return
        
        # 解析当前选中的节点信息
        node_text = self.current_selected_node
        
        # 提取节点名称和类型
        if '] ' in node_text:
            entity_type = node_text.split('[')[1].split(']')[0]
            entity_name = node_text.split('] ', 1)[1]
        else:
            entity_name = node_text
            entity_type = "concept"
        
        logger.info(f"编辑节点: {entity_name} (类型: {entity_type})")
        
        # 直接使用Python备用编辑方案
        self.edit_node_with_python_dialog(entity_name, entity_type)
    
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
            from PySide6.QtWidgets import QScrollArea
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setMaximumHeight(200)  # 限制最大高度
            scroll_area.setMinimumHeight(120)  # 设置最小高度
            scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            # 设置滚动条样式
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
            attr_scroll_layout = QVBoxLayout(attr_scroll)
            attr_scroll_layout.setSpacing(8)  # 增加行间距
            attr_scroll_layout.setContentsMargins(5, 5, 5, 5)  # 添加边距
            
            # 设置滚动区域的内容widget
            scroll_area.setWidget(attr_scroll)
            
            # 存储属性行的列表
            self.attr_rows = []
            
            def add_attribute_row(key='', value=''):
                """添加一行属性编辑"""
                row_widget = QWidget()
                row_widget.setMinimumHeight(40)  # 设置最小高度
                row_widget.setMaximumHeight(50)  # 设置最大高度
                row_widget.setStyleSheet("""
                    QWidget {
                        background-color: #2b2b2b;
                        border-radius: 3px;
                    }
                """)
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(2, 2, 2, 2)
                row_layout.setSpacing(8)
                
                # 属性名输入框
                key_edit = QLineEdit(key)
                key_edit.setPlaceholderText("属性名")
                key_edit.setMinimumWidth(120)
                key_edit.setMaximumWidth(150)
                key_edit.setMinimumHeight(30)
                
                # 属性值输入框  
                value_edit = QLineEdit(value)
                value_edit.setPlaceholderText("属性值")
                value_edit.setMinimumHeight(30)
                
                # 删除按钮
                delete_btn = QPushButton("删除")
                delete_btn.setMinimumWidth(60)
                delete_btn.setMaximumWidth(80)
                delete_btn.setMinimumHeight(30)
                delete_btn.setStyleSheet("QPushButton { background-color: #e74c3c; }")
                
                def remove_row():
                    if len(self.attr_rows) > 1:  # 至少保留一行
                        # 从列表中移除这一行
                        self.attr_rows.remove((key_edit, value_edit, row_widget))
                        
                        # 完全重建布局
                        rebuild_layout()
                
                def rebuild_layout():
                    """重建整个属性布局"""
                    # 清除现有的所有widgets
                    while attr_scroll_layout.count():
                        child = attr_scroll_layout.takeAt(0)
                        if child.widget():
                            child.widget().deleteLater()
                        elif child.spacerItem():
                            # 移除spacer
                            pass
                    
                    # 重新添加所有剩余的行
                    for key_edit, value_edit, old_widget in self.attr_rows:
                        # 获取当前值
                        key_val = key_edit.text()
                        value_val = value_edit.text()
                        
                        # 创建新的行widget
                        new_row_widget = QWidget()
                        new_row_widget.setMinimumHeight(40)
                        new_row_widget.setMaximumHeight(50)
                        new_row_widget.setStyleSheet("""
                            QWidget {
                                background-color: #2b2b2b;
                                border-radius: 3px;
                            }
                        """)
                        new_row_layout = QHBoxLayout(new_row_widget)
                        new_row_layout.setContentsMargins(2, 2, 2, 2)
                        new_row_layout.setSpacing(8)
                        
                        # 创建新的控件
                        new_key_edit = QLineEdit(key_val)
                        new_key_edit.setPlaceholderText("属性名")
                        new_key_edit.setMinimumWidth(120)
                        new_key_edit.setMaximumWidth(150)
                        new_key_edit.setMinimumHeight(30)
                        
                        new_value_edit = QLineEdit(value_val)
                        new_value_edit.setPlaceholderText("属性值")
                        new_value_edit.setMinimumHeight(30)
                        
                        new_delete_btn = QPushButton("删除")
                        new_delete_btn.setMinimumWidth(60)
                        new_delete_btn.setMaximumWidth(80)
                        new_delete_btn.setMinimumHeight(30)
                        new_delete_btn.setStyleSheet("QPushButton { background-color: #e74c3c; }")
                        new_delete_btn.clicked.connect(lambda checked, ke=new_key_edit, ve=new_value_edit, rw=new_row_widget: remove_specific_row(ke, ve, rw))
                        
                        # 添加到布局
                        new_row_layout.addWidget(QLabel("属性:"))
                        new_row_layout.addWidget(new_key_edit)
                        new_row_layout.addWidget(QLabel("值:"))
                        new_row_layout.addWidget(new_value_edit)
                        new_row_layout.addWidget(new_delete_btn)
                        
                        attr_scroll_layout.addWidget(new_row_widget)
                        
                        # 更新列表中的引用
                        idx = self.attr_rows.index((key_edit, value_edit, old_widget))
                        self.attr_rows[idx] = (new_key_edit, new_value_edit, new_row_widget)
                    
                    # 重新添加spacer
                    from PySide6.QtWidgets import QSpacerItem, QSizePolicy
                    spacer = QSpacerItem(1, 1, QSizePolicy.Minimum, QSizePolicy.Expanding)
                    attr_scroll_layout.addItem(spacer)
                
                def remove_specific_row(ke, ve, rw):
                    """删除指定行"""
                    if len(self.attr_rows) > 1:
                        self.attr_rows.remove((ke, ve, rw))
                        rebuild_layout()
                
                delete_btn.clicked.connect(remove_row)
                
                # 添加标签和控件
                row_layout.addWidget(QLabel("属性:"))
                row_layout.addWidget(key_edit)
                row_layout.addWidget(QLabel("值:"))
                row_layout.addWidget(value_edit)
                row_layout.addWidget(delete_btn)
                
                attr_scroll_layout.addWidget(row_widget)
                self.attr_rows.append((key_edit, value_edit, row_widget))
                
                return key_edit, value_edit
            
            # 加载现有属性
            existing_attrs = current_entity.get('attributes', {})
            if existing_attrs:
                for key, value in existing_attrs.items():
                    add_attribute_row(key, str(value))
            else:
                # 如果没有属性，添加一个空行
                add_attribute_row()
            
            # 在属性列表末尾添加弹簧，确保内容顶部对齐
            # 使用QSpacerItem而不是addStretch()，这样删除widget时布局会自动调整
            from PySide6.QtWidgets import QSpacerItem, QSizePolicy
            spacer = QSpacerItem(1, 1, QSizePolicy.Minimum, QSizePolicy.Expanding)
            attr_scroll_layout.addItem(spacer)
            
            # 添加滚动区域到属性组布局
            attr_layout.addWidget(scroll_area)
            
            # 添加属性按钮
            add_attr_btn = QPushButton("+ 添加属性")
            add_attr_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
            add_attr_btn.clicked.connect(lambda: add_attribute_row())
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
                # 验证输入
                new_name = name_edit.text().strip()
                if not new_name:
                    QMessageBox.warning(dialog, "验证错误", "节点名称不能为空！")
                    name_edit.setFocus()
                    return
                
                # 收集动态属性
                new_attributes = {}
                for key_edit, value_edit, _ in self.attr_rows:
                    key = key_edit.text().strip()
                    value = value_edit.text().strip()
                    if key and value:  # 只保存非空的属性
                        new_attributes[key] = value
                
                # 更新或创建实体数据
                current_entity['name'] = new_name
                current_entity['type'] = type_combo.currentText()
                current_entity['description'] = desc_edit.toPlainText().strip()
                current_entity['attributes'] = new_attributes
                current_entity['last_modified'] = time.time()
                
                if is_new_node:
                    # 添加新实体
                    all_entities = self.get_all_entities()
                    all_entities.append(current_entity)
                    self.save_entities(all_entities)
                    logger.info(f"创建新节点: {new_name} (类型: {type_combo.currentText()})")
                else:
                    # 更新现有实体
                    all_entities = self.get_all_entities()
                    self.save_entities(all_entities)
                    logger.info(f"更新节点: {new_name} (类型: {type_combo.currentText()})")
                
                # 更新界面
                self.update_entity_list()
                self.update_stats()
                self.refresh_graph()  # 刷新图谱显示
                
                QMessageBox.information(dialog, "成功", success_msg)
                dialog.accept()
            
            save_btn.clicked.connect(save_changes)
            
            button_layout.addWidget(cancel_btn)
            button_layout.addWidget(save_btn)
            main_layout.addLayout(button_layout)
            
            # 设置默认焦点
            name_edit.setFocus()
            
            # 显示对话框
            dialog.exec()
            
        except Exception as e:
            logger.error(f"Qt编辑对话框失败: {e}")
            QMessageBox.critical(self, "错误", f"编辑失败: {str(e)}")
    
    def delete_node(self):
        """删除节点"""
        if not self.current_selected_node:
            QMessageBox.warning(self, "提示", "请先选择一个节点")
            return
        
        # 解析节点名称
        node_text = self.current_selected_node
        if '] ' in node_text:
            node_name = node_text.split('] ', 1)[1]
        else:
            node_name = node_text
        
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除节点 '{node_name}' 吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 从实际存储中删除节点
            if '] ' in node_text:
                entity_type = node_text.split('[')[1].split(']')[0]
                entity_name = node_text.split('] ', 1)[1]
            else:
                entity_name = node_text
                entity_type = "concept"
            
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
                
                # 清除选择状态
                self.current_selected_node = None
                self.detail_text.clear()
                self.detail_text.setPlaceholderText("选择一个节点查看详细信息...")
                
                # 更新实体列表和统计
                self.update_entity_list()
                self.update_stats()
                
                QMessageBox.information(self, "成功", f"节点 '{entity_name}' 删除成功")
                logger.info(f"删除节点: {entity_name}")
            else:
                QMessageBox.warning(self, "错误", "找不到要删除的节点")
    
    def export_graph(self):
        """导出图谱"""
        try:
            # 选择导出文件位置
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "导出知识图谱",
                str(Path.home() / "knowledge_graph.json"),
                "JSON 文件 (*.json);;所有文件 (*.*)"
            )
            
            if not file_path:
                return
            
            # 获取所有实体数据
            entities = self.get_all_entities()
            
            # 构建导出数据
            export_data = {
                'metadata': {
                    'title': 'ChronoForge Knowledge Graph',
                    'created_by': 'ChronoForge',
                    'export_time': time.time(),
                    'version': '1.0.0'
                },
                'entities': entities,
                'statistics': {
                    'total_entities': len(entities),
                    'entity_types': {}
                }
            }
            
            # 统计各类型实体数量
            for entity in entities:
                entity_type = entity.get('type', 'unknown')
                export_data['statistics']['entity_types'][entity_type] = \
                    export_data['statistics']['entity_types'].get(entity_type, 0) + 1
            
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            QMessageBox.information(
                self, 
                "导出成功", 
                f"知识图谱已导出到：\n{file_path}\n\n包含 {len(entities)} 个实体"
            )
            logger.info(f"知识图谱导出成功: {file_path}")
            
        except Exception as e:
            logger.error(f"导出图谱失败: {e}")
            QMessageBox.critical(self, "导出失败", f"导出失败：{str(e)}")
    
    def reset_view(self):
        """重置视图"""
        try:
            # 在WebView中执行JavaScript重置视图
            js_code = """
            if (typeof resetZoom === 'function') {
                resetZoom();
            }
            """
            self.graph_view.page().runJavaScript(js_code)
            logger.info("图谱视图已重置")
            
        except Exception as e:
            logger.error(f"重置视图失败: {e}")
            # 如果JavaScript执行失败，重新生成图谱
            self.refresh_graph()
    
    def open_dev_tools(self):
        """打开开发者工具"""
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            
            # 创建开发者工具窗口
            if not hasattr(self, 'dev_view'):
                self.dev_view = QWebEngineView()
                self.dev_view.setWindowTitle("开发者工具 - ChronoForge Graph")
                self.dev_view.resize(1000, 600)
            
            # 设置开发者工具页面
            self.graph_view.page().setDevToolsPage(self.dev_view.page())
            self.dev_view.show()
            
            logger.info("开发者工具已打开")
            
        except Exception as e:
            logger.error(f"打开开发者工具失败: {e}")
            QMessageBox.warning(self, "错误", f"无法打开开发者工具：{str(e)}")
    
    def show_debug_info(self):
        """显示调试信息"""
        try:
            # 执行JavaScript获取调试信息
            js_code = """
            if (typeof window.debugGraph === 'function') {
                window.debugGraph();
                // 返回一些基本信息
                {
                    d3_loaded: typeof d3 !== 'undefined',
                    d3_version: typeof d3 !== 'undefined' ? d3.version : 'not loaded',
                    nodes_count: typeof nodes !== 'undefined' ? nodes.length : 'undefined',
                    links_count: typeof links !== 'undefined' ? links.length : 'undefined',
                    edit_mode: typeof editMode !== 'undefined' ? editMode : 'undefined',
                    selected_node: typeof selectedNode !== 'undefined' && selectedNode ? selectedNode.datum().name : 'none',
                    webchannel_bridge: typeof bridge !== 'undefined' ? 'available' : 'not available'
                };
            } else {
                { error: 'debugGraph function not available' };
            }
            """
            
            def show_result(result):
                if result:
                    import json
                    debug_text = json.dumps(result, indent=2, ensure_ascii=False)
                    QMessageBox.information(self, "调试信息", f"图谱状态：\n{debug_text}")
                else:
                    QMessageBox.information(self, "调试信息", "无法获取调试信息")
            
            self.graph_view.page().runJavaScript(js_code, show_result)
            
        except Exception as e:
            logger.error(f"显示调试信息失败: {e}")
            QMessageBox.warning(self, "错误", f"获取调试信息失败：{str(e)}")


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
        
        # 智能对话页面
        self.play_page = IntegratedPlayPage(self.game_engine)
        self.tabs.addTab(self.play_page, "智能对话")
        
        # 知识图谱页面
        self.graph_page = GraphPage(self.memory)
        self.tabs.addTab(self.graph_page, "知识图谱")
        
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
                self.memory.save_all_memory()
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
        /* 主窗口 */
        QMainWindow {
            background-color: #1e1e1e;
            color: #ffffff;
        }
        
        /* 标签页 */
        QTabWidget::pane {
            border: 1px solid #3c3c3c;
            background-color: #2d2d2d;
            border-radius: 4px;
        }
        QTabBar::tab {
            background-color: #3c3c3c;
            color: #ffffff;
            padding: 10px 20px;
            margin-right: 2px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            min-width: 100px;
        }
        QTabBar::tab:selected {
            background-color: #4a90e2;
            font-weight: bold;
        }
        QTabBar::tab:hover {
            background-color: #505050;
        }
        
        /* 输入控件 */
        QTextEdit, QLineEdit {
            background-color: #3c3c3c;
            color: #ffffff;
            border: 1px solid #5a5a5a;
            border-radius: 4px;
            padding: 8px;
            font-size: 14px;
        }
        QTextEdit:focus, QLineEdit:focus {
            border: 2px solid #4a90e2;
        }
        
        /* 下拉框 */
        QComboBox {
            background-color: #3c3c3c;
            color: #ffffff;
            border: 1px solid #5a5a5a;
            border-radius: 4px;
            padding: 6px 10px;
            min-width: 150px;
        }
        QComboBox:hover {
            border: 1px solid #4a90e2;
        }
        QComboBox::drop-down {
            border: none;
            background-color: #4a90e2;
            width: 20px;
            border-radius: 2px;
        }
        QComboBox::down-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 4px solid #ffffff;
        }
        
        /* 按钮 */
        QPushButton {
            background-color: #4a90e2;
            color: #ffffff;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            font-weight: bold;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #357abd;
        }
        QPushButton:pressed {
            background-color: #2e5f99;
        }
        QPushButton:disabled {
            background-color: #5a5a5a;
            color: #888888;
        }
        
        /* 分组框 */
        QGroupBox {
            color: #ffffff;
            border: 1px solid #5a5a5a;
            border-radius: 8px;
            margin-top: 1ex;
            padding-top: 15px;
            font-weight: bold;
            background-color: #2d2d2d;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 15px;
            padding: 0 8px 0 8px;
            color: #4a90e2;
            font-size: 14px;
        }
        
        /* 标签 */
        QLabel {
            color: #ffffff;
            font-size: 13px;
        }
        
        /* 列表 */
        QListWidget {
            background-color: #3c3c3c;
            color: #ffffff;
            border: 1px solid #5a5a5a;
            border-radius: 4px;
            padding: 4px;
        }
        QListWidget::item {
            padding: 6px;
            border-radius: 2px;
        }
        QListWidget::item:selected {
            background-color: #4a90e2;
        }
        QListWidget::item:hover {
            background-color: #505050;
        }
        
        /* 分割器 */
        QSplitter::handle {
            background-color: #5a5a5a;
        }
        QSplitter::handle:horizontal {
            width: 3px;
        }
        QSplitter::handle:vertical {
            height: 3px;
        }
        
        /* 复选框 */
        QCheckBox {
            color: #ffffff;
            spacing: 8px;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border-radius: 2px;
            border: 2px solid #5a5a5a;
            background-color: #3c3c3c;
        }
        QCheckBox::indicator:checked {
            background-color: #4a90e2;
            border-color: #4a90e2;
        }
        QCheckBox::indicator:checked:hover {
            background-color: #357abd;
        }
        
        /* 滚动条 */
        QScrollBar:vertical {
            background-color: #2d2d2d;
            width: 12px;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background-color: #5a5a5a;
            border-radius: 6px;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover {
            background-color: #6a6a6a;
        }
        
        /* 消息框和对话框样式 */
        QMessageBox, QInputDialog, QDialog {
            background-color: #2d2d2d;
            color: #ffffff;
            border: 1px solid #5a5a5a;
            border-radius: 8px;
        }
        QMessageBox QLabel, QInputDialog QLabel {
            color: #ffffff;
            background-color: transparent;
        }
        QMessageBox QPushButton, QInputDialog QPushButton, QDialog QPushButton {
            background-color: #4a90e2;
            color: #ffffff;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            min-width: 80px;
        }
        QMessageBox QPushButton:hover, QInputDialog QPushButton:hover, QDialog QPushButton:hover {
            background-color: #357abd;
        }
        QMessageBox QPushButton:pressed, QInputDialog QPushButton:pressed, QDialog QPushButton:pressed {
            background-color: #2e5f99;
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