"""
EchoGraph 主UI程序
智能角色扮演助手 - 集成对话系统和关系图谱
"""
from src.graph.node_types import NODE_TYPES, TYPE_IDS, TYPE_LABELS, normalize_type, display_name
from src.ui.graph_temp_files import graph_page_path, tavern_placeholder_path, cleanup_stale_graph_pages
import sys
import os

# Capture only variables inherited from the launcher, before imports load .env.
_EXTERNAL_UI_THEME = os.environ.get("UI_THEME")

import time
import traceback
import re
from html import escape
import subprocess
import json
import requests
import threading
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QPushButton, QCheckBox, QTabWidget,
    QMessageBox, QSplitter, QListWidget, QListWidgetItem, QLabel, QTextEdit,
    QGroupBox, QComboBox, QInputDialog, QStyle, QDialog, QFileDialog,
    QRadioButton, QButtonGroup, QScrollArea, QFrame, QStyledItemDelegate
)
from PySide6.QtCore import Qt, QObject, Signal as pyqtSignal, QUrl, Slot, QTimer, QPropertyAnimation, QRect, QThread, QEvent
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtGui import QIcon, QFont, QColor, QIntValidator, QTextCursor, QPainter, QPen, QBrush
from dotenv import dotenv_values, set_key
from loguru import logger

ATTENTION_CONFIG = {
    'collective_weight': 0.6,
    'holistic_weight': 0.4,
    'importance_threshold': 0.3,
    'max_context_entities': 15,
}

sys.path.append(str(Path(__file__).parent))
from src.memory import GRAGMemory

