"""
聊天组件模块（与原版run_ui.bak完全一致）
包含ChatBubble、LoadingBubble和ChatDisplayWidget
"""
import os
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QWidget,
    QSizePolicy
)
from PySide6.QtGui import QFont


class ChatBubble(QFrame):
    """聊天气泡组件（与原版完全一致）"""

    # 添加信号
    message_clicked = Signal(object)  # 点击消息时发出信号

    def __init__(self, message: str, is_user: bool, color: str = None):
        super().__init__()
        self.message = message
        self.is_user = is_user
        self.delete_mode_enabled = False  # 是否处于删除模式

        # 统一的深色主题配色（与原版一致）
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
        """设置删除模式（与原版一致）"""
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
        """鼠标点击事件（与原版一致）"""
        if self.delete_mode_enabled and event.button() == Qt.LeftButton:
            self.message_clicked.emit(self)
        super().mousePressEvent(event)

    def setup_ui(self):
        """设置UI（与原版完全一致）"""
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
    """加载气泡组件（与原版完全一致）"""

    def __init__(self):
        super().__init__()
        self.dots_count = 1
        self.max_dots = 3
        self.setup_ui()

        # 设置定时器来更新动画
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_animation)
        animation_interval = int(os.getenv("ANIMATION_INTERVAL", "500"))
        self.timer.start(animation_interval)  # 从配置读取动画间隔

    def setup_ui(self):
        """设置UI（与原版完全一致）"""
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
        """更新动画（与原版一致）"""
        dots = "." * self.dots_count
        self.message_label.setText(f"助手正在思考{dots}")
        self.dots_count = (self.dots_count % self.max_dots) + 1

    def stop_animation(self):
        """停止动画（与原版一致）"""
        self.timer.stop()


class ChatDisplayWidget(QScrollArea):
    """聊天显示组件（与原版完全一致）"""

    def __init__(self):
        super().__init__()
        self.messages_layout = QVBoxLayout()
        self.current_loading_bubble = None
        self.message_widgets = []  # 存储所有消息组件的引用
        self.setup_ui()

    def setup_ui(self):
        """设置UI（与原版完全一致）"""
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
        """添加消息（与原版完全一致）"""
        # 限制消息历史大小，防止内存泄漏
        MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "1000"))  # 从配置读取最大消息数

        # 如果超过限制，删除最旧的消息
        if len(self.message_widgets) >= MAX_MESSAGES:
            self.remove_oldest_messages(MAX_MESSAGES // 10)  # 删除10%的旧消息

        # 创建新的消息气泡
        bubble = ChatBubble(message, is_user, color)
        self.message_widgets.append(bubble)
        self.messages_layout.addWidget(bubble)

        # 滚动到底部
        self.scroll_to_bottom()

    def remove_oldest_messages(self, count: int):
        """删除最旧的消息（与原版一致）"""
        for _ in range(min(count, len(self.message_widgets))):
            if self.message_widgets:
                widget = self.message_widgets.pop(0)
                self.messages_layout.removeWidget(widget)
                widget.deleteLater()

    def show_loading(self):
        """显示加载动画（与原版一致）"""
        if self.current_loading_bubble is None:
            self.current_loading_bubble = LoadingBubble()
            self.messages_layout.addWidget(self.current_loading_bubble)
            self.scroll_to_bottom()

    def hide_loading(self):
        """隐藏加载动画（与原版一致）"""
        if self.current_loading_bubble:
            self.current_loading_bubble.stop_animation()
            self.messages_layout.removeWidget(self.current_loading_bubble)
            self.current_loading_bubble.deleteLater()
            self.current_loading_bubble = None

    def clear_messages(self):
        """清空所有消息（与原版一致）"""
        # 清除所有消息组件
        for widget in self.message_widgets:
            self.messages_layout.removeWidget(widget)
            widget.deleteLater()
        self.message_widgets.clear()

        # 清除加载气泡
        self.hide_loading()

    def scroll_to_bottom(self):
        """滚动到底部（与原版一致）"""
        # 使用QTimer.singleShot确保在下一个事件循环中执行
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        ))

    def set_delete_mode(self, enabled: bool):
        """设置删除模式（与原版一致）"""
        for widget in self.message_widgets:
            if hasattr(widget, 'set_delete_mode'):
                widget.set_delete_mode(enabled)

    def remove_last_ai_message(self) -> bool:
        """删除最后一条AI消息（与原版一致）"""
        # 从后往前查找最后一条AI消息
        for i in range(len(self.message_widgets) - 1, -1, -1):
            widget = self.message_widgets[i]
            if hasattr(widget, 'is_user') and not widget.is_user:
                # 找到最后一条AI消息，删除它
                self.messages_layout.removeWidget(widget)
                self.message_widgets.pop(i)
                widget.deleteLater()
                return True
        return False