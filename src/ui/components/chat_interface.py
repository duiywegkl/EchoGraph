"""
对话界面组件
"""

from typing import Dict, Any, Optional, List
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QSplitter, QLabel, QScrollArea,
    QWidget, QFrame, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox
)
from PySide6.QtCore import Signal, QTimer, QDateTime, Qt  # [OK] 修正导入
from PySide6.QtGui import QFont, QTextCursor
from loguru import logger
from .base import BaseUIComponent

class MessageBubble(QFrame):
    """消息气泡组件"""
    
    def __init__(self, message: str, sender: str, timestamp: str, is_user: bool = False, parent=None):
        super().__init__(parent)
        self.message = message
        self.sender = sender
        self.timestamp = timestamp
        self.is_user = is_user
        self.setup_ui()
    
    def setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        
        # 设置样式
        if self.is_user:
            self.setStyleSheet("""
                QFrame {
                    background-color: #dcf8c6;
                    border: 1px solid #b8d8a7;
                    border-radius: 12px;
                    margin: 4px 20% 4px 4px;
                    padding: 8px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #ffffff;
                    border: 1px solid #e1e1e1;
                    border-radius: 12px;
                    margin: 4px 4px 4px 20%;
                    padding: 8px;
                }
            """)
        
        # 发送者和时间戳
        header_layout = QHBoxLayout()
        sender_label = QLabel(self.sender)
        sender_label.setFont(QFont("Arial", 9, QFont.Weight.Bold))  # [OK] 修正枚举语法
        timestamp_label = QLabel(self.timestamp)
        timestamp_label.setFont(QFont("Arial", 8))
        timestamp_label.setStyleSheet("color: #666666;")
        
        header_layout.addWidget(sender_label)
        header_layout.addStretch()
        header_layout.addWidget(timestamp_label)
        layout.addLayout(header_layout)
        
        # 消息内容
        message_label = QLabel(self.message)
        message_label.setWordWrap(True)
        message_label.setFont(QFont("Arial", 10))
        layout.addWidget(message_label)
        
        self.setLayout(layout)