# 导入重构后的组件
from src.ui.workers.llm_worker import LLMWorkerThread
from src.ui.managers.scenario_manager import ScenarioManager
from src.ui.managers.window_manager import WindowManager
from src.ui import theme
from src.ui.value_unit_input import UnitSpec, ValueUnitInput
from src.ui.managers.resource_cleanup_manager import ResourceCleanupManager
# 导入酒馆连接器
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
        self.color = color
        self.text_color = theme.current()["TEXT_PRIMARY"]
        self.border_color = theme.current()["BORDER"]
        self.setProperty("role", "chatRow")
        self.setup_ui()

    def set_delete_mode(self, enabled: bool):
        """设置删除模式"""
        self.delete_mode_enabled = enabled
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self.message_label.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self.message_label.setProperty("deleteMode", enabled)
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)

    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if self.delete_mode_enabled and event.button() == Qt.LeftButton:
            self.message_clicked.emit(self)
        super().mousePressEvent(event)

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)

        # 创建消息标签
        message_label = QLabel(self.message)
        self.message_label = message_label
        # Preserve supplied rich text and give ordinary paragraphs compact spacing.
        if re.search(r"<[A-Za-z][^>]*>", self.message):
            content = self.message
        else:
            paragraphs = re.split(r"\n\s*\n", self.message)
            content = "".join(
                f'<p style="margin:0 0 8px 0; line-height:155%">{escape(paragraph).replace(chr(10), "<br>")}</p>'
                for paragraph in paragraphs
            )
        message_label.setText(f'<div style="font-size:14px; line-height:155%">{content}</div>')
        message_label.setWordWrap(True)

        message_label.setProperty("role", "userBubble" if self.is_user else "aiBubble")
        message_label.setMaximumWidth(720 if not self.is_user else 560)
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
        self.setProperty("role", "loadingRow")
        self.dots_count = 1
        self.max_dots = 6
        self.setup_ui()

        # 设置定时器来更新动画
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_animation)
        animation_interval = int(os.getenv("ANIMATION_INTERVAL", "500"))
        self.timer.start(animation_interval)  # 从配置读取动画间隔

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)

        self.message_label = QLabel("助手正在思考...")
        self.message_label.setProperty("role", "loadingBubble")


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
    message_deleted = pyqtSignal(int)  # 删除消息后发出其在当前对话中的索引

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

        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(8)
        container_layout.setContentsMargins(24, 8, 24, 8)

        # 添加消息布局
        reading_column = QWidget()
        reading_layout = QVBoxLayout(reading_column)
        reading_layout.setContentsMargins(0, 0, 0, 0)
        reading_layout.addLayout(self.messages_layout)
        container_layout.addWidget(reading_column)
        container_layout.addStretch()  # 推到顶部

        self.setWidget(container)

        # 设置样式 - 现代深色聊天背景（类似Discord/Slack）


    def add_message(self, message: str, is_user: bool, color: str = None):
        # 限制消息历史大小，防止内存泄漏
        MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "1000"))  # 从配置读取最大消息数

        # 如果超过限制，删除最旧的消息
        if len(self.message_widgets) >= MAX_MESSAGES:
            old_msg_info = self.message_widgets.pop(0)
            old_widget = old_msg_info['widget']
            self.messages_layout.removeWidget(old_widget)
            old_widget.deleteLater()
            logger.debug(f"🧹 [UI] 删除旧消息以防止内存泄漏，当前消息数: {len(self.message_widgets)}")

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
                    self.message_deleted.emit(i)

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
from src.core.llm_client import LLMClient
from src.core.grag_update_agent import GRAGUpdateAgent

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
            if self.graph_page.tavern_mode and (
                not self.graph_page.tavern_session_id or self.graph_page.showing_tavern_placeholder
            ):
                raise RuntimeError("酒馆会话或图谱暂不可用，请连接会话后刷新图谱。")
            logger.info(f"通过WebChannel编辑节点: {entity_name} ({entity_type})")
            self.graph_page.edit_node_with_python_dialog(entity_name, entity_type)
        except Exception as e:
            logger.exception(f"WebChannel编辑节点失败: {e}")
            QMessageBox.warning(self.graph_page, "编辑节点失败", str(e))

    @Slot()
    def refreshGraph(self):
        self.graph_page.refresh_graph()

    @Slot(str)
    def saveLayout(self, positions_json):
        self.graph_page.save_graph_layout(json.loads(positions_json))

    @Slot(str, str, str)
    def createRelation(self, source_name, target_name, relation_type):
        self.graph_page.mutate_relationship("create", source_name, target_name, relation_type)

    @Slot(str, str, str)
    def createRelationship(self, source_name, target_name, relation_type):
        self.createRelation(source_name, target_name, relation_type)

    @Slot(str, str, str)
    def updateRelationship(self, source_name, target_name, relation_type):
        self.graph_page.mutate_relationship("update", source_name, target_name, relation_type)

    @Slot(str, str)
    def deleteRelationship(self, source_name, target_name):
        self.graph_page.mutate_relationship("delete", source_name, target_name)

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
            message['timestamp'] = time.time()
            conv['messages'].append(message)
            conv['last_modified'] = time.time()
            self._save_conversation(conv)

    def delete_message_at(self, index: int) -> bool:
        """删除当前对话指定索引的消息"""
        conv = self.get_current_conversation()
        if not conv:
            return False
        messages = conv.get('messages', [])
        if index < 0 or index >= len(messages):
            return False
        messages.pop(index)
        conv['last_modified'] = time.time()
        self._save_conversation(conv)
        return True

    def clear_current_conversation(self):
        """清空当前对话的消息"""
        conv = self.get_current_conversation()
        if conv:
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
        self.switching_modes = False  # 添加模式切换标志

        # 初始化酒馆管理器

        # 对话管理器
        self.conversation_manager = ConversationManager(Path(__file__).parent / "data" / "local_conversations")

        self.init_ui()
        self.connect_signals()

        # 设置初始状态 - 本地模式默认激活
        self.update_status_display("本地模式已选择")
        self.is_connected_to_api = True
        # 设置初始按钮状态
        self.local_mode_radio.setEnabled(False)  # 当前选中的模式变灰
        self.tavern_mode_radio.setEnabled(True)

        # 初始化加载现有对话
        self.load_existing_conversations()

    def load_existing_conversations(self):
        """加载现有对话到下拉框"""
        try:
            logger.debug("📥 [UI] 开始加载现有对话...")

            # 触发对话管理器加载对话
            self.conversation_manager.load_conversations()

            # 获取排序后的对话列表
            conversations = list(self.conversation_manager.conversations.values())
            logger.debug(f"📋 [UI] 找到 {len(conversations)} 个对话")

            if conversations:
                # 按最后修改时间排序
                sorted_conversations = sorted(
                    conversations,
                    key=lambda x: x.get('last_modified', 0),
                    reverse=True
                )

                for i, conv in enumerate(sorted_conversations):
                    logger.debug(f"📄 [UI] 对话{i+1}: {conv['name']} (ID: {conv['id']})")

                self.update_conversation_combo(sorted_conversations)

                # 如果有对话，自动选择第一个并加载其内容
                if sorted_conversations:
                    first_conv = sorted_conversations[0]
                    logger.debug(f"🎯 [UI] 自动选择第一个对话: {first_conv['name']}")

                    self.conversation_manager.current_conversation_id = first_conv['id']
                    self.load_conversation(first_conv['id'])
                    logger.debug(f"✅ [UI] 自动加载对话: {first_conv['name']}")
            else:
                logger.debug("📭 [UI] 没有找到现有对话")
        except Exception as e:
            logger.error(f"❌ [UI] 加载现有对话失败: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")

    def init_ui(self):
        """初始化UI"""
        # 设置页面背景为深色


        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

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
        layout.setContentsMargins(0, 0, 0, 0)

        # 模式选择组
        mode_group = QGroupBox("模式")
        mode_group.setProperty("variant", "flat")
        mode_group.setTitle("")

        mode_layout = QHBoxLayout(mode_group)
        mode_layout.setContentsMargins(0, 0, 0, 0)

        # 单选按钮组
        self.mode_button_group = QButtonGroup()

        self.local_mode_radio = QRadioButton("本地模式")
        self.tavern_mode_radio = QRadioButton("酒馆模式")

        # 默认选择本地模式
        self.local_mode_radio.setChecked(True)
        self.is_test_mode = True

        # 添加到按钮组
        self.mode_button_group.addButton(self.local_mode_radio, 0)
        self.mode_button_group.addButton(self.tavern_mode_radio, 1)

        mode_layout.addWidget(self.local_mode_radio)
        mode_layout.addWidget(self.tavern_mode_radio)

        # 连接状态指示器
        self.status_label = QLabel("本地模式已选择")
        self.status_label.setProperty("role", "status")
        self.status_dot = QLabel("●")
        self.status_dot.setProperty("role", "statusDot")
        self.status_dot.setProperty("status", "success")


        layout.addWidget(mode_group)
        layout.addStretch()
        layout.addWidget(self.status_dot)
        layout.addWidget(self.status_label)

        return toolbar

    def create_conversation_management(self) -> QWidget:
        """创建对话管理区域"""
        group = QGroupBox("对话管理")
        group.setProperty("variant", "flat")
        group.setTitle("")

        layout = QHBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)

        # 对话选择下拉框
        self.conversation_combo = QComboBox()
        self.conversation_combo.setMinimumWidth(200)

        # 对话管理按钮
        self.new_conv_btn = QPushButton("新建对话")

        self.delete_conv_btn = QPushButton("删除对话")
        self.delete_conv_btn.setProperty("variant", "danger")

        self.rename_conv_btn = QPushButton("重命名")
        self.rename_conv_btn.setProperty("variant", "ghost")

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

        # 重新生成按钮
        self.regenerate_btn = QPushButton("重新生成")
        self.regenerate_btn.setProperty("variant", "ghost")
        self.regenerate_btn.setToolTip("重新生成最后一轮AI回复")

        # 删除模式切换按钮
        self.delete_mode_btn = QPushButton("删除模式")
        self.delete_mode_btn.setProperty("variant", "danger")
        self.delete_mode_btn.setCheckable(True)
        self.delete_mode_btn.setToolTip("切换删除模式，可以选择删除任意对话")

        self.send_btn = QPushButton("发送")
        self.send_btn.setProperty("variant", "primary")

        self.clear_btn = QPushButton("清空对话")
        self.clear_btn.setProperty("variant", "danger")

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
        self.chat_display.message_deleted.connect(self.on_chat_message_deleted)
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

    def _restore_local_graph(self, main_window):
        if not main_window:
            return

        if hasattr(main_window, 'memory'):
            current_id = self.conversation_manager.current_conversation_id
            active_id = getattr(main_window, '_active_local_graph_conversation_id', None)
            if current_id and active_id and current_id != active_id:
                main_window._save_conversation_knowledge_graph(active_id)
                if main_window.load_conversation_knowledge_graph(current_id):
                    main_window._active_local_graph_conversation_id = current_id
            main_window.memory.reload_entities_from_json()
            logger.info("✅ 已恢复本地知识图谱数据")

        if hasattr(main_window, 'graph_page'):
            graph_page = main_window.graph_page
            if graph_page.tavern_mode or graph_page.showing_tavern_placeholder:
                graph_page.exit_tavern_mode(local_memory=main_window.memory)
            else:
                graph_page.refresh_graph()
            logger.info("📊 知识图谱页面已恢复本地显示")

    def on_mode_change(self, mode_id):
        """模式切换处理 - 重新设计的完整酒馆模式"""
        # 设置模式切换标志，防止自动初始化干扰
        main_window = None
        widget = self.parent()
        while widget is not None:
            if isinstance(widget, EchoGraphMainWindow):
                main_window = widget
                break
            widget = widget.parent()

        if main_window:
            main_window._mode_switch_generation += 1
            generation = main_window._mode_switch_generation
            main_window.switching_modes = True
            logger.info("🔄 设置模式切换标志，暂停对话自动初始化")

        try:
            if mode_id == 0:  # 本地模式
                self.is_test_mode = True
                self.tavern_mode_radio.setEnabled(True)
                self.local_mode_radio.setEnabled(False)

                self._restore_local_graph(main_window)

                # 无条件关闭后端酒馆模式并快速清理，确保彻底回到本地隔离
                backend_errors = []
                try:
                    response = requests.post(f"{self.api_base_url}/system/tavern_mode", json={"active": False}, timeout=5)
                    if not response.ok:
                        raise RuntimeError(f"HTTP {response.status_code}")
                except Exception as exc:
                    backend_errors.append(f"mode gate: {exc}")
                try:
                    response = requests.get(f"{self.api_base_url}/system/quick_reset", timeout=5)
                    if not response.ok:
                        raise RuntimeError(f"HTTP {response.status_code}")
                except Exception as exc:
                    backend_errors.append(f"quick reset: {exc}")
                try:
                    self._stop_tavern_session_polling()
                except Exception:
                    pass


                # 启用对话界面
                self.enable_chat_interface(True)

                if backend_errors:
                    warning = "; ".join(backend_errors)
                    self.update_status_display(f"Local mode selected; backend reset failed: {warning}")
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "Backend reset failed", warning)
                else:
                    self.update_status_display("本地模式已选择")
                self.is_connected_to_api = True

            elif mode_id == 1:  # 酒馆模式
                self.is_test_mode = False
                self.local_mode_radio.setEnabled(True)
                self.tavern_mode_radio.setEnabled(False)

                # 开始酒馆模式切换流程
                self.update_status_display("正在切换到酒馆模式...")
                # 确保后端服务器存活；仅检查，不在此处自启，避免端口竞争
                try:
                    r = requests.get(f"{self.api_base_url}/system/liveness", timeout=5)
                    if not r.ok:
                        self.update_status_display("会话初始化失败：后端未启动")
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "EchoGraph", "会话初始化失败: 后端无法访问，请先启动Python服务器。")

                        # 确保后端处于本地隔离（关闭酒馆模式 + 快速清理）
                        try:
                            requests.post(f"{self.api_base_url}/system/tavern_mode", json={"active": False}, timeout=3)
                            requests.get(f"{self.api_base_url}/system/quick_reset", timeout=3)
                            logger.info("🛑 已在回退时关闭后端酒馆模式并请求 quick_reset")
                        except Exception as gate_err:
                            logger.warning(f"⚠️ 回退关闭 tavern_mode/quick_reset 失败: {gate_err}")

                        # 回退到本地模式（UI 状态）
                        self.local_mode_radio.setChecked(True)
                        self.tavern_mode_radio.setChecked(False)
                        self.is_test_mode = True
                        self.local_mode_radio.setEnabled(False)
                        self.tavern_mode_radio.setEnabled(True)
                        self._restore_local_graph(main_window)
                        return

                    # 启用后端酒馆模式开关（允许插件/WS访问）
                    gate_response = requests.post(f"{self.api_base_url}/system/tavern_mode", json={"active": True}, timeout=5)
                    if not gate_response.ok:
                        raise RuntimeError(f"Tavern mode gate returned HTTP {gate_response.status_code}")
                    logger.info("✅ 已开启后端酒馆模式（允许插件访问）")
                except Exception as gate_err:
                    logger.error(f"Tavern mode gate failed: {gate_err}")
                    self.auto_switch_to_local_mode(str(gate_err))
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "Tavern mode", f"Cannot enable Tavern mode: {gate_err}")
                    return

                QApplication.processEvents()

                # 禁用对话界面（切换到酒馆模式后，对话由酒馆控制）
                self.enable_chat_interface(False)

                # 不再阻塞等待插件提交角色数据；直接进入“酒馆模式占位”界面，由插件与后端自行完成初始化
                try:
                    self.update_status_display("酒馆模式已启用（等待SillyTavern角色提交）")
                    if main_window and hasattr(main_window, 'graph_page'):
                        # 显示占位信息；session_id 暂定为 pending，统计为空
                        placeholder_stats = {"graph_nodes": 0, "graph_edges": 0}
                        try:
                            main_window.graph_page._show_tavern_mode_placeholder("pending", placeholder_stats)
                        except Exception as e:
                            logger.warning(f"⚠️ 显示酒馆占位页面失败: {e}")
                except Exception as e:
                    logger.warning(f"⚠️ 进入酒馆占位界面失败: {e}")

        finally:
            # 使用QTimer延迟重置标志，确保所有相关的信号处理完成
            if main_window:
                def reset_switching_flag():
                    if main_window._mode_switch_generation == generation:
                        main_window.switching_modes = False
                # 酒馆模式启动会话监控；本地模式确保停止监控
                try:
                    if self.is_test_mode:
                        self._stop_tavern_session_polling()
                    else:
                        self._start_tavern_session_polling()
                except Exception as _e:
                    logger.warning(f"⚠️ 会话监控状态切换失败: {_e}")

                    logger.info("✅ 重置模式切换标志，恢复对话自动初始化")

                QTimer.singleShot(2000, reset_switching_flag)  # 2秒后重置标志

    def enable_chat_interface(self, enabled: bool):

        """启用/禁用对话界面"""
        try:
            # 禁用/启用用户输入框
            if hasattr(self, 'input_text'):
                self.input_text.setEnabled(enabled)
                if not enabled:
                    self.input_text.setPlaceholderText("酒馆模式下，请在SillyTavern中进行对话")
                else:
                    self.input_text.setPlaceholderText("输入你的消息...")

            # 禁用/启用发送按钮
            if hasattr(self, 'send_btn'):
                self.send_btn.setEnabled(enabled)

            # 禁用/启用其他对话相关控件
            controls = ['clear_btn', 'new_conv_btn', 'delete_conv_btn', 'rename_conv_btn', 'regenerate_btn', 'delete_mode_btn', 'conversation_combo']
            for ctrl_name in controls:
                if hasattr(self, ctrl_name):
                    ctrl = getattr(self, ctrl_name)
                    ctrl.setEnabled(enabled)

            logger.info(f"💬 对话界面已{'启用' if enabled else '禁用'}")

        except Exception as e:
            logger.error(f"切换对话界面状态失败: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")

    def _start_tavern_session_polling(self):
        """
        在酒馆模式下持续轮询后端会话状态，并在会话变更时刷新图谱。
        """
        try:
            self._stop_tavern_session_polling()
        except Exception:
            pass
        self._tavern_session_poll_timer = QTimer(self)
        poll_interval = int(os.getenv("POLL_INTERVAL", "3"))
        self._tavern_session_poll_timer.setInterval(max(1, poll_interval) * 1000)
        self._last_polled_tavern_session_id = None

        def _tick():
            if self.is_test_mode:
                self._stop_tavern_session_polling()
                return

            try:
                r = requests.get(f"{self.api_base_url}/tavern/current_session", timeout=poll_interval)
                if self.is_test_mode:
                    return
                if r.status_code == 200:
                    data = r.json()
                    if data.get("has_session") and data.get("session_id"):
                        session_id = data.get("session_id")
                        if self._last_polled_tavern_session_id != session_id:
                            self._last_polled_tavern_session_id = session_id
                            try:
                                # 找到主窗口
                                main_window = None
                                w = self.parent()
                                while w is not None:
                                    if hasattr(w, 'graph_page'):
                                        main_window = w
                                        break
                                    w = w.parent()
                                if main_window and hasattr(main_window, 'graph_page'):
                                    main_window.graph_page.enter_tavern_mode(session_id)
                                    main_window.graph_page.refresh_from_api_server(session_id)
                            except Exception as ui_err:
                                logger.warning(f"⚠️ 切换图谱为酒馆会话失败: {ui_err}")
                        elif getattr(self.window(), 'graph_page', None):
                            self.window().graph_page.refresh_from_api_server(session_id)
                        state = data.get("initialization_status")
                        reason = data.get("initialization_reason", "")
                        if state == "failed":
                            status_text = f"图谱初始化失败：{reason or '未知原因'}"
                        elif state == "partial":
                            status_text = f"图谱部分完成：{reason or '部分世界书条目未提取'}"
                        elif data.get("graph_nodes", 0) == 0:
                            status_text = (f"图谱为空：{reason or '角色卡未提取到实体'}"
                                           if state == "completed" else "正在从角色卡生成图谱…")
                        else:
                            status_text = f"图谱已就绪：{data['graph_nodes']} 个实体，{data.get('graph_edges', 0)} 条关系"
                        if getattr(self, "_last_polled_tavern_status", None) != status_text:
                            logger.info(f"📊 酒馆图谱状态：{status_text}")
                            self._last_polled_tavern_status = status_text
                        self.update_status_display(status_text)
                    else:
                        # 没有活跃会话时保留监控，等待后续恢复/重连
                        if self._last_polled_tavern_session_id is not None:
                            logger.warning("⚠️ 酒馆活跃会话丢失，等待插件重连...")
                            self.update_status_display("酒馆会话断开，等待重连...")
                            self._last_polled_tavern_session_id = None
                            main_window = self.window()
                            if hasattr(main_window, 'graph_page'):
                                main_window.graph_page._show_tavern_mode_placeholder("pending", {"graph_nodes": 0, "graph_edges": 0})
            except Exception as poll_err:
                logger.debug(f"轮询当前会话异常: {poll_err}")

        self._tavern_session_poll_timer.timeout.connect(_tick)
        self._tavern_session_poll_timer.start()
        _tick()  # 立即执行一次，减少首次延迟

    def _stop_tavern_session_polling(self):
        t = getattr(self, "_tavern_session_poll_timer", None)
        if t:
            try:
                t.stop()
            except Exception:
                pass
            self._tavern_session_poll_timer = None
        self._last_polled_tavern_session_id = None

    def auto_switch_to_local_mode(self, reason: str):
        """自动切换到本地模式"""
        try:
            logger.info(f"🔄 自动切换到本地模式，原因: {reason}")

            # 切换单选按钮状态
            if hasattr(self, 'local_mode_radio') and hasattr(self, 'tavern_mode_radio'):
                self.local_mode_radio.setChecked(True)
                self.tavern_mode_radio.setChecked(False)

                # 更新按钮状态
                self.local_mode_radio.setEnabled(False)  # 当前选中的模式变灰
                self.tavern_mode_radio.setEnabled(True)

            # 设置测试模式标志
            self.is_test_mode = True

            # 关闭后端酒馆模式总开关，确保隔离（并快速清理）
            try:
                requests.post(f"{self.api_base_url}/system/tavern_mode", json={"active": False}, timeout=3)
                requests.get(f"{self.api_base_url}/system/quick_reset", timeout=3)
                logger.info("🛑 已关闭后端酒馆模式并请求 quick_reset")
            except Exception as gate_err:
                logger.warning(f"⚠️ 自动回退时关闭 tavern_mode/quick_reset 失败: {gate_err}")


            # 无论是否真正进入过酒馆模式，都强制恢复本地数据展示
            main_window = None
            widget = self.parent()
            while widget is not None:
                if isinstance(widget, EchoGraphMainWindow):
                    main_window = widget
                    break
                widget = widget.parent()

            if main_window:
                try:
                    self._restore_local_graph(main_window)
                except Exception as restore_error:
                    logger.warning(f"⚠️ 恢复本地图谱页面失败: {restore_error}")

            # 启用对话界面
            self.enable_chat_interface(True)

            # 更新状态显示
            self.update_status_display("本地模式已选择（自动切换）")
            self.is_connected_to_api = True

            logger.info(f"✅ 已自动切换到本地模式，原因: {reason}")

        except Exception as e:
            logger.error(f"❌ 自动切换到本地模式失败: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")

    def check_api_connection(self):
        """检查API连接状态"""
        if self.is_test_mode:
            # 本地模式不需要检查API
            self.is_connected_to_api = True
            self.update_status_display("本地模式已选择")
            return

        # 只有酒馆模式才检查API连接
        try:
            # 显示正在连接状态
            self.update_status_display("正在连接酒馆...")
            QApplication.processEvents()

            response = requests.get(f"{self.api_base_url}/system/liveness", timeout=5)
            if response.status_code == 200:
                self.is_connected_to_api = True
                self.update_status_display("酒馆服务在线")
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

        if any(word in status_text for word in ("失败", "错误", "异常", "断开", "未连接")):
            state = "danger"
        elif any(word in status_text for word in ("酒馆", "连接", "等待", "初始化", "切换")):
            state = "info"
        elif any(word in status_text for word in ("已选择", "已启用", "在线", "就绪")):
            state = "success"
        else:
            state = "idle"
        self.status_dot.setProperty("status", state)
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)

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
            f"确定要删除对话 \"{current_conv['name']}\"吗？此操作不可撤销。",
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
                        if isinstance(widget, EchoGraphMainWindow):
                            main_window = widget
                            break
                        widget = widget.parent()

                    if main_window and hasattr(main_window, 'memory'):
                        main_window.memory.clear_all()
                        logger.info("✅ 删除对话时已清空知识图谱")

                        # 刷新知识图谱页面显示
                        if hasattr(main_window, 'graph_page'):
                            main_window.graph_page.refresh_graph()  # 已包含更新实体列表和统计
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
        logger.debug(f"🔄 [UI] 尝试切换对话: {conv_name}")

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
            logger.debug(f"✅ [UI] 找到对话ID: {found_conv_id}，开始切换")
            self.conversation_manager.switch_conversation(found_conv_id)
        else:
            logger.error(f"❌ [UI] 未找到对话: {conv_name}")
            logger.debug(f"📋 [UI] 可用对话: {list(self.conversation_manager.conversations.keys())}")

    def update_conversation_combo(self, conversations: List[Dict]):
        """更新对话下拉框"""
        logger.debug(f"🔄 [UI] 更新对话下拉框，{len(conversations)} 个对话")

        try:
            # 临时断开信号，避免在更新过程中触发切换
            self.conversation_combo.currentTextChanged.disconnect()
            logger.debug("🔌 [UI] 临时断开下拉框信号")
        except Exception as e:
            logger.warning(f"⚠️ [UI] 断开信号失败（可能还没连接）: {e}")

        self.conversation_combo.clear()
        for conv in conversations:
            self.conversation_combo.addItem(conv['name'])
            logger.debug(f"📝 [UI] 添加对话到下拉框: {conv['name']}")

        # 选中当前对话
        current_conv = self.conversation_manager.get_current_conversation()
        if current_conv:
            logger.debug(f"🎯 [UI] 当前对话: {current_conv['name']}")
            index = self.conversation_combo.findText(current_conv['name'])
            if index >= 0:
                self.conversation_combo.setCurrentIndex(index)
                logger.debug(f"✅ [UI] 设置下拉框选中索引: {index}")
            else:
                logger.error(f"❌ [UI] 在下拉框中找不到对话: {current_conv['name']}")
        else:
            logger.warning("⚠️ [UI] 没有当前对话可选中")

        # 重新连接信号
        self.conversation_combo.currentTextChanged.connect(self.switch_conversation)
        logger.debug("🔌 [UI] 重新连接下拉框信号")

        logger.debug(f"✅ [UI] 下拉框更新完成，当前项目: {self.conversation_combo.currentText()}")

    def load_conversation(self, conv_id: str):
        """加载对话内容"""
        logger.debug(f"📖 [UI] 开始加载对话内容: {conv_id}")

        self.chat_display.clear_messages()

        if not conv_id:
            logger.warning("❌ [UI] 对话ID为空，无法加载")
            return

        conv = self.conversation_manager.get_current_conversation()
        if not conv:
            logger.warning(f"❌ [UI] 找不到对话: {conv_id}")
            return

        logger.debug(f"📄 [UI] 找到对话: {conv['name']}")
        messages = conv.get('messages', [])
        logger.debug(f"💬 [UI] 对话包含 {len(messages)} 条消息")

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

        logger.debug(f"✅ [UI] 成功加载 {loaded_messages} 条消息到聊天界面")
        self._sync_engine_hot_memory_from_current_conversation()

    def _sync_engine_hot_memory_from_current_conversation(self):
        """按当前对话重建热记忆，避免删除/切换后上下文继续引用旧消息。"""
        if not getattr(self, "is_test_mode", True):
            return
        if not self.engine or not hasattr(self.engine, "memory"):
            return

        conv = self.conversation_manager.get_current_conversation()
        if not conv:
            return

        messages = conv.get("messages", [])
        basic_memory = self.engine.memory.basic_memory
        basic_memory.conversation_history.clear()

        pending_user = None
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user":
                if pending_user is not None:
                    basic_memory.add_conversation(pending_user, "")
                pending_user = content
            elif role == "assistant":
                if pending_user is None:
                    continue
                basic_memory.add_conversation(pending_user, content)
                pending_user = None

        if pending_user is not None:
            basic_memory.add_conversation(pending_user, "")

        logger.debug(f"🧠 已重建热记忆: {len(basic_memory.conversation_history)} 条")

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
                    logger.debug("🔄 [UI] 停止之前的LLM工作线程")
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
            logger.debug(f"🚀 [UI] 启动LLM工作线程处理消息: {message}")
            self.llm_worker.start()

        except Exception as e:
            logger.error(f"❌ [UI] 启动工作线程失败: {e}")
            self.remove_loading_animation()
            error_response = "抱歉，系统遇到了一些问题。让我们重新开始吧。"
            self.append_message(error_response, is_user=False)

    def on_grag_data_ready(self, grag_data: dict):
        """GRAG数据准备完成的回调"""
        logger.debug(f"📊 [UI] 收到GRAG数据 - 实体: {grag_data['entities']}, 上下文长度: {grag_data['context_length']}")

    def on_llm_response_ready(self, llm_response: str):
        """LLM回复准备完成的回调"""
        try:
            logger.debug(f"✅ [UI] 收到LLM回复，开始处理UI更新")

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
                        if isinstance(widget, EchoGraphMainWindow):
                            main_window = widget
                            break
                        widget = widget.parent()

                    if main_window and hasattr(main_window, 'graph_page'):
                        # 重新加载实体数据到知识图谱（这一步已经在GameEngine中通过sync_entities_to_json完成了）
                        # 这里只需要重新加载UI的显示
                        main_window.memory.reload_entities_from_json()
                        # 刷新图谱显示
                        main_window.graph_page.refresh_graph()  # 已包含更新实体列表和统计
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
        logger.debug("🧹 [UI] LLM工作线程已完成，进行清理")
        if hasattr(self, 'llm_worker') and self.llm_worker is not None:
            self.llm_worker.deleteLater()
            self.llm_worker = None

    def process_tavern_message(self, message: str):
        """处理酒馆模式消息 - 通过HTTP API与酒馆插件交互"""
        if not self.is_connected_to_api:
            logger.warning("酒馆API未连接，无法处理消息")
            return None

        try:
            logger.info(f"🍺 [酒馆模式] 处理消息: {message[:100]}...")

            # 获取当前有效的酒馆会话ID
            session_id = None
            try:
                main_window = None
                widget = self.parent()
                while widget is not None:
                    if isinstance(widget, EchoGraphMainWindow):
                        main_window = widget
                        break
                    widget = widget.parent()
                if main_window and hasattr(main_window, 'graph_page') and getattr(main_window.graph_page, 'tavern_mode', False):
                    session_id = getattr(main_window.graph_page, 'tavern_session_id', None)
            except Exception as sid_err:
                logger.warning(f"获取酒馆会话ID失败: {sid_err}")

            if not session_id:
                logger.warning("酒馆模式会话ID未知，无法处理消息")
                return {'status': 'no_session'}

            # 发送到EchoGraph API服务器进行处理
            response = requests.post(
                f"{self.api_base_url}/tavern/process_message",
                json={
                    'message': message,
                    'session_id': session_id,  # 使用当前会话ID
                    'mode': 'tavern_integration',
                    'timestamp': time.time()
                },
                timeout=int(os.getenv("API_TIMEOUT", "15"))
            )

            if response.status_code == 200:
                data = response.json()
                enhanced_context = data.get('enhanced_context', '')
                nodes_updated = data.get('nodes_updated', 0)
                edges_added = data.get('edges_added', 0)

                if enhanced_context:
                    logger.info(f"✅ [酒馆模式] 消息处理成功 - 上下文长度: {len(enhanced_context)}, 节点更新: {nodes_updated}, 关系添加: {edges_added}")

                    # 更新本地UI显示
                    try:
                        # 获取主窗口实例并刷新知识图谱页面
                        main_window = None
                        widget = self.parent()
                        while widget is not None:
                            if isinstance(widget, EchoGraphMainWindow):
                                main_window = widget
                                break
                            widget = widget.parent()

                        if main_window and hasattr(main_window, 'graph_page'):
                            main_window.graph_page.refresh_graph()  # 已包含更新实体列表和统计
                            logger.info("📊 [酒馆模式] 知识图谱页面已实时更新")
                    except Exception as refresh_error:
                        logger.warning(f"⚠️ [酒馆模式] 刷新知识图谱页面失败: {refresh_error}")

                    return {
                        'enhanced_context': enhanced_context,
                        'stats': {
                            'nodes_updated': nodes_updated,
                            'edges_added': edges_added
                        },
                        'status': 'success'
                    }
                else:
                    logger.info("📝 [酒馆模式] 消息处理完成，但未生成增强上下文")
                    return {'status': 'no_enhancement'}
            else:
                error_text = response.text
                logger.error(f"❌ [酒馆模式] API调用失败: {response.status_code} - {error_text}")
                return {'status': 'api_error', 'error': f"HTTP {response.status_code}"}

        except requests.exceptions.Timeout:
            logger.error("⏱️ [酒馆模式] API调用超时")
            return {'status': 'timeout', 'error': 'API request timeout'}
        except Exception as e:
            logger.error(f"💥 [酒馆模式] 消息处理异常: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")
            return {'status': 'error', 'error': str(e)}

        return None

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

            self.chat_display.set_delete_mode(True)
            QMessageBox.information(self, "删除模式", "删除模式已开启\n点击任意对话气泡可删除该条消息")
        else:
            self.delete_mode_btn.setText("删除模式")

            self.chat_display.set_delete_mode(False)

    def on_chat_message_deleted(self, message_index: int):
        """同步删除当前对话中的消息，避免UI与存储不一致"""
        try:
            if self.conversation_manager.delete_message_at(message_index):
                self._sync_engine_hot_memory_from_current_conversation()
                logger.info(f"✅ 已同步删除对话历史消息，索引={message_index}")
            else:
                logger.warning(f"⚠️ 删除同步失败：无效索引 {message_index}")
        except Exception as e:
            logger.error(f"❌ 删除消息同步异常: {e}")

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
                    if isinstance(widget, EchoGraphMainWindow):
                        main_window = widget
                        break
                    widget = widget.parent()

                if main_window and hasattr(main_window, 'memory'):
                    main_window.memory.clear_all()
                    logger.info("✅ 清空对话时已清空知识图谱")

                    # 刷新知识图谱页面显示
                    if hasattr(main_window, 'graph_page'):
                        main_window.graph_page.refresh_graph()  # 已包含更新实体列表和统计
                        logger.info("✅ 知识图谱页面显示已刷新")

            except Exception as e:
                logger.warning(f"⚠️ 清空知识图谱失败: {e}")


