"""
EchoGraph UI launcher (modular, preserves original layout/behavior)
- Ensures repo-root on sys.path and loads .env
- Applies dark theme and launches MainWindow
- Includes original signal handling and logging configuration
"""
from __future__ import annotations

import sys
import os
import signal
from pathlib import Path

# Ensure project root is importable (preserve old behavior of run_ui.bak)
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    dotenv_path = REPO_ROOT / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
except Exception:
    # dotenv is optional; continue without failing
    pass

# Import configuration
from src.utils.config import config
from loguru import logger
from version import get_version_info

# High-DPI settings must be set BEFORE creating QApplication
from PySide6.QtCore import Qt, QCoreApplication

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from src.ui.windows.main_window import MainWindow
from src.ui.managers.window_manager import WindowManager


def setup_logging():
    """配置详细日志系统（与原版一致）"""
    # 清除默认配置
    logger.remove()

    # 从环境变量或配置文件获取日志级别，优先使用环境变量
    log_level = os.getenv("LOG_LEVEL", config.logging.level).upper()

    # 添加控制台输出（使用配置的日志级别），遵循级别显示并在控制台做长度截断
    def _console_format(record):
        try:
            level_name = record["level"].name
            msg = record["message"]
            max_len = 500 if level_name == "DEBUG" else 300
            if isinstance(msg, str) and len(msg) > max_len:
                msg = msg[:max_len] + "... [truncated]"
            # Escape braces so Loguru doesn't treat message content as formatting tokens
            if isinstance(msg, str):
                msg = msg.replace("{", "{{").replace("}", "}}")
            return "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} - " + msg + "\n"
        except Exception:
            return "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}\n"

    logger.add(
        sys.stderr,
        format=_console_format,
        level=log_level
    )

    # 确保logs目录存在
    os.makedirs("logs", exist_ok=True)

    # 添加文件输出（详细记录）
    logger.add(
        "logs/echograph_ui_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} | {message}",
        level="DEBUG",  # 文件保留DEBUG级别以便调试
        rotation="10 MB",
        retention="7 days",
        compression="zip"
    )

    # 添加专门的酒馆模式日志
    logger.add(
        "logs/tavern_mode_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
        level="DEBUG",
        filter=lambda record: "tavern" in record["message"].lower() or "酒馆" in record["message"],
        rotation="5 MB",
        retention="3 days"
    )


def set_application_icon(app):
    """设置应用程序图标"""
    try:
        # 尝试多个可能的图标路径，优先使用ICO格式（Windows兼容性更好）
        icon_paths = [
            REPO_ROOT / "assets/icon.ico",
            REPO_ROOT / "assets/icons/OIG1.png",
            REPO_ROOT / "assets/icon.png",
            REPO_ROOT / "icon.ico",
            REPO_ROOT / "icon.png"
        ]

        for icon_path in icon_paths:
            if icon_path.exists():
                logger.info(f"🎨 尝试设置应用程序图标: {icon_path}")
                try:
                    # 先测试文件是否可读
                    with open(icon_path, 'rb') as f:
                        f.read(10)  # 读取前10字节测试

                    icon = QIcon(str(icon_path.resolve()))  # 使用绝对路径
                    if not icon.isNull():
                        app.setWindowIcon(icon)
                        logger.info(f"✅ 应用程序图标设置成功: {icon_path}")
                        return True
                    else:
                        logger.warning(f"⚠️ 图标文件无法解析: {icon_path}")
                except Exception as e:
                    logger.warning(f"⚠️ 加载图标失败 {icon_path}: {e}")
                    continue

        logger.warning("⚠️ 未找到有效的应用程序图标文件")
        return False

    except Exception as e:
        logger.error(f"❌ 设置应用程序图标失败: {e}")
        return False


def main() -> int:
    """主函数（与原版逻辑一致）"""
    # 全局变量用于信号处理
    app = None
    window = None

    def signal_handler(signum, frame):
        """处理CTRL+C等信号（与原版一致）"""
        nonlocal app, window
        logger.info(f"🛑 收到信号 {signum}，正在安全关闭...")
        if window:
            try:
                # 触发正常的关闭流程
                window.close()
            except Exception as e:
                logger.error(f"信号处理中关闭窗口失败: {e}")
        if app:
            try:
                app.quit()
            except Exception as e:
                logger.error(f"信号处理中退出应用失败: {e}")
        sys.exit(0)

    # 注册信号处理器（与原版一致）
    signal.signal(signal.SIGINT, signal_handler)  # CTRL+C
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)  # 终止信号

    # 配置日志系统
    setup_logging()

    # Get version information
    version_info = get_version_info()

    # 记录启动信息
    logger.info(f"🚀 启动 EchoGraph UI v{version_info['version']} ({version_info['codename']})")
    logger.info(f"📂 工作目录: {REPO_ROOT}")
    logger.info(f"📝 日志级别: {os.getenv('LOG_LEVEL', config.logging.level)}")
    logger.info(f"📅 发布日期: {version_info['release_date']}")

    try:

        app = QApplication(sys.argv)
        app.setApplicationName("EchoGraph")
        app.setApplicationVersion(version_info["version"])
        app.setOrganizationName("EchoGraph")

        # 设置应用程序图标
        set_application_icon(app)

        # Apply consistent dark theme (matches original UI appearance)
        WindowManager.apply_dark_theme(app)

        logger.info("✅ Qt应用程序已创建，应用深色主题")

        window = MainWindow()
        window.show()

        # 强制刷新图标显示
        app.processEvents()

        logger.info("✅ 主窗口已显示，进入事件循环")

        return app.exec()

    except Exception as e:
        logger.error(f"❌ 应用程序启动失败: {e}")
        import traceback
        logger.error(f"详细错误: {traceback.format_exc()}")
        return 1
    finally:
        logger.info("🏁 EchoGraph UI 已退出")


if __name__ == "__main__":
    raise SystemExit(main())
