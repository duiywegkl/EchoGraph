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
    QRadioButton, QButtonGroup, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, QObject, Signal as pyqtSignal, QUrl, Slot, QTimer, QPropertyAnimation, QRect, QThread
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtGui import QIcon, QFont, QColor, QIntValidator, QTextCursor, QPainter, QPen, QBrush
from dotenv import dotenv_values, set_key
from loguru import logger

sys.path.append(str(Path(__file__).parent))
from src.memory import GRAGMemory

# 导入重构后的组件
from src.ui.widgets.chat_components import ChatDisplayWidget, ChatBubble, LoadingBubble
from src.ui.managers.conversation_manager import ConversationManager
from src.ui.workers.llm_worker import LLMWorkerThread
from src.ui.managers.scenario_manager import ScenarioManager
from src.ui.managers.window_manager import WindowManager
from src.ui.managers.resource_cleanup_manager import ResourceCleanupManager
from src.ui.generators.graph_html_generator import GraphHTMLGenerator

class ChatBubble(QFrame):
    """聊天气泡组件"""
    
    # 添加信号
    message_clicked = pyqtSignal(object)  # 点击消息时发出信号
    
    def __init__(self, message: str, is_user: bool, color: str = None):
        super().__init__()
        self.message = message
        self.is_user = is_user
        self.delete_mode_enabled = False  # 是否处于删除模式
        # 统一的深色主题配色
        if is_user:
            # 用户消息：简洁的蓝色
            self.color = color or "#5865f2"  # Discord蓝
            self.text_color = "#ffffff"
            self.border_color = "transparent"
        else:
            # AI消息：深色背景，浅色文字，微妙边框
            self.color = color or "#36393f"  # Discord深色
            self.text_color = "#dcddde"      # 温和的浅色
            self.border_color = "#40444b"    # 微妙的边框
        self.setup_ui()
    
    def set_delete_mode(self, enabled: bool):
        """设置删除模式"""
        self.delete_mode_enabled = enabled
        if enabled:
            self.setCursor(Qt.PointingHandCursor)
            # 添加删除模式的视觉提示
            self.setStyleSheet(self.styleSheet() + """
                QFrame:hover {
                    border: 2px solid #e74c3c !important;
                    background-color: rgba(231, 76, 60, 0.1) !important;
                }
            """)
        else:
            self.setCursor(Qt.ArrowCursor)
            self.setStyleSheet("")  # 重置样式
            self.setup_ui()  # 重新设置UI样式
    
    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if self.delete_mode_enabled and event.button() == Qt.LeftButton:
            self.message_clicked.emit(self)
        super().mousePressEvent(event)
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 8)
        
        # 创建消息标签
        message_label = QLabel(self.message)
        message_label.setWordWrap(True)
        
        if self.is_user:
            # 用户消息样式 - 简洁的蓝色
            message_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {self.color};
                    color: {self.text_color};
                    border-radius: 18px;
                    padding: 12px 16px;
                    font-size: 14px;
                    line-height: 1.4;
                    max-width: 400px;
                    min-height: 20px;
                    border: none;
                    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                    font-weight: 500;
                }}
            """)
        else:
            # AI消息样式 - Discord风格深色
            message_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {self.color};
                    color: {self.text_color};
                    border: 1px solid {self.border_color};
                    border-radius: 8px;
                    padding: 12px 16px;
                    font-size: 14px;
                    line-height: 1.5;
                    max-width: 450px;
                    min-height: 20px;
                    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                }}
            """)
        
        message_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        if self.is_user:
            # 用户消息右对齐
            layout.addStretch()
            layout.addWidget(message_label)
        else:
            # AI消息左对齐
            layout.addWidget(message_label)
            layout.addStretch()

class LoadingBubble(QFrame):
    """加载动画气泡"""
    def __init__(self):
        super().__init__()
        self.dots_count = 1
        self.max_dots = 6
        self.setup_ui()
        
        # 设置定时器来更新动画
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(500)  # 每500ms更新一次
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 8)
        
        self.message_label = QLabel("助手正在思考...")
        self.message_label.setStyleSheet("""
            QLabel {
                background-color: #36393f;
                color: #72767d;
                border: 1px solid #40444b;
                border-radius: 8px;
                padding: 12px 16px;
                font-size: 14px;
                min-width: 120px;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                font-style: italic;
            }
        """)
        
        layout.addWidget(self.message_label)
        layout.addStretch()
    
    def update_animation(self):
        dots = "." * self.dots_count
        self.message_label.setText(f"助手正在思考{dots}")
        self.dots_count = (self.dots_count % self.max_dots) + 1
    
    def stop_animation(self):
        self.timer.stop()

