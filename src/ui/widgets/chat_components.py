"""
聊天界面相关组件
包含聊天气泡、聊天显示区域、加载动画等
"""
import time
from typing import List, Dict, Any, Optional
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, 
    QWidget, QSizePolicy, QGraphicsOpacityEffect
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QRect, QTimer
from PySide6.QtGui import QFont, QColor, QTextCursor, QPainter, QPen, QBrush
from loguru import logger


class ChatBubble(QFrame):
    """聊天气泡组件"""
    
    message_clicked = Signal(str)  # 消息被点击时发出信号
    
    def __init__(self, message: str, is_user: bool, color: str = None):
        super().__init__()
        self.message = message
        self.is_user = is_user
        self.color = color
        self.delete_mode = False
        self.setup_ui()
        
    def setup_ui(self):
        """设置界面"""
        self.setFrameStyle(QFrame.Box)
        self.setLineWidth(1)
        
        # 设置气泡样式
        if self.is_user:
            # 用户消息 - 蓝色，右对齐
            bg_color = self.color or "#5865f2"
            text_color = "white"
            alignment = "margin-left: 50px; margin-right: 10px;"
        else:
            # AI消息 - 深灰色，左对齐
            bg_color = self.color or "#4f545c"
            text_color = "#dcddde"
            alignment = "margin-left: 10px; margin-right: 50px;"
        
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                color: {text_color};
                border: none;
                border-radius: 15px;
                padding: 10px 15px;
                margin: 5px;
                {alignment}
            }}
        """)
        
        # 创建布局和标签
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.message_label = QLabel(self.message)
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.message_label.setFont(QFont("Arial", 10))
        layout.addWidget(self.message_label)
        
        # 设置大小策略
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    
    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if self.delete_mode and event.button() == Qt.LeftButton:
            self.message_clicked.emit(self.message)
        super().mousePressEvent(event)
    
    def set_delete_mode(self, enabled: bool):
        """设置删除模式"""
        self.delete_mode = enabled
        if enabled:
            self.setCursor(Qt.PointingHandCursor)
            # 添加删除模式的视觉反馈
            self.setStyleSheet(self.styleSheet() + """
                QFrame:hover {
                    border: 2px solid red;
                }
            """)
        else:
            self.setCursor(Qt.ArrowCursor)
            # 移除悬停效果，重新设置原样式
            self.setup_ui()


class LoadingBubble(QFrame):
    """加载动画气泡"""
    
    def __init__(self):
        super().__init__()
        self.timer = QTimer()
        self.dots = 0
        self.setup_ui()
        
    def setup_ui(self):
        """设置界面"""
        self.setFrameStyle(QFrame.Box)
        self.setLineWidth(1)
        self.setStyleSheet("""
            QFrame {
                background-color: #4f545c;
                color: #dcddde;
                border: none;
                border-radius: 15px;
                padding: 10px 15px;
                margin: 5px;
                margin-left: 10px;
                margin-right: 50px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.loading_label = QLabel("正在思考")
        self.loading_label.setFont(QFont("Arial", 10))
        layout.addWidget(self.loading_label)
        
        # 连接定时器
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(500)  # 每500ms更新一次
        
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    
    def update_animation(self):
        """更新动画"""
        self.dots = (self.dots + 1) % 4
        text = "正在思考" + "." * self.dots
        self.loading_label.setText(text)
    
    def stop_animation(self):
        """停止动画"""
        if self.timer.isActive():
            self.timer.stop()


class ChatDisplayWidget(QScrollArea):
    """聊天显示区域组件"""
    
    def __init__(self):
        super().__init__()
        self.message_widgets: List[Dict[str, Any]] = []
        self.loading_bubble: Optional[LoadingBubble] = None
        self.setup_ui()
    
    def setup_ui(self):
        """设置界面"""
        # 创建滚动内容区域
        scroll_content = QWidget()
        scroll_content.setObjectName("scroll_content")
        
        self.messages_layout = QVBoxLayout(scroll_content)
        self.messages_layout.setSpacing(5)
        self.messages_layout.setContentsMargins(10, 10, 10, 10)
        self.messages_layout.addStretch()  # 添加弹性空间，使消息从上往下排列
        
        # 设置滚动区域
        self.setWidget(scroll_content)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # 设置样式
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
                background-color: #2f3136;
                width: 12px;
                border-radius: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #5865f2;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #4752c4;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
    
    def add_message(self, message: str, is_user: bool, color: str = None):
        """添加消息"""
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
    
    def on_message_clicked(self, message: str):
        """处理消息点击事件"""
        # 删除被点击的消息
        for i, msg_info in enumerate(self.message_widgets):
            if msg_info['message'] == message:
                widget = msg_info['widget']
                self.messages_layout.removeWidget(widget)
                widget.deleteLater()
                self.message_widgets.pop(i)
                logger.info("🗑️ [UI] 删除消息")
                break
    
    def set_delete_mode(self, enabled: bool):
        """设置所有气泡的删除模式"""
        for msg_info in self.message_widgets:
            msg_info['widget'].set_delete_mode(enabled)
    
    def show_loading_animation(self) -> LoadingBubble:
        """显示加载动画"""
        if self.loading_bubble is None:
            self.loading_bubble = LoadingBubble()
            self.messages_layout.addWidget(self.loading_bubble)
            self.scroll_to_bottom()
        return self.loading_bubble
    
    def remove_loading_animation(self):
        """移除加载动画"""
        if self.loading_bubble is not None:
            self.loading_bubble.stop_animation()
            self.messages_layout.removeWidget(self.loading_bubble)
            self.loading_bubble.deleteLater()
            self.loading_bubble = None
    
    def clear_messages(self):
        """清空所有消息"""
        for msg_info in self.message_widgets:
            widget = msg_info['widget']
            self.messages_layout.removeWidget(widget)
            widget.deleteLater()
        
        self.message_widgets.clear()
        self.remove_loading_animation()
        logger.info("🗑️ [UI] 清空聊天记录")
    
    def scroll_to_bottom(self):
        """滚动到底部"""
        QTimer.singleShot(10, lambda: self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        ))
    
    def get_last_user_message(self) -> str:
        """获取最后一条用户消息"""
        for msg_info in reversed(self.message_widgets):
            if msg_info['is_user']:
                return msg_info['message']
        return ""
    
    def remove_last_ai_message(self) -> bool:
        """删除最后一条AI消息"""
        for i in range(len(self.message_widgets) - 1, -1, -1):
            msg_info = self.message_widgets[i]
            if not msg_info['is_user']:
                widget = msg_info['widget']
                self.messages_layout.removeWidget(widget)
                widget.deleteLater()
                self.message_widgets.pop(i)
                logger.info("🔄 [UI] 删除最后一条AI消息以重新生成")
                return True
        return False