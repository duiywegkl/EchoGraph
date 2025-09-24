"""
状态监控组件
"""

from typing import Dict, Any, Optional, List
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QTextEdit, QScrollArea, QWidget, QFrame
)
from PySide6.QtCore import Signal, QTimer, QDateTime  # [OK] 修正导入
from PySide6.QtGui import QFont, QColor, QPalette
from loguru import logger
from .base import BaseUIComponent

class StatusCard(QFrame):
    """状态卡片组件"""
    
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.setup_ui()
    
    def setup_ui(self):
        """设置UI"""
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)  # [OK] 修正枚举语法
        self.setStyleSheet("""
            QFrame {
                border: 1px solid #ccc;
                border-radius: 8px;
                padding: 8px;
                margin: 4px;
                background-color: #f9f9f9;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel(self.title)
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # 状态文本
        self.status_label = QLabel("等待中...")
        layout.addWidget(self.status_label)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.setLayout(layout)
    
    def update_status(self, status: str, progress: Optional[int] = None):
        """更新状态"""
        self.status_label.setText(status)
        
        if progress is not None:
            self.progress_bar.setValue(progress)
            self.progress_bar.setVisible(True)
        else:
            self.progress_bar.setVisible(False)
    
    def set_status_color(self, color: str):
        """设置状态颜色"""
        self.status_label.setStyleSheet(f"color: {color};")

class StatusMonitor(BaseUIComponent):
    """状态监控组件"""
    
    # 状态监控信号 - 使用Signal替代pyqtSignal
    status_update_requested = Signal(str, str)  # (component, status)
    system_alert = Signal(str, str)  # (level, message)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.status_cards: Dict[str, StatusCard] = {}
        self.log_entries: List[Dict[str, Any]] = []
        self.max_log_entries = 1000
    
    def setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        
        # 状态卡片区域
        self.cards_area = self._create_status_cards_area()
        layout.addWidget(self.cards_area)
        
        # 日志区域
        self.log_area = self._create_log_area()
        layout.addWidget(self.log_area)
        
        self.setLayout(layout)
    
    def _create_status_cards_area(self) -> QScrollArea:
        """创建状态卡片区域"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedHeight(200)
        
        # 容器widget
        container = QWidget()
        self.cards_layout = QHBoxLayout(container)
        
        # 默认状态卡片
        self._create_default_cards()
        
        scroll_area.setWidget(container)
        return scroll_area
    
    def _create_default_cards(self):
        """创建默认状态卡片"""
        default_cards = [
            "API服务器",
            "SillyTavern连接",
            "记忆系统",
            "知识图谱",
            "UI状态"
        ]
        
        for card_name in default_cards:
            self.add_status_card(card_name)
    
    def _create_log_area(self) -> QWidget:
        """创建日志区域"""
        container = QWidget()
        layout = QVBoxLayout(container)
        
        # 日志标题
        log_title = QLabel("系统日志")
        log_title.setFont(QFont("Arial", 12, QFont.Weight.Bold))  # [OK] 修正枚举语法
        layout.addWidget(log_title)
        
        # 日志文本区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(300)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                font-family: 'Consolas', monospace;
                font-size: 10px;
            }
        """)
        layout.addWidget(self.log_text)
        
        return container
    
    def connect_signals(self):
        """连接信号和槽"""
        # 定时更新状态
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_system_status)
        self.update_timer.start(5000)  # 每5秒更新一次
    
    def add_status_card(self, name: str) -> StatusCard:
        """添加状态卡片"""
        if name not in self.status_cards:
            card = StatusCard(name)
            self.status_cards[name] = card
            self.cards_layout.addWidget(card)
            logger.debug(f"[Status] 添加状态卡片: {name}")
        
        return self.status_cards[name]
    
    def update_card_status(self, card_name: str, status: str,
                          progress: Optional[int] = None,
                          color: Optional[str] = None):
        """更新卡片状态"""
        if card_name in self.status_cards:
            card = self.status_cards[card_name]
            card.update_status(status, progress)
            
            if color:
                card.set_status_color(color)
            
            # 记录日志
            self.add_log_entry("INFO", f"{card_name}: {status}")
    
    def add_log_entry(self, level: str, message: str, source: str = "SYSTEM"):
        """添加日志条目"""
        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "source": source,
            "message": message
        }
        
        self.log_entries.append(log_entry)
        
        # 限制日志条目数量
        if len(self.log_entries) > self.max_log_entries:
            self.log_entries = self.log_entries[-self.max_log_entries:]
        
        # 更新日志显示
        self._update_log_display()
        
        # 发出系统警报信号（如果是错误或警告）
        if level in ["ERROR", "WARNING"]:
            self.system_alert.emit(level, message)
    
    def _update_log_display(self):
        """更新日志显示"""
        # 获取最新的50条日志
        recent_logs = self.log_entries[-50:]
        log_html = ""
        
        for entry in recent_logs:
            color = self._get_log_color(entry["level"])
            log_html += f'<span style="color: {color};">[{entry["timestamp"]}] {entry["level"]} - {entry["source"]}: {entry["message"]}</span><br>'
        
        self.log_text.setHtml(log_html)
        
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _get_log_color(self, level: str) -> str:
        """获取日志级别对应的颜色"""
        colors = {
            "DEBUG": "#888888",
            "INFO": "#ffffff",
            "WARNING": "#ffaa00",
            "ERROR": "#ff4444",
            "CRITICAL": "#ff0000"
        }
        return colors.get(level, "#ffffff")
    
    def _update_system_status(self):
        """更新系统状态"""
        try:
            # 这里可以添加实际的系统状态检查逻辑
            # 暂时使用模拟数据
            import requests
            
            # 检查API服务器状态
            try:
                response = requests.get("http://127.0.0.1:8000/health", timeout=2)
                if response.status_code == 200:
                    self.update_card_status("API服务器", "运行正常", 100, "#00aa00")
                else:
                    self.update_card_status("API服务器", "响应异常", 50, "#ffaa00")
            except:
                self.update_card_status("API服务器", "连接失败", 0, "#ff4444")
            
            # 检查SillyTavern连接状态
            tavern_status = self.get_config("tavern_connected", False)
            if tavern_status:
                self.update_card_status("SillyTavern连接", "已连接", 100, "#00aa00")
            else:
                self.update_card_status("SillyTavern连接", "未连接", 0, "#888888")
            
            # 更新UI状态
            self.update_card_status("UI状态", "运行正常", 100, "#00aa00")
            
        except Exception as e:
            logger.error(f"更新系统状态失败: {e}")
    
    def clear_logs(self):
        """清空日志"""
        self.log_entries.clear()
        self.log_text.clear()
        self.add_log_entry("INFO", "日志已清空")
    
    def export_logs(self, file_path: str):
        """导出日志"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# EchoGraph 系统日志\n")
                f.write(f"# 导出时间: {QDateTime.currentDateTime().toString()}\n\n")
                
                for entry in self.log_entries:
                    f.write(f"[{entry['timestamp']}] {entry['level']} - {entry['source']}: {entry['message']}\n")
            
            self.add_log_entry("INFO", f"日志已导出到: {file_path}")
            
        except Exception as e:
            error_msg = f"导出日志失败: {e}"
            logger.error(error_msg)
            self.add_log_entry("ERROR", error_msg)
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        summary = {
            "cards_count": len(self.status_cards),
            "log_entries_count": len(self.log_entries),
            "last_update": QDateTime.currentDateTime().toString(),
            "cards_status": {}
        }
        
        for name, card in self.status_cards.items():
            summary["cards_status"][name] = card.status_label.text()
        
        return summary