class ChatDisplayWidget(QScrollArea):
    """聊天显示组件"""
    def __init__(self):
        super().__init__()
        self.messages_layout = QVBoxLayout()
        self.current_loading_bubble = None
        self.message_widgets = []  # 存储所有消息组件的引用
        self.setup_ui()
    
    def setup_ui(self):
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMinimumHeight(400)
        
        # 创建容器widget
        container = QWidget()
        container.setStyleSheet("""
            QWidget {
                background-color: #2f3136;
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(5)
        container_layout.setContentsMargins(0, 10, 0, 10)
        
        # 添加消息布局
        container_layout.addLayout(self.messages_layout)
        container_layout.addStretch()  # 推到顶部
        
        self.setWidget(container)
        
        # 设置样式 - 现代深色聊天背景（类似Discord/Slack）
        self.setStyleSheet("""
            QScrollArea {
                border: none;
                border-radius: 0px;
                background-color: #2f3136;
            }
            QWidget {
                background-color: #2f3136;
            }
            QScrollBar:vertical {
                width: 8px;
                border-radius: 4px;
                background-color: #2f3136;
                border: none;
            }
            QScrollBar::handle:vertical {
                border-radius: 4px;
                background-color: #202225;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #40444b;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
        """)
    
    def add_message(self, message: str, is_user: bool, color: str = None):
        # 限制消息历史大小，防止内存泄漏
        MAX_MESSAGES = 1000  # 最多保留1000条消息
        
        # 如果超过限制，删除最旧的消息
        if len(self.message_widgets) >= MAX_MESSAGES:
            old_msg_info = self.message_widgets.pop(0)
            old_widget = old_msg_info['widget']
            self.messages_layout.removeWidget(old_widget)
            old_widget.deleteLater()
            logger.info(f"🧹 [UI] 删除旧消息以防止内存泄漏，当前消息数: {len(self.message_widgets)}")
        
        bubble = ChatBubble(message, is_user, color)
        bubble.message_clicked.connect(self.on_message_clicked)  # 连接点击信号
        self.messages_layout.addWidget(bubble)
        self.message_widgets.append({
            'widget': bubble,
            'message': message,
            'is_user': is_user,
            'color': color
        })
        self.scroll_to_bottom()
    
    def set_delete_mode(self, enabled: bool):
        """设置所有气泡的删除模式"""
        for msg_info in self.message_widgets:
            msg_info['widget'].set_delete_mode(enabled)
    
    def on_message_clicked(self, bubble):
        """处理消息气泡点击事件"""
        # 找到对应的消息信息
        for i, msg_info in enumerate(self.message_widgets):
            if msg_info['widget'] == bubble:
                # 询问确认删除
                reply = QMessageBox.question(
                    self,
                    "确认删除",
                    f"确定要删除这条{'用户' if msg_info['is_user'] else 'AI'}消息吗？",
                    QMessageBox.Yes | QMessageBox.No
                )
                
                if reply == QMessageBox.Yes:
                    # 从布局中移除
                    self.messages_layout.removeWidget(bubble)
                    bubble.deleteLater()
                    
                    # 从列表中移除
                    self.message_widgets.pop(i)
                    
                    # 发出删除信号通知父组件更新对话历史
                    # TODO: 实现对话历史同步
                
                break
    
    def show_loading_animation(self):
        if self.current_loading_bubble:
            self.remove_loading_animation()
        
        self.current_loading_bubble = LoadingBubble()
        self.messages_layout.addWidget(self.current_loading_bubble)
        self.scroll_to_bottom()
        return self.current_loading_bubble
    
    def remove_loading_animation(self):
        if self.current_loading_bubble:
            self.current_loading_bubble.stop_animation()
            self.messages_layout.removeWidget(self.current_loading_bubble)
            self.current_loading_bubble.deleteLater()
            self.current_loading_bubble = None
    
    def scroll_to_bottom(self):
        # 延迟滚动以确保布局完成
        QTimer.singleShot(50, lambda: self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        ))
    
    def clear_messages(self):
        # 清空所有消息
        while self.messages_layout.count():
            child = self.messages_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.remove_loading_animation()
        self.message_widgets.clear()
    
    def remove_last_ai_message(self):
        """删除最后一条AI回复"""
        # 从后往前找最后一条AI消息
        for i in range(len(self.message_widgets) - 1, -1, -1):
            if not self.message_widgets[i]['is_user']:
                # 找到最后一条AI消息，删除它
                widget_to_remove = self.message_widgets[i]['widget']
                self.messages_layout.removeWidget(widget_to_remove)
                widget_to_remove.deleteLater()
                self.message_widgets.pop(i)
                return True
        return False
    
    def get_last_user_message(self):
        """获取最后一条用户消息"""
        for i in range(len(self.message_widgets) - 1, -1, -1):
            if self.message_widgets[i]['is_user']:
                return self.message_widgets[i]['message']
        return None
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
        
        # 如果没有当前对话，选择最新的（但如果已经有了就不要重复触发）
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
        
        # 切换到新对话
        self.current_conversation_id = conv_id
        
        # 重新加载更新列表，但不要触发自动选择逻辑
        self.load_conversations()  
        
        # 手动发出对话切换信号
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
        
        # 初始化加载现有对话
        self.load_existing_conversations()
    
    def load_existing_conversations(self):
        """加载现有对话到下拉框"""
        try:
            logger.info("📥 [UI] 开始加载现有对话...")
            
            # 触发对话管理器加载对话
            self.conversation_manager.load_conversations()
            
            # 获取排序后的对话列表
            conversations = list(self.conversation_manager.conversations.values())
            logger.info(f"📋 [UI] 找到 {len(conversations)} 个对话")
            
            if conversations:
                # 按最后修改时间排序
                sorted_conversations = sorted(
                    conversations, 
                    key=lambda x: x.get('last_modified', 0), 
                    reverse=True
                )
                
                for i, conv in enumerate(sorted_conversations):
                    logger.info(f"📄 [UI] 对话{i+1}: {conv['name']} (ID: {conv['id']})")
                
                self.update_conversation_combo(sorted_conversations)
                
                # 如果有对话，自动选择第一个并加载其内容
                if sorted_conversations:
                    first_conv = sorted_conversations[0]
                    logger.info(f"🎯 [UI] 自动选择第一个对话: {first_conv['name']}")
                    
                    self.conversation_manager.current_conversation_id = first_conv['id']
                    self.load_conversation(first_conv['id'])
                    logger.info(f"✅ [UI] 自动加载对话: {first_conv['name']}")
            else:
                logger.info("📭 [UI] 没有找到现有对话")
        except Exception as e:
            logger.error(f"❌ [UI] 加载现有对话失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
    
    def init_ui(self):
        """初始化UI"""
        # 设置页面背景为深色
        self.setStyleSheet("""
            IntegratedPlayPage {
                background-color: #2f3136;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        # 顶部工具栏
        toolbar = self.create_toolbar()
        layout.addWidget(toolbar)
        
        # 对话管理区域
        conv_management = self.create_conversation_management()
        layout.addWidget(conv_management)
        
        # 对话显示区域 - 使用新的气泡对话框组件
        self.chat_display = ChatDisplayWidget()
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
        mode_group.setStyleSheet("""
            QGroupBox {
                color: #dcddde;
                border: 1px solid #4f545c;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 15px;
                font-weight: bold;
                background-color: #36393f;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #5865f2;
                font-size: 14px;
            }
            QRadioButton {
                color: #dcddde;
                font-size: 13px;
                spacing: 8px;
                padding: 4px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid #4f545c;
                background-color: #40444b;
            }
            QRadioButton::indicator:checked {
                background-color: #5865f2;
                border-color: #5865f2;
            }
            QRadioButton::indicator:hover {
                border-color: #5865f2;
            }
            QRadioButton::indicator:disabled {
                background-color: #2f3136;
                border-color: #72767d;
            }
        """)
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
        group.setStyleSheet("""
            QGroupBox {
                color: #dcddde;
                border: 1px solid #4f545c;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 15px;
                font-weight: bold;
                background-color: #36393f;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #5865f2;
                font-size: 14px;
            }
            QLabel {
                color: #dcddde;
                font-size: 13px;
            }
        """)
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
        widget.setStyleSheet("""
            QWidget {
                background-color: #36393f;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton {
                background-color: #5865f2;
                color: #ffffff;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #4752c4;
            }
            QPushButton:pressed {
                background-color: #3c45a5;
            }
            QPushButton:disabled {
                background-color: #4f545c;
                color: #72767d;
            }
            QPushButton:checked {
                background-color: #e74c3c;
                color: #ffffff;
            }
            QPushButton:checked:hover {
                background-color: #c0392b;
            }
        """)
        layout = QVBoxLayout(widget)
        
        # 输入框
        self.input_text = QTextEdit()
        self.input_text.setMaximumHeight(100)
        self.input_text.setPlaceholderText("输入你的消息...")
        
        # 按钮行
        button_layout = QHBoxLayout()
        
        # 重新生成按钮
        self.regenerate_btn = QPushButton("重新生成")
        self.regenerate_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.regenerate_btn.setToolTip("重新生成最后一轮AI回复")
        
        # 删除模式切换按钮
        self.delete_mode_btn = QPushButton("删除模式")
        self.delete_mode_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.delete_mode_btn.setCheckable(True)
        self.delete_mode_btn.setToolTip("切换删除模式，可以选择删除任意对话")
        
        self.send_btn = QPushButton("发送")
        self.send_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        
        self.clear_btn = QPushButton("清空对话")
        self.clear_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))
        
        button_layout.addWidget(self.regenerate_btn)
        button_layout.addWidget(self.delete_mode_btn)
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
        self.regenerate_btn.clicked.connect(self.regenerate_last_response)
        self.delete_mode_btn.toggled.connect(self.toggle_delete_mode)
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
                # 删除对话时也清空知识图谱
                try:
                    # 获取主窗口实例
                    main_window = None
                    widget = self.parent()
                    while widget is not None:
                        if isinstance(widget, ChronoForgeMainWindow):
                            main_window = widget
                            break
                        widget = widget.parent()
                    
                    if main_window and hasattr(main_window, 'memory'):
                        main_window.memory.clear_all()
                        logger.info("✅ 删除对话时已清空知识图谱")
                        
                        # 刷新知识图谱页面显示
                        if hasattr(main_window, 'graph_page'):
                            main_window.graph_page.refresh_graph()
                            main_window.graph_page.update_entity_list()
                            main_window.graph_page.update_stats()
                            logger.info("✅ 知识图谱页面显示已刷新")
                    
                except Exception as e:
                    logger.warning(f"⚠️ 清空知识图谱失败: {e}")
                
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
        logger.info(f"🔄 [UI] 尝试切换对话: {conv_name}")
        
        if not conv_name or not conv_name.strip():
            logger.warning(f"❌ [UI] 对话名称为空，忽略切换")
            return
            
        # 根据名称找到对话ID
        found_conv_id = None
        for conv_id, conv_data in self.conversation_manager.conversations.items():
            if conv_data['name'] == conv_name:
                found_conv_id = conv_id
                break
        
        if found_conv_id:
            logger.info(f"✅ [UI] 找到对话ID: {found_conv_id}，开始切换")
            self.conversation_manager.switch_conversation(found_conv_id)
        else:
            logger.error(f"❌ [UI] 未找到对话: {conv_name}")
            logger.info(f"📋 [UI] 可用对话: {list(self.conversation_manager.conversations.keys())}")
    
    def update_conversation_combo(self, conversations: List[Dict]):
        """更新对话下拉框"""
        logger.info(f"🔄 [UI] 更新对话下拉框，{len(conversations)} 个对话")
        
        try:
            # 临时断开信号，避免在更新过程中触发切换
            self.conversation_combo.currentTextChanged.disconnect()
            logger.info("🔌 [UI] 临时断开下拉框信号")
        except Exception as e:
            logger.warning(f"⚠️ [UI] 断开信号失败（可能还没连接）: {e}")
        
        self.conversation_combo.clear()
        for conv in conversations:
            self.conversation_combo.addItem(conv['name'])
            logger.info(f"📝 [UI] 添加对话到下拉框: {conv['name']}")
        
        # 选中当前对话
        current_conv = self.conversation_manager.get_current_conversation()
        if current_conv:
            logger.info(f"🎯 [UI] 当前对话: {current_conv['name']}")
            index = self.conversation_combo.findText(current_conv['name'])
            if index >= 0:
                self.conversation_combo.setCurrentIndex(index)
                logger.info(f"✅ [UI] 设置下拉框选中索引: {index}")
            else:
                logger.error(f"❌ [UI] 在下拉框中找不到对话: {current_conv['name']}")
        else:
            logger.warning("⚠️ [UI] 没有当前对话可选中")
        
        # 重新连接信号
        self.conversation_combo.currentTextChanged.connect(self.switch_conversation)
        logger.info("🔌 [UI] 重新连接下拉框信号")
        
        logger.info(f"✅ [UI] 下拉框更新完成，当前项目: {self.conversation_combo.currentText()}")
    
    def load_conversation(self, conv_id: str):
        """加载对话内容"""
        logger.info(f"📖 [UI] 开始加载对话内容: {conv_id}")
        
        self.chat_display.clear_messages()
        
        if not conv_id:
            logger.warning("❌ [UI] 对话ID为空，无法加载")
            return
        
        conv = self.conversation_manager.get_current_conversation()
        if not conv:
            logger.warning(f"❌ [UI] 找不到对话: {conv_id}")
            return
        
        logger.info(f"📄 [UI] 找到对话: {conv['name']}")
        messages = conv.get('messages', [])
        logger.info(f"💬 [UI] 对话包含 {len(messages)} 条消息")
        
        # 显示消息历史
        loaded_messages = 0
        for msg in messages:
            if msg['role'] == 'user':
                self.append_message(msg['content'], is_user=True)
                loaded_messages += 1
            elif msg['role'] == 'assistant':
                self.append_message(msg['content'], is_user=False)
                loaded_messages += 1
            elif msg['role'] == 'system':
                self.append_message(f"系统: {msg['content']}", is_user=False)
                loaded_messages += 1
        
        logger.info(f"✅ [UI] 成功加载 {loaded_messages} 条消息到聊天界面")
    
    def append_message(self, message: str, is_user: bool = None, color: str = None):
        """添加消息到显示区域"""
        # 从消息前缀判断类型
        if is_user is None:
            if message.startswith("用户: "):
                is_user = True
                message = message[3:]  # 移除前缀
            elif message.startswith("助手: "):
                is_user = False
                message = message[3:]  # 移除前缀
            else:
                is_user = False
        
        self.chat_display.add_message(message, is_user, color)
    
    def show_loading_animation(self):
        """显示加载动画"""
        return self.chat_display.show_loading_animation()
    
    def remove_loading_animation(self):
        """移除加载动画"""
        self.chat_display.remove_loading_animation()
    
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
        self.append_message(message, is_user=True)
        
        # 添加到对话历史
        self.conversation_manager.add_message({
            'role': 'user',
            'content': message
        })
        
        # 显示动态加载状态
        self.loading_message_widget = self.show_loading_animation()
        
        # 发送到API
        self.process_message(message)
    
    def process_message(self, message: str):
        """处理消息（发送到API）"""
        if self.is_test_mode:
            self.process_test_message(message)
        else:
            self.process_tavern_message(message)
    
    def process_test_message(self, message: str):
        """处理测试模式消息 - 使用多线程避免UI阻塞"""
        try:
            # 清理之前的线程
            if hasattr(self, 'llm_worker') and self.llm_worker is not None:
                if self.llm_worker.isRunning():
                    logger.info("🔄 [UI] 停止之前的LLM工作线程")
                    self.llm_worker.terminate()
                    self.llm_worker.wait(1000)  # 等待最多1秒
                self.llm_worker.deleteLater()
            
            # 创建并启动工作线程
            self.llm_worker = LLMWorkerThread(self.engine, message)
            
            # 连接信号
            self.llm_worker.response_ready.connect(self.on_llm_response_ready)
            self.llm_worker.error_occurred.connect(self.on_llm_error)
            self.llm_worker.grag_data_ready.connect(self.on_grag_data_ready)
            self.llm_worker.finished.connect(self.on_llm_worker_finished)  # 新增：线程完成清理
            
            # 启动线程
            logger.info(f"🚀 [UI] 启动LLM工作线程处理消息: {message}")
            self.llm_worker.start()
            
        except Exception as e:
            logger.error(f"❌ [UI] 启动工作线程失败: {e}")
            self.remove_loading_animation()
            error_response = "抱歉，系统遇到了一些问题。让我们重新开始吧。"
            self.append_message(error_response, is_user=False)
    
    def on_grag_data_ready(self, grag_data: dict):
        """GRAG数据准备完成的回调"""
        logger.info(f"📊 [UI] 收到GRAG数据 - 实体: {grag_data['entities']}, 上下文长度: {grag_data['context_length']}")
    
    def on_llm_response_ready(self, llm_response: str):
        """LLM回复准备完成的回调"""
        try:
            logger.info(f"✅ [UI] 收到LLM回复，开始处理UI更新")
            
            # 移除加载动画并显示回复
            self.remove_loading_animation()
            self.append_message(llm_response, is_user=False)
            
            # 添加到对话历史
            self.conversation_manager.add_message({
                'role': 'assistant',
                'content': llm_response
            })
            
            # 处理LLM回复，更新知识图谱
            try:
                logger.info(f"🔄 [GRAG] 开始更新知识图谱...")
                update_results = self.engine.extract_updates_from_response(llm_response, self.llm_worker.message)
                self.engine.memory.add_conversation(self.llm_worker.message, llm_response)
                self.engine.memory.save_all_memory()
                
                logger.info(f"✅ [GRAG] 知识图谱更新成功: {update_results}")
                logger.info(f"📈 [GRAG] 更新统计: 节点更新={update_results.get('nodes_updated', 0)}, 边添加={update_results.get('edges_added', 0)}")
                
                # 实时刷新知识图谱页面显示
                try:
                    # 获取主窗口实例
                    main_window = None
                    widget = self.parent()
                    while widget is not None:
                        if isinstance(widget, ChronoForgeMainWindow):
                            main_window = widget
                            break
                        widget = widget.parent()
                    
                    if main_window and hasattr(main_window, 'graph_page'):
                        # 同步实体数据到JSON文件
                        main_window.memory.sync_entities_to_json()
                        # 刷新图谱显示
                        main_window.graph_page.refresh_graph()
                        main_window.graph_page.update_entity_list()
                        main_window.graph_page.update_stats()
                        logger.info("✅ [GRAG] 知识图谱页面已实时刷新")
                except Exception as refresh_error:
                    logger.warning(f"⚠️ [GRAG] 实时刷新知识图谱页面失败: {refresh_error}")
                    
            except Exception as e:
                logger.warning(f"⚠️ [GRAG] 知识图谱更新失败: {e}")
            
        except Exception as e:
            logger.error(f"❌ [UI] 处理LLM回复时出错: {e}")
    
    def on_llm_error(self, error_message: str):
        """LLM处理出错的回调"""
        logger.error(f"❌ [UI] LLM处理出错: {error_message}")
        self.remove_loading_animation()
        error_response = "抱歉，系统遇到了一些问题。让我们重新开始吧。"
        self.append_message(error_response, is_user=False)
    
    def on_llm_worker_finished(self):
        """LLM工作线程完成时的清理回调"""
        logger.info("🧹 [UI] LLM工作线程已完成，进行清理")
        if hasattr(self, 'llm_worker') and self.llm_worker is not None:
            self.llm_worker.deleteLater()
            self.llm_worker = None
    
    def process_tavern_message(self, message: str):
        """处理酒馆模式消息"""
        # TODO: 实现与SillyTavern的交互
        pass
    
    def regenerate_last_response(self):
        """重新生成最后一轮AI回复"""
        try:
            # 获取最后一条用户消息
            last_user_message = self.chat_display.get_last_user_message()
            if not last_user_message:
                QMessageBox.information(self, "提示", "没有找到可重新生成的对话")
                return
            
            # 删除最后一条AI回复
            if not self.chat_display.remove_last_ai_message():
                QMessageBox.information(self, "提示", "没有找到可删除的AI回复")
                return
            
            # 从对话历史中删除最后一条AI回复
            current_conv = self.conversation_manager.get_current_conversation()
            if current_conv and current_conv.get('messages'):
                # 从后往前找最后一条AI回复并删除
                for i in range(len(current_conv['messages']) - 1, -1, -1):
                    if current_conv['messages'][i]['role'] == 'assistant':
                        current_conv['messages'].pop(i)
                        self.conversation_manager._save_conversation(current_conv)
                        break
            
            # 重新发送用户消息（触发新的AI回复）
            self.process_message(last_user_message)
            
        except Exception as e:
            logger.error(f"重新生成回复失败: {e}")
            QMessageBox.warning(self, "错误", f"重新生成失败：{str(e)}")
    
    def toggle_delete_mode(self, enabled: bool):
        """切换删除模式"""
        if enabled:
            self.delete_mode_btn.setText("退出删除")
            self.delete_mode_btn.setStyleSheet("QPushButton { background-color: #e74c3c; }")
            self.chat_display.set_delete_mode(True)
            QMessageBox.information(self, "删除模式", "删除模式已开启\n点击任意对话气泡可删除该条消息")
        else:
            self.delete_mode_btn.setText("删除模式")
            self.delete_mode_btn.setStyleSheet("")
            self.chat_display.set_delete_mode(False)

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
            self.chat_display.clear_messages()
            
            # 清空对话时也清空知识图谱
            try:
                # 获取主窗口实例
                main_window = None
                widget = self.parent()
                while widget is not None:
                    if isinstance(widget, ChronoForgeMainWindow):
                        main_window = widget
                        break
                    widget = widget.parent()
                
                if main_window and hasattr(main_window, 'memory'):
                    main_window.memory.clear_all()
                    logger.info("✅ 清空对话时已清空知识图谱")
                    
                    # 刷新知识图谱页面显示
                    if hasattr(main_window, 'graph_page'):
                        main_window.graph_page.refresh_graph()
                        main_window.graph_page.update_entity_list()
                        main_window.graph_page.update_stats()
                        logger.info("✅ 知识图谱页面显示已刷新")
                
            except Exception as e:
                logger.warning(f"⚠️ 清空知识图谱失败: {e}")


class GraphPage(QWidget):
    """知识关系图谱页面"""
    
    def __init__(self, memory_system, parent=None):
        super().__init__(parent)
        self.memory = memory_system
        self.graph_file_path = Path(__file__).parent / "graph.html"
        self.current_selected_node = None
        
        # 创建HTML生成器
        self.html_generator = GraphHTMLGenerator()
        
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
        
        self.init_graph_btn = QPushButton("初始化图谱")
        self.init_graph_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        
        self.clear_graph_btn = QPushButton("清空图谱")
        self.clear_graph_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))
        
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.refresh_btn)
        header.addWidget(self.export_btn)
        header.addWidget(self.init_graph_btn)
        header.addWidget(self.clear_graph_btn)
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
        self.init_graph_btn.clicked.connect(self.initialize_graph)
        self.clear_graph_btn.clicked.connect(self.clear_graph)
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
            # 重新加载实体和关系到知识图谱（确保同步，现在包含关系）
            self.memory.reload_entities_from_json()
            
            # 更新UI显示
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
            
            # 获取知识图谱中的真实关系
            graph = self.memory.knowledge_graph.graph
            for source, target, attrs in graph.edges(data=True):
                relationship_type = attrs.get('relationship', 'related_to')
                links.append({
                    'source': source,
                    'target': target,
                    'relation': relationship_type
                })
            
            logger.info(f"从知识图谱获取了 {len(links)} 个关系连接")
            
            # 将数据转换为JSON字符串
            nodes_json = json.dumps(nodes, ensure_ascii=False)
            links_json = json.dumps(links, ensure_ascii=False)
            
            # 使用HTML生成器生成文件
            self.html_generator.generate_graph_html(nodes_json, links_json, self.graph_file_path)
                
        except Exception as e:
            logger.error(f"生成图谱HTML失败: {e}")
            logger.error(f"错误详情: {traceback.format_exc()}")
            # 如果失败，使用HTML生成器的备用方案
            self.html_generator._generate_fallback_html(self.graph_file_path)
    
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
        """获取所有实体（从知识图谱内存状态获取）"""
        try:
            entities = []
            
            # 直接从知识图谱内存中获取数据
            for node_id, attrs in self.memory.knowledge_graph.graph.nodes(data=True):
                entity = {
                    'name': node_id,
                    'type': attrs.get('type', 'concept'),
                    'description': attrs.get('description', ''),
                    'created_time': attrs.get('created_time', time.time()),
                    'last_modified': attrs.get('last_modified', time.time()),
                    'attributes': {}
                }
                
                # 添加动态属性，排除系统属性
                excluded_keys = {'type', 'description', 'created_time', 'last_modified'}
                for key, value in attrs.items():
                    if key not in excluded_keys:
                        entity['attributes'][key] = value
                
                entities.append(entity)
            
            logger.info(f"📊 从知识图谱内存获取 {len(entities)} 个实体")
            return entities
            
        except Exception as e:
            logger.error(f"从知识图谱获取实体失败: {e}")
            return []
    
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
            {"name": "克罗诺", "type": "character"},
            {"name": "利恩王国", "type": "location"},
            {"name": "传送装置", "type": "item"},
            {"name": "千年祭", "type": "event"},
            {"name": "玛尔", "type": "character"},
            {"name": "时空之门", "type": "location"},
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
        # 使用HTML生成器生成备用HTML
        self.html_generator._generate_fallback_html(self.graph_file_path)
    
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
        """获取所有实体（从知识图谱内存状态获取）"""
        try:
            entities = []
            
            # 直接从知识图谱内存中获取数据
            for node_id, attrs in self.memory.knowledge_graph.graph.nodes(data=True):
                entity = {
                    'name': node_id,
                    'type': attrs.get('type', 'concept'),
                    'description': attrs.get('description', ''),
                    'created_time': attrs.get('created_time', time.time()),
                    'last_modified': attrs.get('last_modified', time.time()),
                    'attributes': {}
                }
                
                # 添加动态属性，排除系统属性
                excluded_keys = {'type', 'description', 'created_time', 'last_modified'}
                for key, value in attrs.items():
                    if key not in excluded_keys:
                        entity['attributes'][key] = value
                
                entities.append(entity)
            
            logger.info(f"📊 从知识图谱内存获取 {len(entities)} 个实体")
            return entities
            
        except Exception as e:
            logger.error(f"从知识图谱获取实体失败: {e}")
            return []
    
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
            {"name": "克罗诺", "type": "character"},
            {"name": "利恩王国", "type": "location"},
            {"name": "传送装置", "type": "item"},
            {"name": "千年祭", "type": "event"},
            {"name": "玛尔", "type": "character"},
            {"name": "时空之门", "type": "location"},
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
                
                # 构建属性详情
                attributes = selected_entity.get('attributes', {})
                if attributes:
                    attr_lines = []
                    for key, value in attributes.items():
                        attr_lines.append(f"  • {key}: {value}")
                    attr_text = "\n".join(attr_lines)
                else:
                    attr_text = "  暂无属性"
                
                detail_text = f"""节点信息:
名称: {selected_entity['name']}
类型: {selected_entity['type']}
描述: {selected_entity.get('description', '暂无描述')}
创建时间: {created_time}
属性:
{attr_text}"""
                
            else:
                # 备用显示
                detail_text = f"""节点信息:
名称: {entity_display_name}
类型: {entity_type}
创建时间: 未知
描述: 暂无描述
属性: 暂无数据"""
            
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
                    
                    # 找到并更新对应的实体
                    entity_updated = False
                    for i, entity in enumerate(all_entities):
                        if entity['name'] == entity_name and entity['type'] == entity_type:
                            # 更新找到的实体
                            all_entities[i] = current_entity
                            entity_updated = True
                            logger.info(f"找到并更新实体: {entity_name} -> {new_name}")
                            break
                    
                    if not entity_updated:
                        logger.warning(f"未找到要更新的实体: {entity_name} ({entity_type})")
                        QMessageBox.warning(dialog, "更新失败", f"未找到要更新的实体: {entity_name}")
                        return
                    
                    self.save_entities(all_entities)
                    logger.info(f"实体更新成功: {new_name} (类型: {type_combo.currentText()})")
                    
                    # 同步更新知识图谱中的节点
                    try:
                        # 如果名称改变了，需要先删除旧节点，再创建新节点
                        if new_name != entity_name:
                            # 删除旧节点
                            if self.memory.knowledge_graph.graph.has_node(entity_name):
                                self.memory.knowledge_graph.graph.remove_node(entity_name)
                                logger.info(f"删除旧节点: {entity_name}")
                        
                        # 创建或更新新节点
                        self.memory.knowledge_graph.add_or_update_node(
                            new_name, 
                            current_entity['type'], 
                            description=current_entity['description'],
                            **current_entity['attributes']
                        )
                        logger.info(f"同步更新知识图谱节点成功: {new_name}")
                    except Exception as e:
                        logger.warning(f"同步知识图谱失败: {e}")
                
                # 更新界面
                self.update_entity_list()
                self.update_stats()
                self.refresh_graph()  # 刷新图谱显示
                
                # 同步到知识图谱
                try:
                    # 获取主窗口实例
                    main_window = None
                    widget = self.parent()
                    while widget is not None:
                        if isinstance(widget, ChronoForgeMainWindow):
                            main_window = widget
                            break
                        widget = widget.parent()
                    
                    if main_window and hasattr(main_window, 'memory'):
                        # 重新加载实体到知识图谱
                        main_window.memory.reload_entities_from_json()
                        logger.info("✅ 实体修改已同步到知识图谱")
                except Exception as e:
                    logger.warning(f"⚠️ 同步到知识图谱失败: {e}")
                
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
    
    def clear_graph(self):
        """清空知识图谱"""
        reply = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空当前的知识图谱吗？\n\n此操作将删除所有实体和关系，无法撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # 清空内存中的知识图谱
                self.memory.clear_all()
                
                # 刷新显示
                self.refresh_graph()
                
                # 更新统计信息
                self.update_stats()
                
                QMessageBox.information(self, "清空完成", "知识图谱已成功清空。")
                logger.info("知识图谱已清空")
                
            except Exception as e:
                logger.error(f"清空知识图谱失败: {e}")
                QMessageBox.warning(self, "清空失败", f"清空知识图谱时出现错误：\n{str(e)}")
    
    def initialize_graph(self):
        """初始化知识图谱"""
        reply = QMessageBox.question(
            self,
            "初始化知识图谱",
            "是否要创建默认的游戏开局？\n\n这将清空现有图谱并创建新的世界设定。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.Yes:
            self.create_default_scenario_for_graph()
    
    def create_default_scenario_for_graph(self):
        """为知识图谱创建默认场景（不依赖对话ID）"""
        try:
            # 使用主窗口的方法创建默认开局
            main_window = None
            widget = self.parent()
            while widget is not None:
                if isinstance(widget, ChronoForgeMainWindow):
                    main_window = widget
                    break
                widget = widget.parent()
            
            if main_window:
                # 先清空现有图谱
                self.memory.clear_all()
                
                # 创建默认开局
                main_window.create_default_game_scenario("manual_init")
                
                # 立即刷新图谱页面显示
                self.refresh_graph()
                self.update_entity_list() 
                self.update_stats()
                logger.info("✅ 知识图谱初始化完成，页面已刷新")
            else:
                QMessageBox.warning(self, "初始化失败", "无法找到主窗口实例。")
                
        except Exception as e:
            logger.error(f"初始化知识图谱失败: {e}")
            QMessageBox.warning(self, "初始化失败", f"初始化知识图谱时出现错误：\n{str(e)}")
    
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
        
        # 初始化管理器
        self.init_managers()
        
        # 启动API服务器
        self.start_api_server()
        
        # 初始化UI
        self.init_ui()
        
        # 设置窗口属性
        WindowManager.setup_window(self)
    
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
            self.cleanup_manager = ResourceCleanupManager(self)
            
            logger.info("管理器组件初始化完成")
            
        except Exception as e:
            logger.error(f"管理器初始化失败: {e}")
            QMessageBox.critical(self, "初始化错误", f"无法初始化管理器组件：\n{e}")
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
        
        # 设置对话和知识图谱的联动
        self.setup_cross_page_connections()
    
    def setup_cross_page_connections(self):
        """设置页面间的联动连接"""
        # 当对话切换时，刷新知识图谱
        self.play_page.conversation_manager.conversation_changed.connect(
            self.on_conversation_changed
        )
    
    def on_conversation_changed(self, conv_id: str):
        """处理对话切换事件"""
        logger.info(f"对话切换到: {conv_id}")
        
        # 如果conv_id为空，说明没有剩余对话
        if not conv_id:
            logger.info("没有剩余对话，保持当前状态")
            return
        
        # 获取对话信息
        conv = self.play_page.conversation_manager.conversations.get(conv_id)
        if not conv:
            logger.warning(f"对话 {conv_id} 不存在")
            return
        
        # 检查对话是否有消息内容
        messages = conv.get('messages', [])
        
        if not messages:
            # 新对话或空对话 - 询问是否创建默认开局
            logger.info("这是一个空对话，询问是否创建默认开局")
            self.prompt_initialize_knowledge_graph(conv_id)
        else:
            # 有内容的对话 - 不做任何操作，保持当前知识图谱
            logger.info("切换到有内容的对话，保持当前知识图谱状态")
    
    def load_conversation_knowledge_graph(self, conv_id: str) -> bool:
        """加载对话相关的知识图谱 - 暂时简化实现"""
        # TODO: 未来可以实现真正的对话-图谱关联机制
        # 现在先简化，只在真正需要时才处理
        return True  # 默认返回True，表示加载成功
    
    def prompt_initialize_knowledge_graph(self, conv_id: str):
        """提示用户初始化知识图谱"""
        # 防止重复调用的标志
        if hasattr(self, '_initializing_knowledge_graph') and self._initializing_knowledge_graph:
            logger.info("知识图谱正在初始化中，跳过重复调用")
            return
        
        try:
            self._initializing_knowledge_graph = True
            
            # 获取对话名称以便更好地提示用户
            conv = self.play_page.conversation_manager.conversations.get(conv_id)
            conv_name = conv.get('name', '当前对话') if conv else '当前对话'
            
            reply = QMessageBox.question(
                self, 
                "知识图谱初始化", 
                f"对话 \"{conv_name}\" 还没有开始。\n\n是否要创建默认的奇幻游戏开局来开始你的冒险？\n\n点击\"否\"将保持当前知识图谱状态。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.Yes:
                self.create_default_game_scenario(conv_id)
        finally:
            self._initializing_knowledge_graph = False
    
    def create_default_game_scenario(self, conv_id: str):
        """为对话创建默认游戏开局"""
        try:
            logger.info(f"为对话 {conv_id} 创建默认游戏开局")
            
            # 使用场景管理器创建超时空之轮场景
            opening_story, entity_count, relationship_count = self.scenario_manager.create_chrono_trigger_scenario()
            
            # 刷新图谱显示
            self.graph_page.refresh_graph()
            self.graph_page.update_entity_list()
            self.graph_page.update_stats()
            logger.info("✅ 知识图谱页面已刷新")
            
            # 在聊天界面显示开场故事
            self.play_page.chat_display.add_message(opening_story, False)  # False表示不是用户消息
            
            # 将开场故事保存到对话历史中
            self.play_page.conversation_manager.add_message({
                'role': 'assistant',
                'content': opening_story
            })
            
            # 显示成功消息
            self.scenario_manager.show_scenario_success_message(self, entity_count, relationship_count)
            
        except Exception as e:
            logger.error(f"创建默认游戏开局失败: {e}")
            self.scenario_manager.show_scenario_error_message(self, e)
    
    
    def closeEvent(self, event):
        """关闭事件处理"""
        success = self.cleanup_manager.cleanup_all_resources()
        if success:
            event.accept()
        else:
            event.accept()  # 即使出错也要关闭


def main():
    """主函数"""
    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("ChronoForge")
    app.setApplicationVersion("1.0.0")
    
    # 设置深色主题
    WindowManager.apply_dark_theme(app)
    
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