class EntityListDelegate(QStyledItemDelegate):
    """Draw a type dot while retaining the list item's lookup text."""

    def paint(self, painter, option, index):
        from PySide6.QtWidgets import QStyleOptionViewItem
        item_option = QStyleOptionViewItem(option)
        self.initStyleOption(item_option, index)
        raw = item_option.text
        entity = index.data(Qt.UserRole)
        node_type = entity.get("type", "other") if isinstance(entity, dict) else "other"
        if not isinstance(entity, dict) and raw.startswith("[") and "] " in raw:
            node_type, item_option.text = raw[1:].split("] ", 1)
        elif not isinstance(entity, dict) and raw.startswith("【") and "】" in raw:
            node_type, item_option.text = raw[1:].split("】", 1)
        type_names = {item.label: item.id for item in NODE_TYPES}
        node_type = type_names.get(node_type, node_type)
        item_option.rect.adjust(16, 0, 0, 0)
        super().paint(painter, item_option, index)
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.node_type_colors().get(node_type, theme.node_type_colors()["other"])))
        painter.drawEllipse(option.rect.left() + 6, option.rect.center().y() - 3, 7, 7)
        painter.restore()


class GraphPage(QWidget):
    """知识关系图谱页面"""

    def __init__(self, memory_system, parent=None):
        super().__init__(parent)
        self.memory = memory_system
        self.graph_file_path = graph_page_path()
        self.current_selected_node = None

        # 酒馆模式相关属性
        self.tavern_mode = False
        self.tavern_session_id = None
        self.showing_tavern_placeholder = False
        self._tavern_graph_data = None
        self._tavern_entities = []
        self.layout_storage_root = Path.cwd() / "data"
        self._layout_node_ids = set()

        # 创建HTML生成器
        self.html_generator = GraphHTMLGenerator()
        # 将输出HTML写到模板目录，保证相对assets路径能加载
        try:
            self.graph_file_path = graph_page_path()
            logger.debug(f"[Graph] HTML输出路径: {self.graph_file_path}")
            from pathlib import Path as _P
            _assets_root = _P(__file__).resolve().parent / 'assets'
            logger.debug(f"[Graph] 资源基路径: {_assets_root}")
        except Exception as _e:
            logger.warning(f"[Graph] 设定HTML输出路径失败，退回默认: {_e}")


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
        title.setProperty("role", "pageTitle")


        # 快速操作按钮
        self.refresh_btn = QPushButton("刷新图谱")
        self.refresh_btn.setProperty("variant", "ghost")

        self.export_btn = QPushButton("导出图谱")
        self.export_btn.setProperty("variant", "ghost")

        self.reset_view_btn = QPushButton("重置视图")
        self.reset_view_btn.setProperty("variant", "ghost")

        self.init_graph_btn = QPushButton("初始化图谱")
        self.init_graph_btn.setProperty("variant", "ghost")

        self.clear_graph_btn = QPushButton("清空图谱")
        self.clear_graph_btn.setProperty("variant", "danger")

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
                logger.debug("开发者工具已启用")
            else:
                # 尝试直接设置常见的开发者工具属性
                try:
                    settings.setAttribute(settings.DeveloperExtrasEnabled, True)
                    logger.debug("开发者工具已启用(直接属性)")
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
        self.clear_search_btn.setProperty("variant", "ghost")

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
        self.filter_type_buttons = {item.id: QPushButton(item.label) for item in NODE_TYPES}
        self.filter_character_btn = self.filter_type_buttons['character']
        self.filter_location_btn = self.filter_type_buttons['location']
        self.filter_item_btn = self.filter_type_buttons['item']
        self.filter_event_btn = self.filter_type_buttons['event']

        # 设置过滤按钮样式
        filter_buttons = [self.filter_all_btn, *self.filter_type_buttons.values()]

        for btn in filter_buttons:
            btn.setCheckable(True)
            btn.setProperty("variant", "ghost")
            btn.setMaximumHeight(30)
            filter_layout.addWidget(btn)

        self.filter_all_btn.setChecked(True)  # 默认选中全部

        entity_layout.addLayout(filter_layout)

        # 实体列表
        self.entity_list = QListWidget()
        self.entity_list.setMinimumHeight(200)
        self.entity_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.entity_list.setTextElideMode(Qt.ElideRight)
        self.entity_list.setItemDelegate(EntityListDelegate(self.entity_list))
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
        self.delete_node_btn.setProperty("variant", "danger")


        node_actions.addWidget(self.add_node_btn)
        node_actions.addWidget(self.edit_node_btn)
        node_actions.addWidget(self.delete_node_btn)

        detail_layout.addLayout(node_actions)
        layout.addWidget(detail_group)

        # 图谱统计
        stats_group = QGroupBox("图谱统计")
        stats_layout = QVBoxLayout(stats_group)

        self.stats_label = QLabel("节点数量: 0\n关系数量: 0\n最后更新: 未知")
        self.stats_label.setProperty("role", "stats")


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
        filter_buttons = [self.filter_all_btn, *self.filter_type_buttons.values()]

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
        """刷新关系图谱（自动根据模式选择数据源）"""
        try:
            if self.tavern_mode:
                if self.tavern_session_id:
                    self.refresh_from_api_server(self.tavern_session_id, force=True)
                else:
                    self._show_tavern_mode_placeholder("pending", {"graph_nodes": 0, "graph_edges": 0})
                return

            logger.debug("[Graph] 本地模式刷新知识关系图谱...")
            # 重新加载实体和关系到知识图谱（确保同步，现在包含关系）
            self.memory.reload_entities_from_json()

            # 一次性获取所有实体数据，避免重复调用
            entities = self.get_all_entities()

            # 更新UI显示（传递数据避免重复获取）
            self.update_entity_list_with_data(entities, self._selected_filter_type())
            self.update_stats_with_data(entities)

            # 生成图谱HTML（传递数据避免重复获取）
            self.generate_graph_html_with_data(entities)

            # 加载到WebView
            if self.graph_file_path.exists():
                self.graph_view.load(QUrl.fromLocalFile(str(self.graph_file_path)))
                self.showing_tavern_placeholder = False
        except Exception as e:
            logger.error(f"刷新图谱失败: {e}")
            QMessageBox.warning(self, "错误", f"刷新图谱失败：{str(e)}")

    def _selected_filter_type(self):
        for button in (self.filter_all_btn, *self.filter_type_buttons.values()):
            if button.isChecked():
                return button.text()
        return self.filter_all_btn.text()

    def update_entity_list_with_data(self, entities, filter_type: str = "全部"):
        """使用提供的实体数据更新实体列表（避免重复获取）"""
        try:
            self.entity_list.clear()
            self.current_selected_node = None
            self.detail_text.clear()

            selected_type = {item.label: item.id for item in NODE_TYPES}.get(filter_type)
            filtered_entities = [entity for entity in entities
                                 if selected_type is None or entity.get('type') == selected_type]

            # 添加实体到列表
            for entity in filtered_entities:
                item_text = entity.get('display_name') or display_name(entity.get('name', ''), entity.get('attributes', {}).get('name'))
                if entity.get('description'):
                    item_text += f" - {entity['description'][:50]}{'...' if len(entity['description']) > 50 else ''}"

                list_item = QListWidgetItem(item_text)
                list_item.setData(Qt.UserRole, entity)  # 存储完整的实体数据
                self.entity_list.addItem(list_item)

        except Exception as e:
            logger.error(f"更新实体列表失败: {e}")

    def update_stats_with_data(self, entities):
        """使用提供的实体数据更新统计信息（避免重复获取）"""
        try:
            node_count = len(entities)

            # 计算关系数量（简单估算：每个实体平均2个关系）
            relation_count = self.memory.knowledge_graph.graph.number_of_edges()

            import datetime
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            stats_text = f"""节点数量: {node_count}
关系数量: {relation_count}
最后更新: {current_time}"""

            if hasattr(self, 'stats_label'):
                self.stats_label.setText(stats_text)

        except Exception as e:
            logger.error(f"更新统计信息失败: {e}")

    def _graph_layout_path(self):
        from src.ui.graph_layout_store import layout_path
        if self.tavern_mode:
            return layout_path(session_id=self.tavern_session_id, storage_root=self.layout_storage_root)
        return layout_path(entities_path=self.memory.entities_json_path)

    def load_graph_layout(self):
        from src.ui.graph_layout_store import load_layout
        try:
            return load_layout(self._graph_layout_path(), self._layout_node_ids)
        except (KeyError, ValueError, OSError) as exc:
            logger.warning(f"Graph layout unavailable: {exc}")
            return {}

    def save_graph_layout(self, positions):
        from src.ui.graph_layout_store import save_layout
        try:
            save_layout(self._graph_layout_path(), positions, self._layout_node_ids)
        except (KeyError, ValueError, OSError) as exc:
            logger.warning(f"Graph layout save failed: {exc}")

    def clear_graph_layout(self):
        from src.ui.graph_layout_store import clear_layout
        try:
            clear_layout(self._graph_layout_path())
        except (KeyError, ValueError, OSError) as exc:
            logger.warning(f"Graph layout clear failed: {exc}")

    def generate_graph_html_with_data(self, entities):
        """使用提供的实体数据生成图谱HTML文件（避免重复获取）"""
        try:
            # 构建节点和边的数据
            nodes = []
            links = []

            for i, entity in enumerate(entities):
                nodes.append({
                    'id': entity['name'],
                    'name': entity.get('display_name') or display_name(entity['name'], entity.get('attributes', {}).get('name')),
                    'type': normalize_type(entity['type'])[0],
                    'subtype': entity.get('subtype') or entity.get('attributes', {}).get('subtype', ''),
                    'description': entity.get('description', ''),
                    'group': self._get_type_group(normalize_type(entity['type'])[0]),
                    'is_main_character': bool(entity.get('attributes', {}).get('is_main_character'))
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
            self._layout_node_ids = {node["id"] for node in nodes}
            layout_json = json.dumps(self.load_graph_layout(), ensure_ascii=False)

            # 使用HTML生成器生成文件
            self.html_generator.generate_graph_html(nodes_json, links_json, self.graph_file_path, layout_json)

        except Exception as e:
            logger.error(f"生成图谱HTML失败: {e}")
            logger.error(f"错误详情: {traceback.format_exc()}")
            # 如果失败，使用HTML生成器的备用方案
            self.html_generator._generate_fallback_html(self.graph_file_path)

    def generate_graph_html(self):
        """生成图谱HTML文件（向后兼容方法）"""
        entities = self.get_all_entities()
        self.generate_graph_html_with_data(entities)

    def _get_type_group(self, entity_type):
        """获取实体类型的分组ID"""
        return TYPE_IDS.index(entity_type) + 1 if entity_type in TYPE_IDS else TYPE_IDS.index('other') + 1

    def update_entity_list(self, filter_type: str = "全部"):
        """更新实体列表（向后兼容方法）"""
        entities = self.get_all_entities()
        self.update_entity_list_with_data(entities, filter_type)

    def get_all_entities(self):
        """获取所有实体（从知识图谱内存状态获取）"""
        try:
            entities = []

            # 在酒馆模式下，尝试从API服务器获取数据
            if self.tavern_mode:
                return list(self._tavern_entities)

            for node_id, attrs in self.memory.knowledge_graph.graph.nodes(data=True):
                entity = {
                    'name': node_id,
                    'type': normalize_type(attrs.get('type', 'other'))[0],
                    'subtype': attrs.get('subtype', ''),
                    'display_name': display_name(node_id, attrs.get('name')),
                    'description': attrs.get('description', ''),
                    'created_time': attrs.get('created_time', time.time()),
                    'last_modified': attrs.get('last_modified', time.time()),
                    'attributes': {}
                }

                # 添加动态属性，排除系统属性
                excluded_keys = {'type', 'subtype', 'description', 'created_time', 'last_modified'}
                for key, value in attrs.items():
                    if key not in excluded_keys:
                        entity['attributes'][key] = value

                entities.append(entity)

            logger.info(f"📊 从知识图谱内存获取 {len(entities)} 个实体")
            return entities

        except Exception as e:
            logger.error(f"从知识图谱获取实体失败: {e}")
            return []

    def _tavern_mutation(self, method, path, payload=None, params=None):
        from urllib.parse import quote
        if not self.tavern_session_id:
            raise RuntimeError("酒馆会话不可用，请重新连接后重试。")
        url = f"{self._api_base_url()}/sessions/{quote(self.tavern_session_id, safe='')}/{path}"
        try:
            response = requests.request(method, url, json=payload, params=params, timeout=30)
        except requests.RequestException as exc:
            raise RuntimeError("酒馆后端不可用，请检查连接后重试。") from exc
        if not response.ok:
            try:
                detail = response.json().get("detail", response.text)
            except (ValueError, AttributeError):
                detail = response.text
            raise RuntimeError(str(detail))
        if not self.refresh_from_api_server(self.tavern_session_id, force=True):
            raise RuntimeError("节点已保存，但无法从酒馆会话刷新图谱。")
        return response.json()

    def mutate_relationship(self, action, source, target, relation=None):
        try:
            if self.tavern_mode:
                method = {"create": "POST", "update": "PUT", "delete": "DELETE"}[action]
                body = {"source": source, "target": target}
                if action != "delete":
                    body["relationship"] = relation
                self._tavern_mutation(method, "relationships", None if action == "delete" else body,
                                      body if action == "delete" else None)
            else:
                from src.graph.graph_operations import save_local_relationship
                save_local_relationship(self.memory, action, source, target, relation)
                self.refresh_graph()
        except Exception as exc:
            QMessageBox.warning(self, "??????", str(exc))
            return False
        return True

    def save_entities(self, entities, old_name=None, new_name=None):
        """Persist local or active tavern node edits."""
        if self.tavern_mode:
            from urllib.parse import quote
            if old_name:
                entity = next(entity for entity in entities if entity["name"] == new_name)
                self._tavern_mutation("PUT", f"nodes/{quote(old_name, safe='')}", entity)
            else:
                self._tavern_mutation("POST", "nodes", entities[-1])
            return
        from src.graph.graph_operations import save_local_entities
        save_local_entities(self.memory, entities, old_name, new_name)

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
            list_item = QListWidgetItem(entity.get('display_name') or display_name(entity['name'], entity.get('attributes', {}).get('name')))
            list_item.setData(Qt.UserRole, entity)
            self.entity_list.addItem(list_item)

    def update_stats(self):
        """更新图谱统计信息（向后兼容方法）"""
        entities = self.get_all_entities()
        self.update_stats_with_data(entities)

    def search_nodes(self):
        """搜索节点"""
        search_term = self.search_input.text().strip()
        if not search_term:
            return

        try:
            all_entities = self.get_all_entities()
            matching_entities = []
            selected_filter = self._selected_filter_type()
            filter_types = {item.label: item.id for item in NODE_TYPES}

            # 搜索匹配的实体
            for entity in all_entities:
                if selected_filter in filter_types and entity['type'] != filter_types[selected_filter]:
                    continue
                if (search_term.lower() in entity['name'].lower() or
                    search_term.lower() in entity.get('description', '').lower() or
                    search_term.lower() in entity['type'].lower()):
                    matching_entities.append(entity)

            # 更新实体列表显示搜索结果
            self.entity_list.clear()
            self.current_selected_node = None
            self.detail_text.clear()
            for entity in matching_entities:
                list_item = QListWidgetItem(entity.get('display_name') or display_name(entity['name'], entity.get('attributes', {}).get('name')))
                list_item.setData(Qt.UserRole, entity)
                self.entity_list.addItem(list_item)

            if not matching_entities:
                self.entity_list.addItem("未找到匹配的节点")

            logger.info(f"搜索节点: {search_term}, 找到 {len(matching_entities)} 个结果")

        except Exception as e:
            logger.error(f"搜索节点失败: {e}")
            QMessageBox.warning(self, "搜索错误", f"搜索失败：{str(e)}")

    def clear_search(self):
        """清除搜索"""
        self.search_input.clear()
        self.update_entity_list(self._selected_filter_type())

    def filter_entities(self):
        """过滤实体"""
        sender = self.sender()

        # 取消其他过滤按钮的选中状态
        filter_buttons = [self.filter_all_btn, *self.filter_type_buttons.values()]

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
            # Resolve the visible row through its stored entity data.
            row_entity = item.data(Qt.UserRole)
            entity_display_name = row_entity.get('name', entity_name) if isinstance(row_entity, dict) else entity_name
            entity_type = row_entity.get('type', 'unknown') if isinstance(row_entity, dict) else 'unknown'

            all_entities = self.get_all_entities()
            selected_entity = next(
                (entity for entity in all_entities
                 if entity['name'] == entity_display_name and entity['type'] == entity_type),
                row_entity if isinstance(row_entity, dict) else None
            )

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
名称: {selected_entity.get('display_name') or display_name(selected_entity['name'], selected_entity.get('attributes', {}).get('name'))}
类型: {TYPE_LABELS.get(selected_entity['type'], TYPE_LABELS['other'])}{' · ' + selected_entity['subtype'] if selected_entity.get('subtype') else ''}
描述: {selected_entity.get('description', '暂无描述')}
创建时间: {created_time}
属性:
{attr_text}"""

            else:
                # 备用显示
                detail_text = f"""节点信息:
名称: {display_name(entity_display_name)}
类型: {TYPE_LABELS.get(entity_type, TYPE_LABELS['other'])}
创建时间: 未知
描述: 暂无描述
属性: 暂无数据"""

            self.detail_text.setText(detail_text)
            self.current_selected_node = f"[{entity_type}] {entity_display_name}"

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
            row_entity = item.data(Qt.UserRole)
            node_name = row_entity.get('name', entity_name) if isinstance(row_entity, dict) else entity_name

            # 执行JavaScript来聚焦节点
            js_code = f"""
            // 查找并高亮节点
            const targetNode = d3.selectAll('.node').filter(d => d.id === {json.dumps(node_name)});
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
                    .style('stroke', '{theme.current()['ACCENT']}');

                // 恢复正常大小
                setTimeout(() => {{
                    targetNode.transition().duration(300)
                        .attr('r', 14)
                        .style('stroke-width', '2px')
                        .style('stroke', '{theme.current()['BG_BASE']}');
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
                        current_entity = {**entity, "attributes": dict(entity.get("attributes", {}))}
                        break

                if not current_entity:
                    logger.warning("Node edit refused: entity not found: %s (%s)", entity_name, entity_type)
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
            name_edit = QLineEdit(current_entity.get('display_name') or display_name(current_entity['name'], current_entity.get('attributes', {}).get('name')))
            name_edit.setPlaceholderText("请输入节点名称")
            basic_layout.addRow("名称 *:", name_edit)

            # 类型
            type_combo = QComboBox()
            type_combo.addItems(TYPE_IDS)
            type_combo.setCurrentText(current_entity['type'])
            basic_layout.addRow("类型:", type_combo)
            subtype_edit = QLineEdit(current_entity.get('subtype', ''))
            basic_layout.addRow("细分类别:", subtype_edit)

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


            # 属性列表容器widget
            attr_scroll = QWidget()

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
                delete_btn.setProperty("variant", "danger")
                delete_btn.setMinimumWidth(60)
                delete_btn.setMaximumWidth(80)
                delete_btn.setMinimumHeight(30)


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
                        new_delete_btn.setProperty("variant", "danger")
                        new_delete_btn.setMinimumWidth(60)
                        new_delete_btn.setMaximumWidth(80)
                        new_delete_btn.setMinimumHeight(30)

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
            add_attr_btn.clicked.connect(lambda: add_attribute_row())
            attr_layout.addWidget(add_attr_btn)

            main_layout.addWidget(attr_group)

            # 按钮区域
            button_layout = QHBoxLayout()
            button_layout.addStretch()

            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(dialog.reject)

            if not is_new_node:
                delete_btn = QPushButton("删除节点")
                delete_btn.setProperty("variant", "danger")

                def delete_changes():
                    answer = QMessageBox.question(
                        dialog, "确认删除",
                        f"确定删除节点 '{entity_name}'吗？",
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    if answer != QMessageBox.Yes:
                        logger.info("Node deletion cancelled: %s", entity_name)
                        return
                    try:
                        if self.tavern_mode:
                            from urllib.parse import quote
                            self._tavern_mutation("DELETE", f"nodes/{quote(entity_name, safe='')}")
                        else:
                            entities = self.get_all_entities()
                            remaining = [entity for entity in entities
                                         if not (entity["name"] == entity_name and entity["type"] == entity_type)]
                            if len(remaining) == len(entities):
                                raise RuntimeError(f"找不到要删除的节点: {entity_name}")
                            self.save_entities(remaining)
                            self.refresh_graph()
                        self.current_selected_node = None
                        self.detail_text.clear()
                    except Exception as exc:
                        logger.exception("Node deletion failed: %s", exc)
                        QMessageBox.warning(dialog, "删除失败", str(exc))
                        return
                    QMessageBox.information(dialog, "成功", f"节点 '{entity_name}' 已删除")
                    dialog.accept()

                delete_btn.clicked.connect(delete_changes)

            save_btn = QPushButton("保存" if not is_new_node else "创建")
            save_btn.setProperty("variant", "primary")


            def save_changes():
                # 验证输入
                new_name = name_edit.text().strip()
                if not new_name:
                    logger.warning("Node edit refused: empty name")
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
                if not is_new_node and new_name == (current_entity.get('display_name') or display_name(entity_name, current_entity.get('attributes', {}).get('name'))):
                    new_name = entity_name
                current_entity['name'] = new_name
                current_entity['type'] = type_combo.currentText()
                current_entity['subtype'] = subtype_edit.text().strip()
                new_name = current_entity['name']
                current_entity['description'] = desc_edit.toPlainText().strip()
                if 'name' in current_entity.get('attributes', {}):
                    new_attributes['name'] = name_edit.text().strip()
                current_entity['attributes'] = new_attributes
                current_entity['last_modified'] = time.time()

                if is_new_node:
                    # 添加新实体
                    all_entities = self.get_all_entities()
                    all_entities.append(current_entity)
                    try:
                        self.save_entities(all_entities)
                    except Exception as exc:
                        logger.exception("Node save failed: %s", exc)
                        QMessageBox.warning(dialog, "Save failed", str(exc))
                        return
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

                    try:
                        self.save_entities(all_entities, old_name=entity_name, new_name=new_name)
                    except Exception as exc:
                        logger.exception("Node save failed: %s", exc)
                        QMessageBox.warning(dialog, "Save failed", str(exc))
                        return
                    logger.info(f"实体更新成功: {new_name} (类型: {type_combo.currentText()})")

                if not self.tavern_mode:
                    self.refresh_graph()

                QMessageBox.information(dialog, "成功", success_msg)
                dialog.accept()

            save_btn.clicked.connect(save_changes)

            if not is_new_node:
                button_layout.addWidget(delete_btn)
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
            f"确定要删除节点 '{node_name}'吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if self.tavern_mode:
                from urllib.parse import quote
                try:
                    self._tavern_mutation("DELETE", f"nodes/{quote(node_name, safe='')}")
                    self.current_selected_node = None
                    self.detail_text.clear()
                except Exception as exc:
                    QMessageBox.warning(self, "????", str(exc))
                return
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
                try:
                    self.save_entities(all_entities)
                except Exception as exc:
                    QMessageBox.warning(self, "Delete failed", str(exc))
                    return
                self.refresh_graph()

                # 清除选择状态
                self.current_selected_node = None
                self.detail_text.clear()
                self.detail_text.setPlaceholderText("选择一个节点查看详细信息...")

                # 更新实体列表和统计
                self.update_entity_list()
                self.update_stats()

                QMessageBox.information(self, "成功", f"节点 '{entity_name}'删除成功")
                logger.info(f"删除节点: {entity_name}")
            else:
                QMessageBox.warning(self, "错误", "找不到要删除的节点")

    def export_graph(self):
        """导出图谱"""
        try:
            if self.tavern_mode and not self.refresh_from_api_server(self.tavern_session_id):
                QMessageBox.warning(self, "Export failed", "Tavern graph is unavailable")
                return
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
                    'title': 'EchoGraph Knowledge Graph',
                    'created_by': 'EchoGraph',
                    'export_time': time.time(),
                    'version': '1.0.0'
                },
                'entities': entities,
                'relationships': (self._tavern_graph_data or {}).get('graph_data', {}).get(
                    'links', (self._tavern_graph_data or {}).get('graph_data', {}).get('edges', []))
                if self.tavern_mode else [
                    {'source': source, 'target': target, **attrs}
                    for source, target, attrs in self.memory.knowledge_graph.graph.edges(data=True)
                ],
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
        if self.tavern_mode and not self.tavern_session_id:
            return
        reply = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空当前的知识图谱吗？\n\n此操作将删除所有实体和关系，无法撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                if self.tavern_mode and self.tavern_session_id:
                    # 酒馆模式下：通过API清空当前会话的图谱
                    api_url = f"{self._api_base_url()}/sessions/{self.tavern_session_id}/clear"
                    api_timeout = int(os.getenv("API_TIMEOUT", "15"))
                    response = requests.post(api_url, timeout=api_timeout)
                    if response.status_code == 200:
                        logger.info("通过API成功清空酒馆会话知识图谱")
                        # 刷新显示
                        if not self.refresh_from_api_server(self.tavern_session_id):
                            raise RuntimeError("Graph cleared but refresh failed")
                    else:
                        raise Exception(f"API清空失败: {response.status_code}")
                else:
                    # 本地模式下：清空内存中的知识图谱
                    from src.graph.graph_operations import clear_knowledge_graph
                    clear_knowledge_graph(self.memory)
                    # 刷新显示（已包含统计信息更新）
                    self.refresh_graph()

                self.clear_graph_layout()
                QMessageBox.information(self, "清空完成", "知识图谱已成功清空。")
                logger.info("知识图谱已清空")

            except Exception as e:
                logger.error(f"清空知识图谱失败: {e}")
                QMessageBox.warning(self, "清空失败", f"清空知识图谱时出现错误：\n{str(e)}")

    def initialize_graph(self):
        """初始化知识图谱"""
        if self.tavern_mode:
            # --- 酒馆模式下的重新初始化 ---
            if not self.tavern_session_id:
                QMessageBox.warning(self, "操作失败", "无法重新初始化：未找到有效的酒馆会话ID。")
                return

            reply = QMessageBox.question(
                self,
                "确认操作",
                "这将重新初始化知识图谱，确定要继续吗？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

            try:
                logger.debug(f"🚀 [UI] Starting tavern graph initialization for session: {self.tavern_session_id}")

                # 直接调用重新初始化API
                logger.debug(f"🔄 [UI] Calling coordinated re-initialization API for session: {self.tavern_session_id}")
                api_url = f"{self._api_base_url()}/tavern/sessions/{self.tavern_session_id}/request_reinitialize"

                api_timeout = int(os.getenv("API_TIMEOUT", "15"))
                response = requests.post(api_url, timeout=api_timeout)

                if response.status_code == 200:
                    result = response.json()
                    QMessageBox.information(
                        self,
                        "重新初始化已启动",
                        f"知识图谱重新初始化已开始。\n\n{result.get('message', '请稍等片刻...')}"
                    )
                    # 刷新图谱
                    session_id = self.tavern_session_id
                    QTimer.singleShot(3000, lambda: self.refresh_graph()
                                      if self.tavern_mode and self.tavern_session_id == session_id else None)
                else:
                    try:
                        error_msg = response.json().get("detail", response.text)
                    except:
                        error_msg = response.text[:200]
                    QMessageBox.warning(self, "初始化失败", f"重新初始化失败 (HTTP {response.status_code}):\n{error_msg}")

            except Exception as api_error:
                logger.error(f"❌ [UI] API call failed: {api_error}")
                QMessageBox.warning(self, "网络问题", f"无法连接到服务器，请检查EchoGraph服务是否运行")

        else:
            # --- 本地模式下的初始化 ---
            reply = QMessageBox.question(
                self,
                "初始化知识图谱",
                "是否要创建默认的游戏开局？\n\n这将清空现有图谱并创建新的世界设定。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if reply == QMessageBox.Yes:
                self.create_default_scenario_for_graph()

    def reinitialize_tavern_character_graph(self):
        """重新初始化酒馆角色的知识图谱"""
        try:
            logger.info(f"🍺 重新初始化酒馆角色知识图谱，会话ID: {self.tavern_session_id}")

            # 获取主窗口实例
            main_window = None
            widget = self.parent()
            while widget is not None:
                if isinstance(widget, EchoGraphMainWindow):
                    main_window = widget
                    break
                widget = widget.parent()

            if not main_window:
                QMessageBox.warning(self, "初始化失败", "无法找到主窗口实例")
                return

            # 清空当前知识图谱
            api_base_url = self._api_base_url()

            # 调用API服务器的角色初始化端点
            init_url = f"{api_base_url}/sessions/{self.tavern_session_id}/reinitialize"

            response = requests.post(init_url, timeout=30)

            if response.status_code == 200:
                result = response.json()
                nodes_created = result.get('nodes_created', 0)
                edges_created = result.get('edges_created', 0)
                character_name = result.get('character_name', '未知角色')

                logger.info(f"✅ 酒馆角色图谱重新初始化成功: {character_name}, 节点={nodes_created}, 边={edges_created}")

                # 刷新UI显示 - 从API服务器获取最新数据
                self.refresh_from_api_server(self.tavern_session_id)

                QMessageBox.information(
                    self,
                    "初始化成功",
                    f"酒馆角色 '{character_name}'的知识图谱已重新初始化！\n\n"
                    f"创建了 {nodes_created} 个节点和 {edges_created} 个关系。"
                )

            else:
                error_text = response.text
                logger.error(f"❌ 酒馆角色图谱重新初始化失败: HTTP {response.status_code} - {error_text}")
                QMessageBox.warning(
                    self,
                    "初始化失败",
                    f"无法重新初始化酒馆角色图谱：\nHTTP {response.status_code}\n\n{error_text}"
                )

        except requests.exceptions.Timeout:
            logger.error("⏱️ 酒馆角色图谱初始化超时")
            QMessageBox.warning(self, "初始化超时", "重新初始化请求超时，请检查API服务器状态")

        except Exception as e:
            logger.error(f"💥 酒馆角色图谱重新初始化异常: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")
            QMessageBox.critical(self, "初始化异常", f"重新初始化时发生异常：\n{str(e)}")

    def create_default_scenario_for_graph(self):
        """为知识图谱创建默认场景（不依赖对话ID）"""
        try:
            # 使用主窗口的方法创建默认开局
            main_window = None
            widget = self.parent()
            while widget is not None:
                if isinstance(widget, EchoGraphMainWindow):
                    main_window = widget
                    break
                widget = widget.parent()

            if main_window:
                # 先清空现有图谱
                from src.graph.graph_operations import clear_knowledge_graph
                clear_knowledge_graph(self.memory)

                # 创建默认开局
                if not main_window.create_default_game_scenario("manual_init"):
                    return

                # 只需要刷新图谱显示，refresh_graph内部会更新实体列表和统计信息
                self.refresh_graph()
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
                self.dev_view.setWindowTitle("开发者工具 - EchoGraph Graph")
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
                    debug_text = json.dumps(result, indent=2, ensure_ascii=False)
                    QMessageBox.information(self, "调试信息", f"图谱状态：\n{debug_text}")
                else:
                    QMessageBox.information(self, "调试信息", "无法获取调试信息")

            self.graph_view.page().runJavaScript(js_code, show_result)

        except Exception as e:
            logger.error(f"显示调试信息失败: {e}")
            QMessageBox.warning(self, "错误", f"获取调试信息失败：{str(e)}")

    def _api_base_url(self):
        main_window = self.window()
        port = getattr(main_window, 'api_server_port', 9543)
        return f"http://127.0.0.1:{port}"

    def _update_mode_controls(self):
        pending = self.tavern_mode and not self.tavern_session_id
        unavailable = self.tavern_mode and self.showing_tavern_placeholder
        self.refresh_btn.setEnabled(not pending)
        self.refresh_btn.setToolTip("等待酒馆会话连接" if pending else "")
        for button in (self.export_btn, self.init_graph_btn, self.clear_graph_btn,
                       self.reset_view_btn, self.search_btn, self.clear_search_btn,
                       self.filter_all_btn, *self.filter_type_buttons.values()):
            button.setEnabled(not unavailable)
            button.setToolTip("酒馆图谱暂不可用，请刷新重试" if unavailable else "")
        for button in (self.add_node_btn, self.edit_node_btn, self.delete_node_btn):
            button.setEnabled(not pending)
            button.setToolTip("等待酒馆会话连接" if pending else "")
        self.search_input.setEnabled(not unavailable)
        self.entity_list.setEnabled(not unavailable)

    def enter_tavern_mode(self, session_id: str):
        """进入酒馆模式，切换到使用API服务器的数据源"""
        self.tavern_mode = True
        self.tavern_session_id = session_id
        self.showing_tavern_placeholder = False
        self._tavern_graph_data = None
        self._tavern_entities = []
        self._update_mode_controls()

        # 清理本地模式的数据显示
        self.clear_graph_display()

        logger.info(f"GraphPage进入酒馆模式，会话ID: {session_id}")

    def exit_tavern_mode(self, local_memory=None):
        """退出酒馆模式，切换回本地数据源"""
        self.tavern_mode = False
        self.tavern_session_id = None
        self.showing_tavern_placeholder = False
        self._tavern_graph_data = None
        self._tavern_entities = []
        self._update_mode_controls()

        # 清理酒馆模式的数据显示
        self.clear_graph_display()

        if local_memory is not None:
            self.memory = local_memory
        else:
            # 独立使用 GraphPage 时保留原有的本地数据源回退行为。
            try:
                local_mode_path = Path(__file__).parent / "data" / "local_mode"
                local_mode_path.mkdir(exist_ok=True)
                self.memory = GRAGMemory(
                    hot_memory_size=10,
                    graph_save_path=str(local_mode_path / "knowledge_graph.graphml"),
                    entities_json_path=str(local_mode_path / "entities.json"),
                    auto_load_entities=True,
                    attention_config=ATTENTION_CONFIG.copy(),
                )
                logger.info(f"已切换内存对象到本地模式路径: {local_mode_path}")
            except Exception as e:
                logger.error(f"重新初始化本地模式内存对象失败: {e}")

        # 重新加载本地模式的数据
        self.refresh_graph()

        logger.info("GraphPage退出酒馆模式，切换回本地数据源")

    def clear_graph_display(self):
        """清理图谱显示数据"""
        try:
            # 清空图谱显示
            self.graph_view.setHtml(f"<html><body style=\"background:{theme.current()['BG_BASE']};color:{theme.current()['TEXT_PRIMARY']}\"><p>Loading...</p></body></html>")

            # 清空实体列表
            if hasattr(self, 'entity_list'):
                self.entity_list.clear()
            self.current_selected_node = None
            self.detail_text.clear()

            # 重置统计信息
            if hasattr(self, 'stats_label'):
                self.stats_label.setText("节点: 0 | 关系: 0")

            logger.info("已清理图谱显示数据")
        except Exception as e:
            logger.error(f"清理图谱显示失败: {e}")

    def refresh_from_api_server(self, session_id: str, force: bool = False):
        """从API服务器获取知识图谱数据并刷新显示"""
        try:
            logger.info(f"从API服务器获取会话 {session_id} 的知识图谱数据...")


            # 获取会话统计信息
            api_base_url = self._api_base_url()  # 从配置获取
            stats_url = f"{api_base_url}/sessions/{session_id}/stats"

            health_check_timeout = int(os.getenv("HEALTH_CHECK_TIMEOUT", "10"))
            response = requests.get(stats_url, timeout=health_check_timeout)
            if not self.tavern_mode or self.tavern_session_id != session_id:
                return False
            if response.status_code == 200:
                stats = response.json()
                logger.info(f"成功获取会话统计: 节点={stats.get('graph_nodes', 0)}, 边={stats.get('graph_edges', 0)}")
                if stats.get("graph_nodes", 0) == 0:
                    if hasattr(self, "clear_graph_layout"):
                        self.clear_graph_layout()
                    state = {}
                    try:
                        current = requests.get(f"{api_base_url}/tavern/current_session", timeout=health_check_timeout)
                        if current.status_code == 200 and current.json().get("session_id") == session_id:
                            state = current.json()
                    except Exception as state_error:
                        logger.debug(f"无法获取图谱初始化状态: {state_error}")
                    placeholder_data = {**stats, **state}
                    if (self.showing_tavern_placeholder and self.tavern_session_id == session_id
                            and self._placeholder_stats == placeholder_data):
                        return True
                    self._show_tavern_mode_placeholder(session_id, placeholder_data)
                    return True

                # 获取会话的知识图谱导出数据
                export_url = f"{api_base_url}/sessions/{session_id}/export"
                export_response = requests.get(export_url, timeout=30)

                if not self.tavern_mode or self.tavern_session_id != session_id:
                    return False
                if export_response.status_code == 200:
                    graph_data = export_response.json()
                    if (not self.showing_tavern_placeholder and self._tavern_graph_data
                            and graph_data.get('graph_data') == self._tavern_graph_data.get('graph_data')):
                        return True
                    self._tavern_graph_data = graph_data
                    self._tavern_entities = [
                        {'name': node.get('id', ''), 'type': normalize_type(node.get('type', 'other'))[0],
                         'display_name': display_name(node.get('id', ''), node.get('name')),
                         'subtype': node.get('subtype') or normalize_type(node.get('type', 'other'))[1],
                         'description': node.get('description', ''),
                         'created_time': node.get('created_time', time.time()),
                         'last_modified': node.get('last_modified', time.time()),
                         'attributes': {key: value for key, value in node.items()
                                        if key not in {'id', 'type', 'subtype', 'description',
                                                       'created_time', 'last_modified'}}}
                        for node in graph_data.get('graph_data', {}).get('nodes', [])
                    ]
                    self.showing_tavern_placeholder = False
                    self._update_mode_controls()
                    logger.info("成功获取知识图谱导出数据")

                    # 从导出的图谱数据生成HTML显示
                    self._generate_graph_html_from_api_data(graph_data)

                    # 加载图谱HTML
                    if self.graph_file_path.exists():
                        self.graph_view.load(QUrl.fromLocalFile(str(self.graph_file_path)))
                        logger.info("知识图谱HTML已加载到WebView")

                    # 更新实体列表和统计
                    self._update_ui_from_api_data(graph_data)
                    return True
                else:
                    logger.warning(f"无法获取图谱导出数据: HTTP {export_response.status_code}")
                    # 尝试仅使用统计数据更新UI
                    self._update_ui_from_stats_only(stats)
                    self._show_tavern_mode_placeholder(session_id, stats)
            else:
                logger.warning(f"Cannot fetch Tavern session stats: HTTP {response.status_code}")
                self._show_tavern_mode_placeholder(session_id, {"graph_nodes": 0, "graph_edges": 0})
        except Exception as exc:
            logger.error(f"Tavern graph refresh failed: {exc}")
            if self.tavern_mode and self.tavern_session_id == session_id:
                self._show_tavern_mode_placeholder(session_id, {"graph_nodes": 0, "graph_edges": 0})
        return False

    def _generate_graph_html_from_api_data(self, graph_data: dict):
        """从API数据生成图谱HTML"""
        try:
            # 解析导出的图谱数据
            graph_json = graph_data.get('graph_data', {})
            nodes_data = graph_json.get('nodes', [])
            links_data = graph_json.get('links', graph_json.get('edges', []))

            # 转换为我们的显示格式
            nodes = []
            for node_data in nodes_data:
                node = {
                    'id': node_data.get('id', ''),
                    'name': display_name(node_data.get('id', ''), node_data.get('name')),
                    'type': normalize_type(node_data.get('type', 'other'))[0],
                    'subtype': node_data.get('subtype') or normalize_type(node_data.get('type', 'other'))[1],
                    'description': node_data.get('description', ''),
                    'group': self._get_type_group(normalize_type(node_data.get('type', 'other'))[0]),
                    'is_main_character': bool(node_data.get('is_main_character'))
                }
                nodes.append(node)

            # 转换链接数据
            links = []
            for link_data in links_data:
                link = {
                    'source': link_data.get('source', ''),
                    'target': link_data.get('target', ''),
                    'relation': link_data.get('relationship', 'related_to')
                }
                links.append(link)

            logger.info(f"转换API数据: {len(nodes)} 个节点, {len(links)} 个连接")

            # 生成JSON字符串
            nodes_json = json.dumps(nodes, ensure_ascii=False)
            links_json = json.dumps(links, ensure_ascii=False)

            # 使用HTML生成器生成文件
            self._layout_node_ids = {node["id"] for node in nodes}
            layout_json = json.dumps(self.load_graph_layout(), ensure_ascii=False)
            self.html_generator.generate_graph_html(nodes_json, links_json, self.graph_file_path, layout_json)

        except Exception as e:
            logger.error(f"从API数据生成图谱HTML失败: {e}")
            # 使用备用方案
            self.html_generator._generate_fallback_html(self.graph_file_path)

    def _update_ui_from_stats_only(self, stats: dict):
        """仅从统计数据更新UI（当无法获取完整图谱数据时的备用方案）"""
        try:
            logger.info("使用统计数据更新UI（备用方案）")

            # 更新统计信息
            node_count = stats.get('graph_nodes', 0)
            edge_count = stats.get('graph_edges', 0)

            import datetime
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            stats_text = f"""节点数量: {node_count}
关系数量: {edge_count}
最后更新: {current_time}
数据源: API服务器"""

            self.stats_label.setText(stats_text)

            # 清空实体列表并显示占位信息
            self.entity_list.clear()
            if node_count > 0:
                self.entity_list.addItem(f"[酒馆] 检测到 {node_count} 个实体")
                self.entity_list.addItem("请刷新图谱获取详细信息")
            else:
                self.entity_list.addItem("暂无实体数据")

            logger.info(f"UI已更新（仅统计数据）: {node_count} 节点, {edge_count} 边")

        except Exception as e:
            logger.error(f"从统计数据更新UI失败: {e}")

    def _update_ui_from_api_data(self, graph_data: dict):
        """从API数据更新UI组件"""
        try:
            # 更新统计信息
            stats = graph_data.get('graph_stats', {})
            node_count = stats.get('nodes', 0)
            edge_count = stats.get('edges', 0)

            import datetime
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            stats_text = f"""节点数量: {node_count}
关系数量: {edge_count}
最后更新: {current_time}
数据源: API服务器"""

            self.stats_label.setText(stats_text)

            # 更新实体列表（从图谱数据中提取）
            self.update_entity_list_with_data(self._tavern_entities, self._selected_filter_type())

            logger.info(f"已更新UI: {len(self._tavern_entities)} 个实体")

        except Exception as e:
            logger.error(f"从API数据更新UI失败: {e}")

    def _show_tavern_mode_placeholder(self, session_id: str, stats: dict):
        """显示酒馆模式的占位信息"""
        try:
            self.tavern_mode = True
            self.tavern_session_id = None if session_id == "pending" else session_id
            self._tavern_entities = []
            self._tavern_graph_data = None
            self.clear_graph_display()
            self.showing_tavern_placeholder = True
            self._update_mode_controls()
            self._placeholder_stats = dict(stats)
            from html import escape
            state = stats.get("initialization_status")
            reason = stats.get("initialization_reason", "")
            if state == "failed":
                status_text = f"图谱初始化失败：{reason or '未知原因'}"
            elif state == "completed":
                status_text = f"图谱为空：{reason or '角色卡未提取到实体'}"
            else:
                status_text = "正在从角色卡生成图谱…"
            self.entity_list.clear()
            self.entity_list.addItem(status_text)
            safe_status = escape(status_text)
            colors = theme.current()
            # 创建简单的酒馆模式信息页面
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>EchoGraph - 酒馆模式</title>
                <style>
                    ::-webkit-scrollbar {{ width: 8px; background: {colors["BG_BASE"]}; }}
                    ::-webkit-scrollbar-thumb {{ background: {colors["BORDER_STRONG"]}; border-radius: 4px; }}
                    body {{
                        font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
                        background: {colors["BG_BASE"]};
                        color: {colors["TEXT_PRIMARY"]};
                        text-align: center;
                        padding: 50px;
                        margin: 0;
                    }}
                    .container {{
                        max-width: 600px;
                        margin: 0 auto;
                        background: {colors["BG_SURFACE"]};
                        border: 1px solid {colors["BORDER"]};
                        padding: 40px;
                        border-radius: 20px;
                        backdrop-filter: blur(10px);
                    }}
                    h1 {{ color: {colors["TEXT_PRIMARY"]}; margin-bottom: 20px; }}
                    h2 {{ color: {colors["TEXT_SECONDARY"]}; margin: 30px 0 15px 0; }}
                    .stats {{
                        display: flex;
                        justify-content: space-around;
                        margin: 30px 0;
                    }}
                    .stat {{
                        text-align: center;
                        background: {colors["BG_RAISED"]};
                        border: 1px solid {colors["BORDER"]};
                        padding: 20px;
                        border-radius: 10px;
                        min-width: 100px;
                    }}
                    .stat-number {{
                        font-size: 2em;
                        font-weight: bold;
                        color: {colors["ACCENT_TEXT"]};
                    }}
                    .info {{
                        background: {colors["BG_RAISED"]};
                        border: 1px solid {colors["BORDER"]};
                        padding: 20px;
                        border-radius: 10px;
                        margin: 20px 0;
                        text-align: left;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>酒馆模式已激活</h1>
                    <p>EchoGraph正在与SillyTavern协作，提供智能对话增强服务</p>

                    <h2>当前会话统计</h2>
                    <div class="stats">
                        <div class="stat">
                            <div class="stat-number">{stats.get('graph_nodes', 0)}</div>
                            <div>知识节点</div>
                        </div>
                        <div class="stat">
                            <div class="stat-number">{stats.get('graph_edges', 0)}</div>
                            <div>关系边</div>
                        </div>
                    </div>

                    <div class="info">
                        <h3>会话信息</h3>
                        <p><strong>会话ID:</strong> {session_id}</p>
                        <p><strong>状态:</strong> {safe_status}</p>
                        <p><strong>模式:</strong> SillyTavern集成</p>
                    </div>

                    <div class="info">
                        <h3>使用说明</h3>
                        <p>• 在SillyTavern中进行对话，EchoGraph会自动提供智能增强</p>
                        <p>• 知识图谱会根据对话内容动态更新</p>
                        <p>• 可以随时在EchoGraph主界面切换回本地模式</p>
                    </div>
                </div>
            </body>
            </html>
            """

            # 写入临时HTML文件
            temp_file = tavern_placeholder_path()
            temp_file.write_text(html_content, encoding='utf-8')

            # 加载到WebView
            self.graph_view.load(QUrl.fromLocalFile(str(temp_file.absolute())))
            self.showing_tavern_placeholder = True

            logger.info("酒馆模式占位页面已显示")

        except Exception as e:
            logger.error(f"显示酒馆模式占位页面失败: {e}")



class ModelFetchWorker(QThread):
    fetched = pyqtSignal(object, bool)
    failed = pyqtSignal(str)

    def __init__(self, base_url, api_key, timeout, parent=None):
        super().__init__(parent)
        self.base_url, self.api_key, self.timeout = base_url, api_key, timeout

    def run(self):
        from src.utils.model_catalog import fetch_models
        try:
            models, retried = fetch_models(self.base_url, self.api_key, self.timeout)
            self.fetched.emit(models, retried)
        except ValueError as error:
            self.failed.emit(str(error))
        except Exception:
            self.failed.emit("获取模型失败，请检查接口地址和网络")


class BackendReloadWorker(QThread):
    checked = pyqtSignal(str)

    def __init__(self, port, parent=None):
        super().__init__(parent)
        self.port = port

    def run(self):
        try:
            response = requests.post(f"http://127.0.0.1:{self.port}/system/reload_config", timeout=2)
            data = response.json() if response.ok else {}
            if response.ok and data.get("ok"):
                status = "后端已加载新 LLM 设置" if data.get("llm_configured") else "后端已加载设置，但 LLM 配置不完整"
            elif response.status_code == 404:
                status = "当前后端不支持配置热重载；重启后端后生效"
            else:
                status = f"后端未确认更新（HTTP {response.status_code}）"
        except Exception:
            status = "后端未连接；下次启动或初始化时会读取配置"
        self.checked.emit(status)


class ConfigPage(QWidget):
    """系统配置页面"""

    def __init__(self, parent=None, env_path=None, api_server_port=None):
        super().__init__(parent)
        self.setObjectName("configPage")
        self.env_path = Path(env_path) if env_path is not None else Path(__file__).resolve().parent / '.env'
        self.api_server_port = int(api_server_port if api_server_port is not None else
                                   (dotenv_values(self.env_path).get("API_SERVER_PORT") or 9543))
        self.init_ui()
        self.load_config()
        self.connection_status_manager = QNetworkAccessManager(self)
        self._connection_status_request_id = 0
        self.connection_status_timer = QTimer(self)
        self.connection_status_timer.timeout.connect(self.refresh_connection_status)

    def showEvent(self, event):
        super().showEvent(event)
        self.connection_status_timer.start(5000)
        self.refresh_connection_status()

    def hideEvent(self, event):
        self.connection_status_timer.stop()
        self._connection_status_request_id += 1
        super().hideEvent(event)

    def init_ui(self):
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # 创建主容器
        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)

        # LLM配置组
        llm_group = QGroupBox("LLM模型配置")
        llm_layout = QFormLayout(llm_group)

        self.api_base_url_input = QLineEdit()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.model_input = QComboBox()
        self.model_input.setEditable(True)
        self.fetch_models_button = QPushButton("获取模型")
        self.fetch_models_button.clicked.connect(self.fetch_models)
        self.model_metadata = {}
        self.model_status_label = QLabel("")
        self.model_status_label.setProperty("role", "status")
        self.model_detail_labels = {}
        details = QWidget()
        details_layout = QFormLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        from src.utils.model_catalog import model_details
        for name in model_details({}):
            label = QLabel("未提供（使用服务商默认）")
            label.setWordWrap(True)
            details_layout.addRow(name + ":", label)
            self.model_detail_labels[name] = label
        self.model_input.currentTextChanged.connect(self.update_model_details)
        self.stream_checkbox = QCheckBox("启用流式输出")
        self.embedding_review_checkbox = QCheckBox("启用Embedding向量复核（付费）")
        self.embedding_review_checkbox.setToolTip("仅勾选后才会调用Embedding接口进行语义复核，可能产生额外费用。")

        # LLM参数配置
        self.max_tokens_input = ValueUnitInput([UnitSpec('tokens', 1), UnitSpec('K tokens', 1000)], 100, 32000, decimals=0)
        self.max_tokens_input.setValue(4000)

        self.temperature_input = ValueUnitInput([], 0.0, 2.0, decimals=1)
        self.temperature_input.setValue(0.8)

        self.request_timeout_input = ValueUnitInput([UnitSpec('秒', 1), UnitSpec('分钟', 60)], 30, 600, decimals=0)
        self.request_timeout_input.setValue(180)

        llm_layout.addRow("API接口地址:", self.api_base_url_input)
        llm_layout.addRow("API密钥:", self.api_key_input)
        model_row = QWidget()
        model_row_layout = QHBoxLayout(model_row)
        model_row_layout.setContentsMargins(0, 0, 0, 0)
        model_row_layout.addWidget(self.model_input, 1)
        model_row_layout.addWidget(self.fetch_models_button)
        llm_layout.addRow("默认模型:", model_row)
        llm_layout.addRow("", self.model_status_label)
        llm_layout.addRow("模型详情:", details)
        llm_layout.addRow("最大输出量:", self.max_tokens_input)
        llm_layout.addRow("温度参数:", self.temperature_input)
        llm_layout.addRow("请求超时:", self.request_timeout_input)
        llm_layout.addRow("", self.stream_checkbox)
        llm_layout.addRow("", self.embedding_review_checkbox)

        # 滑动窗口配置组
        window_group = QGroupBox("滑动窗口配置")
        window_layout = QFormLayout(window_group)

        self.window_size_input = ValueUnitInput([UnitSpec('轮', 1)], 2, 20, decimals=0)
        self.window_size_input.setValue(4)

        self.processing_delay_input = ValueUnitInput([UnitSpec('轮', 1)], 0, 10, decimals=0)
        self.processing_delay_input.setValue(1)

        self.enable_conflict_resolution_checkbox = QCheckBox("启用冲突解决")
        self.enable_conflict_resolution_checkbox.setChecked(True)

        window_layout.addRow("窗口大小:", self.window_size_input)
        window_layout.addRow("处理延迟:", self.processing_delay_input)
        window_layout.addRow("", self.enable_conflict_resolution_checkbox)

        # 服务器配置组
        server_group = QGroupBox("服务器配置")
        server_layout = QFormLayout(server_group)

        self.api_server_port_input = QLineEdit()
        self.api_server_port_input.setValidator(QIntValidator(1024, 65535, self))

        self.api_timeout_input = ValueUnitInput([UnitSpec('秒', 1), UnitSpec('分钟', 60)], 5, 60, decimals=0)
        self.api_timeout_input.setValue(15)

        self.health_check_timeout_input = ValueUnitInput([UnitSpec('秒', 1), UnitSpec('分钟', 60)], 3, 30, decimals=0)
        self.health_check_timeout_input.setValue(10)

        server_layout.addRow("API服务器端口:", self.api_server_port_input)
        server_layout.addRow("API请求超时:", self.api_timeout_input)
        server_layout.addRow("健康检查超时:", self.health_check_timeout_input)

        status_group = QGroupBox("连接状态")
        status_layout = QFormLayout(status_group)
        self.plugin_status_label = QLabel("未连接")
        self.backend_status_label = QLabel("未运行")
        for label in (self.plugin_status_label, self.backend_status_label):
            label.setProperty("role", "status")
        status_layout.addRow("插件连接:", self.plugin_status_label)
        status_layout.addRow("后台服务:", self.backend_status_label)

        # UI配置组
        ui_group = QGroupBox("界面配置")
        ui_layout = QFormLayout(ui_group)

        self.max_messages_input = ValueUnitInput([UnitSpec('条', 1)], 100, 5000, decimals=0)
        self.max_messages_input.setValue(1000)

        self.animation_interval_input = ValueUnitInput([UnitSpec('毫秒', 1), UnitSpec('秒', 1000)], 100, 2000, decimals=0)
        self.animation_interval_input.setValue(500)

        self.poll_interval_input = ValueUnitInput([UnitSpec('秒', 1), UnitSpec('分钟', 60)], 1, 10, decimals=0)
        self.poll_interval_input.setValue(3)

        ui_layout.addRow("最大消息数:", self.max_messages_input)
        ui_layout.addRow("动画间隔:", self.animation_interval_input)
        ui_layout.addRow("轮询间隔:", self.poll_interval_input)

        # 系统配置组
        system_group = QGroupBox("系统配置")
        system_layout = QFormLayout(system_group)

        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("INFO")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("\u6696\u6c99\uff08\u6d45\u8272\uff09", "sand")
        self.theme_combo.addItem("\u58a8\u8272\uff08\u6df1\u8272\uff09", "ink")
        system_layout.addRow("\u754c\u9762\u4e3b\u9898:", self.theme_combo)
        system_layout.addRow("日志等级:", self.log_level_combo)

        # 保存按钮
        self.save_button = QPushButton("保存配置")
        self.save_button.setProperty("variant", "primary")
        self.save_button.clicked.connect(self.save_config)



        # 添加到布局
        layout.addWidget(llm_group)
        layout.addWidget(window_group)
        layout.addWidget(server_group)
        layout.addWidget(status_group)
        layout.addWidget(ui_group)
        layout.addWidget(system_group)
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_row.addWidget(self.save_button)
        layout.addLayout(save_row)
        layout.addStretch()

        # 设置滚动区域
        scroll_area.setWidget(main_widget)

        # 设置主布局
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll_area)

    @staticmethod
    def connection_status_from_response(status_code, data):
        if status_code != 200:
            return "未连接", "未运行"
        return ("已连接" if data.get("connected") else "未连接", "运行中")

    def refresh_connection_status(self):
        if not self.isVisible():
            return
        self._connection_status_request_id += 1
        request_id = self._connection_status_request_id
        request = QNetworkRequest(QUrl(f"http://127.0.0.1:{self.api_server_port}/system/plugin_status"))
        request.setTransferTimeout(1000)
        reply = self.connection_status_manager.get(request)
        reply.finished.connect(lambda: self._finish_connection_status(reply, request_id))

    def _finish_connection_status(self, reply, request_id):
        try:
            if request_id != self._connection_status_request_id or not self.isVisible():
                return
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) if reply.error() == QNetworkReply.NoError else None
            data = json.loads(bytes(reply.readAll())) if status == 200 else {}
            plugin, backend = self.connection_status_from_response(status, data)
            self.plugin_status_label.setText(plugin)
            self.backend_status_label.setText(backend)
        except (ValueError, TypeError):
            self.plugin_status_label.setText("未连接")
            self.backend_status_label.setText("未运行")
        finally:
            reply.deleteLater()

    def load_config(self):
        """加载配置"""
        if not self.env_path.exists():
            self.env_path.touch()

        config = dotenv_values(self.env_path)

        # LLM配置
        self.api_base_url_input.setText(config.get("OPENAI_API_BASE_URL", ""))
        self.api_key_input.setText(config.get("OPENAI_API_KEY", ""))
        self.model_input.setCurrentText(config.get("DEFAULT_MODEL", "deepseek-v3.1"))

        # LLM参数配置
        self.max_tokens_input.setValue(int(config.get("MAX_TOKENS", "4000")))
        self.temperature_input.setValue(float(config.get("TEMPERATURE", "0.8")))
        self.request_timeout_input.setValue(int(config.get("REQUEST_TIMEOUT", "180")))

        stream_val = config.get("LLM_STREAM_OUTPUT", "false").lower()
        self.stream_checkbox.setChecked(stream_val in ('true', '1', 't'))
        embedding_review_val = config.get("ENABLE_EMBEDDING_REVIEW", "false").lower()
        self.embedding_review_checkbox.setChecked(embedding_review_val in ('true', '1', 't'))

        # 滑动窗口配置
        self.window_size_input.setValue(int(config.get("SLIDING_WINDOW_SIZE", "4")))
        self.processing_delay_input.setValue(int(config.get("PROCESSING_DELAY", "1")))

        conflict_resolution_val = config.get("ENABLE_CONFLICT_RESOLUTION", "true").lower()
        self.enable_conflict_resolution_checkbox.setChecked(conflict_resolution_val in ('true', '1', 't'))

        # 服务器配置
        self.api_server_port_input.setText(config.get("API_SERVER_PORT", "9543"))
        self.api_timeout_input.setValue(int(config.get("API_TIMEOUT", "15")))
        self.health_check_timeout_input.setValue(int(config.get("HEALTH_CHECK_TIMEOUT", "10")))

        # UI配置
        self.max_messages_input.setValue(int(config.get("MAX_MESSAGES", "1000")))
        self.animation_interval_input.setValue(int(config.get("ANIMATION_INTERVAL", "500")))
        self.poll_interval_input.setValue(int(config.get("POLL_INTERVAL", "3")))

        # 系统配置
        self.log_level_combo.setCurrentText(config.get("LOG_LEVEL", "INFO"))
        resolved_theme = theme.resolve_ui_theme(self.env_path)
        active_theme = theme.current_name() if QApplication.instance() else resolved_theme
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(active_theme))

    def update_model_details(self, model_id):
        from src.utils.model_catalog import model_details
        data = self.model_metadata.get(model_id)
        details = model_details(data) if data is not None else {}
        for name, label in self.model_detail_labels.items():
            label.setText(details.get(name, "未提供（使用服务商默认）"))
        if data is None:
            self.model_status_label.setText("当前模型无元数据")

    def fetch_models(self):
        if not self.request_timeout_input.isValid():
            self._models_failed(f"请求超时：{self.request_timeout_input.errorText()}")
            return
        from src.utils.model_catalog import validate_endpoint
        try:
            base_url, api_key = validate_endpoint(self.api_base_url_input.text(), self.api_key_input.text())
        except ValueError as error:
            self.model_status_label.setText(str(error))
            self.model_status_label.setProperty("status", "danger")
            self.model_status_label.style().unpolish(self.model_status_label)
            self.model_status_label.style().polish(self.model_status_label)
            return
        self.fetch_models_button.setEnabled(False)
        self.fetch_models_button.setText("获取中…")
        self.model_status_label.setText("正在获取模型列表…")
        self.model_fetch_worker = ModelFetchWorker(base_url, api_key, self.request_timeout_input.value(), self)
        self.model_fetch_worker.fetched.connect(self._models_fetched)
        self.model_fetch_worker.failed.connect(self._models_failed)
        self.model_fetch_worker.finished.connect(self._models_fetch_finished)
        self.model_fetch_worker.start()

    def _models_fetched(self, models, retried):
        selected = self.model_input.currentText()
        self.model_metadata = models
        self.model_input.blockSignals(True)
        self.model_input.clear()
        self.model_input.addItems(models)
        self.model_input.setCurrentText(selected)
        self.model_input.blockSignals(False)
        self.update_model_details(selected)
        note = "（原地址返回 404，已通过 /v1/models 获取）" if retried else ""
        self.model_status_label.setText(f"已获取 {len(models)} 个模型{note}")
        self.model_status_label.setProperty("status", "success")
        self.model_status_label.style().unpolish(self.model_status_label)
        self.model_status_label.style().polish(self.model_status_label)

    def _models_failed(self, message):
        self.model_status_label.setText(message)
        self.model_status_label.setProperty("status", "danger")
        self.model_status_label.style().unpolish(self.model_status_label)
        self.model_status_label.style().polish(self.model_status_label)

    def _models_fetch_finished(self):
        self.fetch_models_button.setEnabled(True)
        self.fetch_models_button.setText("获取模型")
        self.model_fetch_worker.deleteLater()

    def _show_save_result(self, backend_status, other_settings_changed):
        message = "配置保存成功！\n" + backend_status
        if other_settings_changed:
            message += "\n其他部分设置可能需要重启应用。"
        QMessageBox.information(self, "成功", message)

    def save_config(self):
        """保存配置；先验证全部数值，避免部分写入 .env。"""
        fields = (
            ("最大输出量", self.max_tokens_input),
            ("温度参数", self.temperature_input),
            ("请求超时", self.request_timeout_input),
            ("滑动窗口", self.window_size_input),
            ("处理延迟", self.processing_delay_input),
            ("API请求超时", self.api_timeout_input),
            ("健康检查超时", self.health_check_timeout_input),
            ("最大消息数", self.max_messages_input),
            ("动画间隔", self.animation_interval_input),
            ("轮询间隔", self.poll_interval_input),
        )
        for label, field in fields:
            if not field.isValid():
                field.number_edit.setFocus()
                QMessageBox.warning(self, "输入无效", f"{label}：{field.errorText()}")
                return
        try:
            previous_config = dotenv_values(self.env_path)
            # LLM配置
            set_key(self.env_path, "OPENAI_API_BASE_URL", self.api_base_url_input.text())
            set_key(self.env_path, "OPENAI_API_KEY", self.api_key_input.text())
            set_key(self.env_path, "DEFAULT_MODEL", self.model_input.currentText())
            set_key(self.env_path, "LLM_STREAM_OUTPUT", str(self.stream_checkbox.isChecked()).lower())
            set_key(self.env_path, "ENABLE_EMBEDDING_REVIEW", str(self.embedding_review_checkbox.isChecked()).lower())

            # LLM参数配置
            set_key(self.env_path, "MAX_TOKENS", str(self.max_tokens_input.value()))
            set_key(self.env_path, "TEMPERATURE", str(self.temperature_input.value()))
            set_key(self.env_path, "REQUEST_TIMEOUT", str(self.request_timeout_input.value()))

            # 滑动窗口配置
            set_key(self.env_path, "SLIDING_WINDOW_SIZE", str(self.window_size_input.value()))
            set_key(self.env_path, "PROCESSING_DELAY", str(self.processing_delay_input.value()))
            set_key(self.env_path, "ENABLE_CONFLICT_RESOLUTION", str(self.enable_conflict_resolution_checkbox.isChecked()).lower())

            # 服务器配置
            set_key(self.env_path, "API_SERVER_PORT", self.api_server_port_input.text())
            set_key(self.env_path, "API_TIMEOUT", str(self.api_timeout_input.value()))
            set_key(self.env_path, "HEALTH_CHECK_TIMEOUT", str(self.health_check_timeout_input.value()))

            # UI配置
            set_key(self.env_path, "MAX_MESSAGES", str(self.max_messages_input.value()))
            set_key(self.env_path, "ANIMATION_INTERVAL", str(self.animation_interval_input.value()))
            set_key(self.env_path, "POLL_INTERVAL", str(self.poll_interval_input.value()))

            # 系统配置
            set_key(self.env_path, "LOG_LEVEL", self.log_level_combo.currentText())
            selected_theme = self.theme_combo.currentData()
            set_key(self.env_path, "UI_THEME", selected_theme)
            theme_changed = theme.needs_switch(selected_theme)
            if theme_changed:
                main_window = self.window()
                if not isinstance(main_window, EchoGraphMainWindow):
                    raise RuntimeError("Config page is not attached to the EchoGraph main window")
                main_window.apply_theme(selected_theme)

            updated_config = dotenv_values(self.env_path)
            other_settings_changed = any(
                previous_config.get(key) != updated_config.get(key)
                for key in previous_config.keys() | updated_config.keys() if key != "UI_THEME"
            )
            from src.utils.config import reload_config, config as live_config
            reload_config(self.env_path)
            main_window = self.window()
            if isinstance(main_window, EchoGraphMainWindow) and hasattr(main_window, "game_engine"):
                main_window.game_engine.grag_agent = (
                    GRAGUpdateAgent(LLMClient()) if live_config.llm.api_key and live_config.llm.base_url else None
                )
            port = self.api_server_port_input.text().strip() or "9543"
            self.save_button.setEnabled(False)
            self.backend_reload_worker = BackendReloadWorker(port, self)
            self.backend_reload_worker.checked.connect(
                lambda status: self._show_save_result(status, other_settings_changed)
            )
            self.backend_reload_worker.finished.connect(lambda: self.save_button.setEnabled(True))
            self.backend_reload_worker.finished.connect(self.backend_reload_worker.deleteLater)
            self.backend_reload_worker.start()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"配置保存失败：{str(e)}")

class EchoGraphMainWindow(QMainWindow):
    """EchoGraph主窗口"""

    def __init__(self, env_path=None):
        super().__init__()

        # 读取配置
        self.env_path = Path(env_path) if env_path is not None else Path(__file__).resolve().parent / '.env'
        config = dotenv_values(self.env_path) if self.env_path.exists() else {}
        self.api_server_port = int(config.get("API_SERVER_PORT", "9543"))

        # 模式切换标志，防止自动初始化干扰
        self.switching_modes = False
        self._mode_switch_generation = 0

        # 初始化核心组件
        self.init_components()

        # 初始化管理器
        self.init_managers()

        # 启动API服务器
        self.start_api_server()
        # 在启动或连接到已有API服务器后，强制关闭酒馆模式，确保默认本地隔离
        try:
            requests.post(f"http://localhost:{self.api_server_port}/system/tavern_mode", json={"active": False}, timeout=3)
        except Exception:
            pass


        # 初始化UI
        self.init_ui()

        # 设置窗口属性
        WindowManager.setup_window(self)

    def apply_theme(self, name):
        WindowManager.apply_theme(QApplication.instance(), name)
        if self.graph_page.showing_tavern_placeholder:
            self.graph_page._show_tavern_mode_placeholder(
                self.graph_page.tavern_session_id or "pending",
                getattr(self.graph_page, "_placeholder_stats", {"graph_nodes": 0, "graph_edges": 0}),
            )
        elif self.graph_page.html_generator.last_graph_data:
            nodes_json, links_json = self.graph_page.html_generator.last_graph_data
            layout_json = json.dumps(self.graph_page.load_graph_layout(), ensure_ascii=False)
            self.graph_page.html_generator.generate_graph_html(nodes_json, links_json, self.graph_page.graph_file_path, layout_json)
            self.graph_page.graph_view.load(QUrl.fromLocalFile(str(self.graph_page.graph_file_path)))
        else:
            self.graph_page.refresh_graph()

    def init_components(self):
        """初始化核心组件"""
        logger.info("初始化EchoGraph核心组件...")

        try:
            # 初始化核心系统 - 本地模式使用独立目录
            base_path = Path(__file__).parent / "data"
            local_mode_path = base_path / "local_mode"  # 本地模式专用目录
            local_mode_path.mkdir(exist_ok=True)

            self.memory = GRAGMemory(
                hot_memory_size=10,
                graph_save_path=str(local_mode_path / "knowledge_graph.graphml"),
                entities_json_path=str(local_mode_path / "entities.json"),  # 本地模式专用路径
                auto_load_entities=True,  # 本地模式需要加载已有的对话数据
                attention_config=ATTENTION_CONFIG.copy(),
            )
            self.perception = PerceptionModule()
            self.rpg_processor = RPGTextProcessor()
            self.validation_layer = ValidationLayer()
            grag_agent = None

            # 默认优先启用LLM Agent做图谱维护，避免纯正则策略误更新。
            try:
                from src.utils.config import config
                if config.llm.api_key and config.llm.base_url:
                    grag_agent = GRAGUpdateAgent(LLMClient())
                    logger.info("🤖 本地模式已启用GRAG Agent。")
                else:
                    logger.warning("⚠️ LLM配置不完整，本地模式将不会自动维护图谱（正则回退已禁用）。")
            except Exception as agent_error:
                logger.warning(f"⚠️ 本地模式GRAG Agent初始化失败: {agent_error}")

            # 创建游戏引擎
            self.game_engine = GameEngine(
                self.memory,
                self.perception,
                self.rpg_processor,
                self.validation_layer,
                grag_agent
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
                logger.info(f"📡 API服务器已在端口 {self.api_server_port} 运行，跳过启动")
                self.api_server_process = None  # 标记为外部进程
                return

            api_server_path = str(Path(__file__).parent / "api_server.py")
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

    def init_ui(self):
        """初始化用户界面"""
        # 创建标签页
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 智能对话页面
        self.play_page = IntegratedPlayPage(self.game_engine)
        self.play_page.api_base_url = f"http://127.0.0.1:{self.api_server_port}"
        self.tabs.addTab(self.play_page, "对话")

        # 知识图谱页面
        self.graph_page = GraphPage(self.memory)
        self.tabs.addTab(self.graph_page, "知识图谱")

        # 系统配置页面
        self.config_page = ConfigPage(env_path=self.env_path, api_server_port=self.api_server_port)
        self.tabs.addTab(self.config_page, "系统配置")

        # 设置对话和知识图谱的联动
        self.setup_cross_page_connections()

    def setup_cross_page_connections(self):
        """设置页面间的联动连接"""
        self._conversation_graph_root = Path(__file__).parent / "data" / "local_conversations" / "graphs"
        self._conversation_graph_root.mkdir(exist_ok=True, parents=True)
        self._active_local_graph_conversation_id: Optional[str] = None

        # 当对话切换时，刷新知识图谱
        self.play_page.conversation_manager.conversation_changed.connect(
            self.on_conversation_changed
        )

        # 启动时对当前会话执行一次图谱附着，避免默认共享同一图谱上下文
        current_conv_id = self.play_page.conversation_manager.current_conversation_id
        if current_conv_id and getattr(self.play_page, 'is_test_mode', True):
            if self.load_conversation_knowledge_graph(current_conv_id):
                self._active_local_graph_conversation_id = current_conv_id
                self.graph_page.refresh_graph()

    @staticmethod
    def _sanitize_conversation_id(conv_id: str) -> str:
        safe_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(conv_id))
        return safe_id.strip("_") or "default"

    def _get_conversation_graph_paths(self, conv_id: str) -> tuple[Path, Path]:
        safe_conv_id = self._sanitize_conversation_id(conv_id)
        conv_graph_dir = self._conversation_graph_root / safe_conv_id
        conv_graph_dir.mkdir(exist_ok=True, parents=True)
        return conv_graph_dir / "knowledge_graph.graphml", conv_graph_dir / "entities.json"

    def _save_conversation_knowledge_graph(self, conv_id: str) -> bool:
        """保存指定对话当前图谱快照"""
        if not conv_id:
            return False
        try:
            graph_path, entities_path = self._get_conversation_graph_paths(conv_id)
            self.memory.graph_save_path = str(graph_path)
            self.memory.set_entities_json_path(str(entities_path))
            self.memory.knowledge_graph.save_graph(str(graph_path))
            self.memory.sync_entities_to_json()
            logger.info(f"💾 已保存对话图谱快照: conv={conv_id} path={graph_path}")
            return True
        except Exception as e:
            logger.error(f"❌ 保存对话图谱快照失败 (conv={conv_id}): {e}")
            return False

    def on_conversation_changed(self, conv_id: str):
        """处理对话切换事件"""
        logger.info(f"对话切换到: {conv_id}")

        # 如果正在切换模式，跳过自动初始化
        if self.switching_modes:
            logger.info("正在切换模式，跳过对话自动初始化")
            return

        # 如果conv_id为空，说明没有剩余对话
        if not conv_id:
            logger.info("没有剩余对话，保持当前状态")
            return

        # 酒馆模式下图谱由后端会话驱动，不进行本地图谱隔离切换
        if not getattr(self.play_page, 'is_test_mode', True):
            logger.info("当前为酒馆模式，跳过本地图谱隔离切换")
            return

        # 先保存离开前对话的图谱快照，再加载目标对话图谱
        previous_conv_id = getattr(self, '_active_local_graph_conversation_id', None)
        if previous_conv_id and previous_conv_id != conv_id:
            self._save_conversation_knowledge_graph(previous_conv_id)

        if not self.load_conversation_knowledge_graph(conv_id):
            logger.warning(f"对话 {conv_id} 的知识图谱加载失败，保持当前图谱")
            return
        self._active_local_graph_conversation_id = conv_id
        self.graph_page.refresh_graph()

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
        """加载对话相关的知识图谱（本地模式下按对话隔离）"""
        if not conv_id:
            return False

        try:
            graph_path, entities_path = self._get_conversation_graph_paths(conv_id)
            self.memory.graph_save_path = str(graph_path)
            self.memory.set_entities_json_path(str(entities_path))

            # 首次升级到“按对话隔离”时，保留历史的本地共享图谱到当前对话
            if (
                not graph_path.exists()
                and not entities_path.exists()
                and getattr(self, "_active_local_graph_conversation_id", None) is None
                and self.memory.knowledge_graph.graph.number_of_nodes() > 0
            ):
                self.memory.knowledge_graph.save_graph(str(graph_path))
                self.memory.sync_entities_to_json()
                logger.info(f"🧭 已将历史共享图谱迁移到当前对话快照: conv={conv_id}")
                return True

            # 切换对话时先清空内存图谱，避免跨对话污染
            self.memory.knowledge_graph.clear()

            if graph_path.exists():
                self.memory.knowledge_graph.load_graph(str(graph_path))
                self.memory.sync_entities_to_json()
                logger.info(f"📥 已加载对话图谱: conv={conv_id} graph={graph_path}")
                return True

            if entities_path.exists():
                self.memory.reload_entities_from_json()
                if self.memory.graph_save_path:
                    self.memory.knowledge_graph.save_graph(self.memory.graph_save_path)
                logger.info(f"📥 从entities快照恢复对话图谱: conv={conv_id} entities={entities_path}")
                return True

            # 没有任何历史快照，创建空隔离图谱
            self.memory.sync_entities_to_json()
            logger.info(f"🆕 对话无图谱快照，已创建空图谱上下文: conv={conv_id}")
            return True
        except Exception as e:
            logger.error(f"❌ 加载对话图谱失败 (conv={conv_id}): {e}")
            return False

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
                f"对话 \"{conv_name}\"还没有开始。\n\n是否要创建默认的奇幻游戏开局来开始你的冒险？\n\n点击\"否\"将保持当前知识图谱状态。",
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
            self.memory.knowledge_graph.save_graph(self.memory.graph_save_path)

            # 刷新图谱显示（已包含更新实体列表和统计）
            self.graph_page.refresh_graph()
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
            return True

        except Exception as e:
            logger.error(f"创建默认游戏开局失败: {e}")
            self.scenario_manager.show_scenario_error_message(self, e)
            return False


    def closeEvent(self, event):
        """关闭事件处理"""
        try:
            if getattr(self.play_page, 'is_test_mode', True):
                active_conv_id = getattr(self, '_active_local_graph_conversation_id', None)
                if active_conv_id:
                    self._save_conversation_knowledge_graph(active_conv_id)
        except Exception as e:
            logger.warning(f"关闭时保存当前对话图谱失败: {e}")

        # 关闭API日志文件
        if hasattr(self, 'api_log_file') and self.api_log_file:
            try:
                logger.info("📝 Closing API log file...")
                self.api_log_file.close()
                self.api_log_file = None
            except Exception as e:
                logger.error(f"❌ Error closing API log file: {e}")

        success = self.cleanup_manager.cleanup_all_resources()
        if success:
            event.accept()
        else:
            event.accept()  # 即使出错也要关闭


def create_app_and_window(env_path=None, process_theme=theme._USE_PROCESS_ENV):
    """Create the real desktop startup UI without entering the event loop."""
    from dotenv import load_dotenv

    cleanup_stale_graph_pages()
    path = Path(env_path) if env_path is not None else Path(__file__).resolve().parent / ".env"
    if process_theme is theme._USE_PROCESS_ENV:
        process_theme = _EXTERNAL_UI_THEME
    selected_theme = theme.resolve_ui_theme(path, process_theme)
    from src.utils.config import reload_config
    reload_config(path)
    os.environ["UI_THEME"] = selected_theme
    app = QApplication(sys.argv)
    app.setApplicationName("EchoGraph")
    app.setApplicationVersion("1.0.0")
    icon_path = Path(__file__).resolve().parent / "assets" / "icons" / "OIG1.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    WindowManager.apply_theme(app, selected_theme)
    window = EchoGraphMainWindow(env_path=path)
    window.show()
    return app, window


def main():
    """主函数"""
    # 导入配置
    external_ui_theme = _EXTERNAL_UI_THEME
    from src.utils.config import config

    # 加载环境变量

    # 配置详细日志系统
    # 清除默认配置
    logger.remove()

    # 从环境变量或配置文件获取日志级别，优先使用环境变量
    log_level = os.getenv("LOG_LEVEL", config.logging.level).upper()

    # 添加控制台输出（使用配置的日志级别）
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=log_level,
        colorize=True
    )

    # 添加文件输出（详细记录）
    logs_dir = Path(__file__).resolve().parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    logger.add(
        str(logs_dir / "echograph_ui_{time:YYYY-MM-DD}.log"),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        level="DEBUG",  # 文件保留DEBUG级别以便调试
        rotation="10 MB",
        retention="7 days",
        compression="zip"
    )

    # 添加专门的酒馆模式日志
    logger.add(
        str(logs_dir / "tavern_mode_{time:YYYY-MM-DD}.log"),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="INFO",
        filter=lambda record: "酒馆" in record["message"] or "tavern" in record["message"].lower() or "" in record["message"],
        rotation="5 MB",
        retention="7 days"
    )

    logger.info("🚀 ========== EchoGraph UI 启动 ==========")
    logger.info(f"📋 Python版本: {sys.version}")
    logger.info(f"📋 启动参数: {sys.argv}")

    # 创建应用
    # 创建主窗口
    try:
        app, window = create_app_and_window(process_theme=external_ui_theme)
        logger.info("🏗️ 创建主窗口...")

        logger.info("✅ EchoGraph UI 启动完成")
        logger.info("🍺 ========== 准备就绪，等待用户操作 ==========")

        # 运行应用
        exit_code = app.exec()

        logger.info("🏁 ========== EchoGraph UI 退出 ==========")
        logger.debug(f"📋 退出代码: {exit_code}")

        sys.exit(exit_code)

    except Exception as e:
        logger.error("💥 ========== EchoGraph UI 启动失败 ==========")
        logger.error(f"📋 异常详情: {e}")
        logger.error(f"📋 完整堆栈: {traceback.format_exc()}")

        QMessageBox.critical(None, "启动错误", f"EchoGraph启动失败：\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