class ChatInterface(BaseUIComponent):
    """对话界面组件"""
    
    # 对话相关信号 - 使用Signal替代pyqtSignal
    message_sent = Signal(str)  # (message)
    message_received = Signal(str, str, str)  # (message, sender, timestamp)
    typing_started = Signal()
    typing_stopped = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.messages: List[Dict[str, Any]] = []
        self.is_typing = False
    
    def setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        
        # 分割器
        splitter = QSplitter(Qt.Orientation.Vertical)  # [OK] 修正枚举语法
        
        # 消息显示区域
        self.message_area = self._create_message_area()
        splitter.addWidget(self.message_area)
        
        # 输入区域
        self.input_area = self._create_input_area()
        splitter.addWidget(self.input_area)
        
        # 设置分割器比例
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)
        self.setLayout(layout)
    
    def _create_message_area(self) -> QScrollArea:
        """创建消息显示区域"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #cccccc;
                background-color: #f5f5f5;
            }
        """)
        
        # 消息容器
        self.message_container = QWidget()
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.addStretch()
        
        scroll_area.setWidget(self.message_container)
        return scroll_area
    
    def _create_input_area(self) -> QWidget:
        """创建输入区域"""
        container = QWidget()
        layout = QVBoxLayout(container)
        
        # 输入框和发送按钮
        input_layout = QHBoxLayout()
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入消息...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                border: 1px solid #cccccc;
                border-radius: 20px;
                padding: 8px 16px;
                font-size: 12px;
            }
        """)
        
        self.send_button = QPushButton("发送")
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 20px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_button)
        layout.addLayout(input_layout)
        
        # 工具栏
        toolbar_layout = QHBoxLayout()
        self.clear_button = QPushButton("清空对话")
        self.export_button = QPushButton("导出对话")
        self.typing_indicator = QLabel("")
        
        toolbar_layout.addWidget(self.clear_button)
        toolbar_layout.addWidget(self.export_button)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.typing_indicator)
        
        layout.addLayout(toolbar_layout)
        return container
    
    def connect_signals(self):
        """连接信号和槽"""
        # 发送消息
        self.send_button.clicked.connect(self._send_message)
        self.input_field.returnPressed.connect(self._send_message)
        
        # 工具栏
        self.clear_button.clicked.connect(self.clear_messages)
        self.export_button.clicked.connect(self.export_messages)
        
        # 输入监听
        self.input_field.textChanged.connect(self._on_text_changed)
    
    def _send_message(self):
        """发送消息"""
        message = self.input_field.text().strip()
        if message:
            timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
            self.add_message(message, "用户", timestamp, is_user=True)
            self.message_sent.emit(message)
            self.input_field.clear()
    
    def _on_text_changed(self, text: str):
        """输入文本变化处理"""
        if text and not self.is_typing:
            self.is_typing = True
            self.typing_started.emit()
        elif not text and self.is_typing:
            self.is_typing = False
            self.typing_stopped.emit()
    
    def add_message(self, message: str, sender: str, timestamp: str, is_user: bool = False):
        """添加消息"""
        # 创建消息气泡
        bubble = MessageBubble(message, sender, timestamp, is_user)
        
        # 插入到布局中（在stretch之前）
        self.message_layout.insertWidget(self.message_layout.count() - 1, bubble)
        
        # 记录消息
        message_data = {
            "message": message,
            "sender": sender,
            "timestamp": timestamp,
            "is_user": is_user
        }
        self.messages.append(message_data)
        
        # 滚动到底部
        QTimer.singleShot(100, self._scroll_to_bottom)
        logger.debug(f"[Chat] 添加消息: {sender} - {message[:50]}...")
    
    def add_system_message(self, message: str):
        """添加系统消息"""
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        self.add_message(message, "系统", timestamp, is_user=False)
    
    def add_assistant_message(self, message: str):
        """添加助手消息"""
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        self.add_message(message, "助手", timestamp, is_user=False)
    
    def show_typing_indicator(self, sender: str = "助手"):
        """显示正在输入指示器"""
        self.typing_indicator.setText(f"{sender} 正在输入...")
        self.typing_indicator.setStyleSheet("color: #666666; font-style: italic;")
    
    def hide_typing_indicator(self):
        """隐藏正在输入指示器"""
        self.typing_indicator.setText("")
    
    def _scroll_to_bottom(self):
        """滚动到底部"""
        scrollbar = self.message_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_messages(self):
        """清空消息"""
        reply = self._show_confirmation("确认清空所有对话吗？")
        if reply:
            # 清除所有消息气泡
            for i in reversed(range(self.message_layout.count() - 1)):
                child = self.message_layout.itemAt(i).widget()
                if child:
                    child.deleteLater()
            
            self.messages.clear()
            self.add_system_message("对话已清空")
            logger.info("[Chat] 对话已清空")
    
    def export_messages(self):
        """导出对话"""
        if not self.messages:
            self._show_message("没有对话内容可导出")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出对话", "chat_export.txt", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("# EchoGraph 对话导出\n")
                    f.write(f"# 导出时间: {QDateTime.currentDateTime().toString()}\n\n")
                    
                    for msg in self.messages:
                        f.write(f"[{msg['timestamp']}] {msg['sender']}: {msg['message']}\n")
                
                self.add_system_message(f"对话已导出到: {file_path}")
                logger.info(f"[Chat] 对话已导出到: {file_path}")
                
            except Exception as e:
                error_msg = f"导出对话失败: {e}"
                logger.error(error_msg)
                self._show_message(error_msg, is_error=True)
    
    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """获取对话历史"""
        return self.messages.copy()
    
    def load_conversation_history(self, messages: List[Dict[str, Any]]):
        """加载对话历史"""
        self.clear_messages()
        for msg in messages:
            self.add_message(
                msg["message"],
                msg["sender"], 
                msg["timestamp"],
                msg.get("is_user", False)
            )
    
    def _show_confirmation(self, message: str) -> bool:
        """显示确认对话框"""
        reply = QMessageBox.question(
            self, "确认", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,  # [OK] 修正枚举语法
            QMessageBox.StandardButton.No
        )
        return reply == QMessageBox.StandardButton.Yes
    
    def _show_message(self, message: str, is_error: bool = False):
        """显示消息框"""
        if is_error:
            QMessageBox.critical(self, "错误", message)
        else:
            QMessageBox.information(self, "提示", message)
