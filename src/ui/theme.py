"""Shared ink and parchment colours for the live desktop UI."""

from pathlib import Path

_ICON_DIR = (Path(__file__).resolve().parents[2] / "assets" / "icons").resolve()
CHECK_ICON = (_ICON_DIR / "check.svg").resolve().as_posix()
RADIO_DOT_ICON = (_ICON_DIR / "radio-dot.svg").resolve().as_posix()

BG_BASE = "#141312"
BG_SURFACE = "#1b1a18"
BG_RAISED = "#23211e"
BG_INPUT = "#181715"
BORDER = "#2c2925"
BORDER_STRONG = "#3a3631"
TEXT_PRIMARY = "#e8e3d9"
TEXT_SECONDARY = "#a8a194"
TEXT_MUTED = "#6f695f"
ACCENT = "#c9a063"
ACCENT_HOVER = "#d8b177"
ACCENT_PRESSED = "#b08a50"
ON_ACCENT = "#1a1409"
ACCENT_SUBTLE = "rgba(201,160,99,0.12)"
DANGER = "#d27565"
DANGER_SUBTLE = "rgba(210,117,101,0.12)"
SUCCESS = "#8fae78"
INFO = "#7f9fbf"
NODE_TYPE_COLORS = {
    "character": ACCENT,
    "location": SUCCESS,
    "item": INFO,
    "event": "#c27b86",
    "concept": "#968cb4",
    "other": "#8a847a",
}


def build_app_stylesheet() -> str:
    return f"""
    QWidget {{ background: transparent; color: {TEXT_PRIMARY}; font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif; font-size: 13px; }}
    QMainWindow, QTabWidget, QTabWidget::pane {{ background: {BG_BASE}; border: 0; }}
    QTabBar {{ background: {BG_BASE}; }}
    QTabBar::tab {{ background: transparent; color: {TEXT_SECONDARY}; border: 0; border-bottom: 2px solid transparent; padding: 10px 18px; min-width: 90px; }}
    QTabBar::tab:selected {{ color: {TEXT_PRIMARY}; border-bottom-color: {ACCENT}; }}
    QTabBar::tab:hover {{ color: {TEXT_PRIMARY}; }}
    QLabel {{ background: transparent; color: {TEXT_PRIMARY}; }}
    QLabel[role="pageTitle"] {{ font-size: 15px; font-weight: 600; }}
    QLabel[role="status"] {{ color: {TEXT_SECONDARY}; font-size: 12px; }}
    QLabel[role="statusDot"] {{ font-size: 12px; color: {TEXT_MUTED}; }}
    QLabel[status="success"] {{ color: {SUCCESS}; }}
    QLabel[status="info"] {{ color: {INFO}; }}
    QLabel[status="danger"] {{ color: {DANGER}; }}
    QLabel[role="stats"] {{ color: {TEXT_SECONDARY}; font-size: 12px; }}
    QGroupBox {{ background: {BG_SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; margin-top: 0; padding: 24px 12px 12px; color: {TEXT_SECONDARY}; font-size: 12px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: border; subcontrol-position: top left; left: 16px; top: 12px; padding: 0; color: {TEXT_SECONDARY}; }}
    QGroupBox[variant="flat"] {{ background: transparent; border: 0; padding: 0; margin: 0; }}
    QPushButton {{ min-height: 30px; background: transparent; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_STRONG}; border-radius: 6px; padding: 0 12px; font-weight: 400; }}
    QPushButton:hover {{ background: {BG_RAISED}; }}
    QPushButton:focus {{ border: 1px solid {ACCENT}; }}
    QPushButton[variant="primary"] {{ background: {ACCENT}; color: {ON_ACCENT}; border-color: {ACCENT}; font-weight: 600; }}
    QPushButton[variant="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
    QPushButton[variant="primary"]:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
    QPushButton[variant="ghost"] {{ border-color: transparent; color: {TEXT_SECONDARY}; }}
    QPushButton[variant="ghost"]:hover {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; }}
    QPushButton[variant="ghost"]:checked {{ background: {ACCENT_SUBTLE}; color: {ACCENT}; }}
    QPushButton[variant="danger"] {{ border-color: rgba(210,117,101,0.35); color: {DANGER}; }}
    QPushButton[variant="danger"]:hover, QPushButton[variant="danger"]:checked {{ background: {DANGER_SUBTLE}; }}
    QPushButton:disabled {{ background: transparent; border-color: {BORDER}; color: {TEXT_MUTED}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height: 18px; background: {BG_INPUT}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_STRONG}; border-radius: 6px; padding: 6px 10px; selection-background-color: {ACCENT_SUBTLE}; selection-color: {TEXT_PRIMARY}; }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
    QComboBox::drop-down {{ width: 22px; border: 0; background: transparent; }}
    QComboBox QAbstractItemView {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_STRONG}; selection-background-color: {ACCENT_SUBTLE}; }}
    QRadioButton, QCheckBox {{ color: {TEXT_SECONDARY}; spacing: 8px; background: transparent; }}
    QRadioButton::indicator, QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {BORDER_STRONG}; background: {BG_INPUT}; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator {{ border-radius: 3px; }}
    QRadioButton::indicator:checked, QCheckBox::indicator:checked {{ border-color: {ACCENT}; background: {ACCENT}; }}
    QCheckBox::indicator:checked {{ image: url("{CHECK_ICON}"); }}
    QRadioButton::indicator:checked {{ image: url("{RADIO_DOT_ICON}"); }}
    QScrollArea, QListWidget, QTreeWidget {{ background: transparent; border: 0; }}
    QListWidget::item, QTreeWidget::item {{ min-height: 28px; padding: 2px 6px; border-radius: 4px; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {BG_RAISED}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: {ACCENT_SUBTLE}; color: {TEXT_PRIMARY}; }}
    QScrollBar:vertical {{ width: 8px; background: transparent; }}
    QScrollBar:horizontal {{ height: 8px; background: transparent; }}
    QScrollBar::handle {{ background: rgba(232,227,217,0.14); border-radius: 4px; min-height: 20px; min-width: 20px; }}
    QScrollBar::handle:hover {{ background: rgba(232,227,217,0.24); }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: 0; }}
    QSplitter::handle {{ background: {BORDER}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}
    QMenu, QToolTip, QMessageBox, QInputDialog, QDialog {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; }}
    QMenu::item:selected {{ background: {ACCENT_SUBTLE}; }}
    ChatDisplayWidget, ChatDisplayWidget QWidget {{ background: {BG_BASE}; }}
    QLabel[role="userBubble"] {{ background: {ACCENT_SUBTLE}; color: {TEXT_PRIMARY}; border: 1px solid rgba(201,160,99,0.25); border-radius: 10px; padding: 14px 18px; font-size: 14px; }}
    QLabel[role="aiBubble"], QLabel[role="loadingBubble"] {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER}; border-radius: 10px; padding: 14px 18px; font-size: 14px; }}
    QLabel[role="loadingBubble"] {{ color: {TEXT_MUTED}; }}
    QFrame[deleteMode="true"]:hover {{ border: 1px solid {DANGER}; border-radius: 10px; }}
    """
