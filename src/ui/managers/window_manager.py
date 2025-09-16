"""
窗口管理器
处理主窗口的设置、样式和布局
"""
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from loguru import logger


class WindowManager:
    """窗口管理器，处理窗口设置和样式"""
    
    @staticmethod
    def setup_window(main_window):
        """设置窗口属性"""
        main_window.setWindowTitle("EchoGraph - 智能角色扮演助手")
        main_window.setMinimumSize(1200, 800)
        main_window.resize(1400, 900)
        
        # 设置应用图标
        # 从 src/ui/managers/window_manager.py 到项目根目录需要回退3级
        icon_path = Path(__file__).parent.parent.parent.parent / "assets" / "icons" / "OIG1.png"
        if icon_path.exists():
            main_window.setWindowIcon(QIcon(str(icon_path)))
            logger.debug(f"✅ 窗口图标已设置: {icon_path}")
        else:
            logger.warning(f"⚠️ 图标文件不存在: {icon_path}")
            # 尝试使用系统默认图标
            try:
                from PySide6.QtWidgets import QStyle
                default_icon = main_window.style().standardIcon(QStyle.SP_ComputerIcon)
                main_window.setWindowIcon(default_icon)
                logger.debug("✅ 使用系统默认图标")
            except Exception as e:
                logger.error(f"❌ 设置默认图标失败: {e}")
        
        # 居中显示
        WindowManager.center_window(main_window)
    
    @staticmethod
    def center_window(window):
        """窗口居中显示"""
        frame_geometry = window.frameGeometry()
        screen = QApplication.primaryScreen().availableGeometry().center()
        frame_geometry.moveCenter(screen)
        window.move(frame_geometry.topLeft())
    
    @staticmethod
    def apply_dark_theme(app):
        """应用深色主题"""
        app.setStyleSheet("""
            /* 主窗口 - Discord风格深色主题 */
            QMainWindow {
                background-color: #2f3136;
                color: #dcddde;
            }
            
            /* 标签页 */
            QTabWidget::pane {
                border: 1px solid #40444b;
                background-color: #36393f;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #40444b;
                color: #dcddde;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                min-width: 100px;
            }
            QTabBar::tab:selected {
                background-color: #5865f2;
                color: #ffffff;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background-color: #4f545c;
            }
            
            /* 输入控件 */
            QTextEdit, QLineEdit {
                background-color: #40444b;
                color: #dcddde;
                border: 1px solid #4f545c;
                border-radius: 4px;
                padding: 8px;
                font-size: 14px;
            }
            QTextEdit:focus, QLineEdit:focus {
                border: 2px solid #5865f2;
            }
            
            /* 下拉框 */
            QComboBox {
                background-color: #40444b;
                color: #dcddde;
                border: 1px solid #4f545c;
                border-radius: 4px;
                padding: 6px 10px;
                min-width: 150px;
            }
            QComboBox:hover {
                border: 1px solid #5865f2;
            }
            QComboBox::drop-down {
                border: none;
                background-color: #5865f2;
                width: 20px;
                border-radius: 2px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #ffffff;
            }
            QComboBox QAbstractItemView {
                background-color: #40444b;
                color: #dcddde;
                selection-background-color: #5865f2;
                border: 1px solid #4f545c;
            }
            
            /* 按钮 */
            QPushButton {
                background-color: #5865f2;
                color: #ffffff;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
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
            
            /* 分组框 */
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
            
            /* 标签 */
            QLabel {
                color: #dcddde;
                font-size: 13px;
            }
            
            /* 列表 */
            QListWidget {
                background-color: #40444b;
                color: #dcddde;
                border: 1px solid #4f545c;
                border-radius: 4px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 6px;
                border-radius: 2px;
            }
            QListWidget::item:selected {
                background-color: #5865f2;
            }
            QListWidget::item:hover {
                background-color: #4f545c;
            }
            
            /* 分割器 */
            QSplitter::handle {
                background-color: #4f545c;
            }
            QSplitter::handle:horizontal {
                width: 3px;
            }
            QSplitter::handle:vertical {
                height: 3px;
            }
            
            /* 单选按钮 */
            QRadioButton {
                color: #dcddde;
                spacing: 8px;
                font-size: 13px;
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
            /* 复选框 */
            QCheckBox {
                color: #dcddde;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 2px;
                border: 2px solid #4f545c;
                background-color: #40444b;
            }
            QCheckBox::indicator:checked {
                background-color: #5865f2;
                border-color: #5865f2;
            }
            QCheckBox::indicator:checked:hover {
                background-color: #4752c4;
            }
            
            /* 滚动条 */
            QScrollBar:vertical {
                background-color: #2f3136;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #202225;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #40444b;
            }
            
            /* 消息框和对话框样式 */
            QMessageBox, QInputDialog, QDialog {
                background-color: #36393f;
                color: #dcddde;
                border: 1px solid #4f545c;
                border-radius: 8px;
            }
            QMessageBox QLabel, QInputDialog QLabel {
                color: #dcddde;
                background-color: transparent;
            }
            QMessageBox QPushButton, QInputDialog QPushButton, QDialog QPushButton {
                background-color: #5865f2;
                color: #ffffff;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                min-width: 80px;
            }
            QMessageBox QPushButton:hover, QInputDialog QPushButton:hover, QDialog QPushButton:hover {
                background-color: #4752c4;
            }
            QMessageBox QPushButton:pressed, QInputDialog QPushButton:pressed, QDialog QPushButton:pressed {
                background-color: #3c45a5;
            }
        """)