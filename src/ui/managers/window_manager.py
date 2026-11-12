"""
窗口管理器
处理主窗口的设置、样式和布局
"""
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QPalette, QColor, QFont
from src.ui import theme
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
            logger.debug(f"[OK] 窗口图标已设置: {icon_path}")
        else:
            logger.warning(f"[WARN] 图标文件不存在: {icon_path}")
            # 尝试使用系统默认图标
            try:
                from PySide6.QtWidgets import QStyle
                default_icon = main_window.style().standardIcon(QStyle.SP_ComputerIcon)
                main_window.setWindowIcon(default_icon)
                logger.debug("[OK] 使用系统默认图标")
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
    def apply_theme(app, name):
        """Apply the active palette to existing and future widgets."""
        theme.set_theme(name)
        colors = theme.current()
        if app.style().objectName().lower() != "fusion":
            app.setStyle("Fusion")
        palette = QPalette()
        for role, key in (
            (QPalette.Window, "BG_BASE"), (QPalette.WindowText, "TEXT_PRIMARY"),
            (QPalette.Base, "BG_INPUT"), (QPalette.AlternateBase, "BG_SURFACE"),
            (QPalette.Text, "TEXT_PRIMARY"), (QPalette.Button, "BG_SURFACE"),
            (QPalette.ButtonText, "TEXT_PRIMARY"), (QPalette.Highlight, "ACCENT_FILL"),
            (QPalette.HighlightedText, "ON_ACCENT"), (QPalette.PlaceholderText, "TEXT_MUTED"),
        ):
            palette.setColor(role, QColor(colors[key]))
        for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
            palette.setColor(QPalette.Disabled, role, QColor(colors["TEXT_MUTED"]))
        app.setPalette(palette)
        app.setFont(QFont("Microsoft YaHei UI", 10))
        app.setStyleSheet(theme.build_app_stylesheet(colors))
        for widget in app.allWidgets():
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
