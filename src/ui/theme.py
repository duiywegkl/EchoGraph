"""Shared palettes for the live desktop and graph UI."""

import os
from pathlib import Path

from dotenv import dotenv_values

_ICON_DIR = (Path(__file__).resolve().parents[2] / "assets" / "icons").resolve()
PALETTES = {
    "sand": {
        "BG_BASE": "#FFFBE9", "BG_SURFACE": "#F8F0DC", "BG_RAISED": "#F1E4CA",
        "BG_INPUT": "#FFFDF6", "BORDER": "#E3CAA5", "BORDER_STRONG": "#CEAB93",
        "TEXT_PRIMARY": "#3E2F24", "TEXT_SECONDARY": "#6B5444", "TEXT_MUTED": "#8F7764",
        "ACCENT": "#AD8B73", "ACCENT_TEXT": "#7D5F4B", "ACCENT_FILL": "#8C6B55",
        "ACCENT_HOVER": "#7D5F4B", "ACCENT_PRESSED": "#6E5341", "ON_ACCENT": "#FFFBE9",
        "ACCENT_SUBTLE": "rgba(173,139,115,0.16)", "DANGER": "#A14E3B",
        "DANGER_SUBTLE": "rgba(164,80,61,0.10)", "SUCCESS": "#566E41", "INFO": "#4B697F",
        "EDGE": "rgba(62,47,36,0.30)", "EDGE_HIGHLIGHT": "rgba(62,47,36,0.70)",
        "GRID": "rgba(62,47,36,0.07)", "SHADOW": "rgba(62,47,36,0.08)",
        "OVERLAY": "rgba(62,47,36,0.28)", "SCROLLBAR": "rgba(62,47,36,0.18)",
        "SCROLLBAR_HOVER": "rgba(62,47,36,0.30)",
        "USER_BORDER": "rgba(173,139,115,0.35)",
        "NODE_TYPE_COLORS": {
            "character": "#A06A50", "location": "#6F8A5A", "item": "#557C96",
            "event": "#A8574F", "concept": "#7E6F9E", "other": "#9C8C7C",
        },
    },
    "ink": {
        "BG_BASE": "#141312", "BG_SURFACE": "#1b1a18", "BG_RAISED": "#23211e",
        "BG_INPUT": "#181715", "BORDER": "#2c2925", "BORDER_STRONG": "#3a3631",
        "TEXT_PRIMARY": "#e8e3d9", "TEXT_SECONDARY": "#a8a194", "TEXT_MUTED": "#6f695f",
        "ACCENT": "#c9a063", "ACCENT_TEXT": "#c9a063", "ACCENT_FILL": "#c9a063",
        "ACCENT_HOVER": "#d8b177", "ACCENT_PRESSED": "#b08a50", "ON_ACCENT": "#1a1409",
        "ACCENT_SUBTLE": "rgba(201,160,99,0.12)", "DANGER": "#d27565",
        "DANGER_SUBTLE": "rgba(210,117,101,0.12)", "SUCCESS": "#8fae78", "INFO": "#7f9fbf",
        "EDGE": "rgba(232,227,217,0.32)", "EDGE_HIGHLIGHT": "rgba(232,227,217,0.75)",
        "GRID": "rgba(232,227,217,0.05)", "SHADOW": "rgba(0,0,0,0.3)",
        "OVERLAY": "rgba(0,0,0,0.55)", "SCROLLBAR": "rgba(232,227,217,0.14)",
        "SCROLLBAR_HOVER": "rgba(232,227,217,0.24)",
        "USER_BORDER": "rgba(201,160,99,0.35)",
        "NODE_TYPE_COLORS": {
            "character": "#c9a063", "location": "#8fae78", "item": "#7f9fbf",
            "event": "#c27b86", "concept": "#968cb4", "other": "#8a847a",
        },
    },
}

_theme = "sand"
_USE_PROCESS_ENV = object()


def resolve_ui_theme(env_path, process_value=_USE_PROCESS_ENV) -> str:
    """Resolve UI_THEME: process environment, then the given .env, then sand.

    An explicit process variable wins, even when invalid (which falls back to sand).
    Pass process_value=None when the caller has already captured an unset variable.
    """
    if process_value is _USE_PROCESS_ENV:
        process_value = os.environ.get("UI_THEME")
    value = process_value
    if value is None:
        path = Path(env_path)
        value = dotenv_values(path).get("UI_THEME") if path.is_file() else None
    name = str(value or "").strip().strip("\"'").strip().lower()
    return name if name in PALETTES else "sand"


def get_theme(name=None):
    """Return a palette; missing or invalid settings use sand."""
    return PALETTES.get(name if name is not None else _theme, PALETTES["sand"])


def current():
    return get_theme()


def current_name() -> str:
    return _theme


def needs_switch(selected_name: str) -> bool:
    """Decide a live switch by the active palette name."""
    return current_name() != selected_name


def set_theme(name):
    global _theme
    _theme = name if name in PALETTES else "sand"
    return _theme


def node_type_colors():
    return current()["NODE_TYPE_COLORS"]


def css_variables(palette=None):
    palette = palette or current()
    variables = {key.lower().replace("_", "-"): value for key, value in palette.items()
                 if key != "NODE_TYPE_COLORS"}
    variables.update(palette["NODE_TYPE_COLORS"])
    return ":root {\n" + "\n".join(f"  --{key}: {value};" for key, value in variables.items()) + "\n}"

def build_app_stylesheet(palette=None) -> str:
    palette = palette or current()
    BG_BASE = palette["BG_BASE"]
    BG_SURFACE = palette["BG_SURFACE"]
    BG_RAISED = palette["BG_RAISED"]
    BG_INPUT = palette["BG_INPUT"]
    BORDER = palette["BORDER"]
    BORDER_STRONG = palette["BORDER_STRONG"]
    TEXT_PRIMARY = palette["TEXT_PRIMARY"]
    TEXT_SECONDARY = palette["TEXT_SECONDARY"]
    TEXT_MUTED = palette["TEXT_MUTED"]
    ACCENT = palette["ACCENT"]
    ACCENT_TEXT = palette["ACCENT_TEXT"]
    ACCENT_FILL = palette["ACCENT_FILL"]
    ACCENT_HOVER = palette["ACCENT_HOVER"]
    ACCENT_PRESSED = palette["ACCENT_PRESSED"]
    ON_ACCENT = palette["ON_ACCENT"]
    ACCENT_SUBTLE = palette["ACCENT_SUBTLE"]
    DANGER = palette["DANGER"]
    DANGER_SUBTLE = palette["DANGER_SUBTLE"]
    SUCCESS = palette["SUCCESS"]
    INFO = palette["INFO"]
    palette_name = "ink" if palette is PALETTES["ink"] else "sand"
    CHECK_ICON = (_ICON_DIR / f"check-{palette_name}.svg").as_posix()
    RADIO_DOT_ICON = (_ICON_DIR / f"radio-dot-{palette_name}.svg").as_posix()
    CHEVRON_DOWN = (_ICON_DIR / f"chevron-down-{palette_name}.svg").as_posix()
    CHEVRON_UP = (_ICON_DIR / f"chevron-up-{palette_name}.svg").as_posix()
    CHEVRON_DISABLED = (_ICON_DIR / f"chevron-down-{palette_name}-disabled.svg").as_posix()
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
    QPushButton[variant="primary"] {{ background: {ACCENT_FILL}; color: {ON_ACCENT}; border-color: {ACCENT_FILL}; font-weight: 600; }}
    QPushButton[variant="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
    QPushButton[variant="primary"]:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
    QPushButton[variant="ghost"] {{ border-color: transparent; color: {TEXT_SECONDARY}; }}
    QPushButton[variant="ghost"]:hover {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; }}
    QPushButton[variant="ghost"]:checked {{ background: {ACCENT_SUBTLE}; color: {ACCENT_TEXT}; }}
    QPushButton[variant="danger"] {{ border-color: {DANGER}; color: {DANGER}; }}
    QPushButton[variant="danger"]:hover, QPushButton[variant="danger"]:checked {{ background: {DANGER_SUBTLE}; }}
    QPushButton:disabled {{ background: transparent; border-color: {BORDER}; color: {TEXT_MUTED}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height: 18px; background: {BG_INPUT}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_STRONG}; border-radius: 6px; padding: 6px 10px; selection-background-color: {ACCENT_SUBTLE}; selection-color: {TEXT_PRIMARY}; }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
    QComboBox {{ padding-right: 34px; }}
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: right center; width: 26px; border: 0; border-left: 1px solid {BORDER}; background: transparent; }}
    QComboBox::drop-down:hover {{ background: {BG_RAISED}; }}
    QComboBox::down-arrow {{ image: url("{CHEVRON_DOWN}"); width: 12px; height: 12px; }}
    QComboBox::down-arrow:on {{ image: url("{CHEVRON_UP}"); }}
    QComboBox::down-arrow:disabled {{ image: url("{CHEVRON_DISABLED}"); }}
    QLineEdit#valueUnitNumber[invalid="true"] {{ border-color: {DANGER}; background: {DANGER_SUBTLE}; }}
    QLineEdit#valueUnitNumber[invalid="true"]:focus {{ border-color: {DANGER}; }}
    QAbstractSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: 0; border-left: 1px solid {BORDER}; background: transparent; }}
    QAbstractSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: 0; border-left: 1px solid {BORDER}; background: transparent; }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {BG_RAISED}; }}
    QAbstractSpinBox::up-arrow {{ image: url("{CHEVRON_UP}"); width: 10px; height: 10px; }}
    QAbstractSpinBox::down-arrow {{ image: url("{CHEVRON_DOWN}"); width: 10px; height: 10px; }}
    QComboBox QAbstractItemView {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_STRONG}; selection-background-color: {ACCENT_SUBTLE}; }}
    QRadioButton, QCheckBox {{ color: {TEXT_SECONDARY}; spacing: 8px; background: transparent; }}
    QRadioButton::indicator, QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {BORDER_STRONG}; background: {BG_INPUT}; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator {{ border-radius: 3px; }}
    QRadioButton::indicator:checked, QCheckBox::indicator:checked {{ border-color: {ACCENT_FILL}; background: {ACCENT_FILL}; }}
    QCheckBox::indicator:checked {{ image: url("{CHECK_ICON}"); }}
    QRadioButton::indicator:checked {{ image: url("{RADIO_DOT_ICON}"); }}
    QScrollArea, QListWidget, QTreeWidget {{ background: transparent; border: 0; }}
    QListWidget::item, QTreeWidget::item {{ min-height: 28px; padding: 2px 6px; border-radius: 4px; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {BG_RAISED}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: {ACCENT_SUBTLE}; color: {TEXT_PRIMARY}; }}
    QScrollBar:vertical {{ width: 8px; background: transparent; }}
    QScrollBar:horizontal {{ height: 8px; background: transparent; }}
    QScrollBar::handle {{ background: {palette['SCROLLBAR']}; border-radius: 4px; min-height: 20px; min-width: 20px; }}
    QScrollBar::handle:hover {{ background: {palette['SCROLLBAR_HOVER']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: 0; }}
    QSplitter::handle {{ background: {BORDER}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}
    QMenu, QToolTip, QMessageBox, QInputDialog, QDialog {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; }}
    QMenu::item:selected {{ background: {ACCENT_SUBTLE}; }}
    ChatDisplayWidget, ChatDisplayWidget QWidget {{ background: {BG_BASE}; }}
    QLabel[role="userBubble"] {{ background: {ACCENT_SUBTLE}; color: {TEXT_PRIMARY}; border: 1px solid {palette['USER_BORDER']}; border-radius: 10px; padding: 14px 18px; font-size: 14px; }}
    QFrame[role="chatRow"], QFrame[role="loadingRow"] {{ background: transparent; border: 0; padding: 0; }}
    QLabel[role="aiBubble"], QLabel[role="loadingBubble"] {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER}; border-radius: 10px; padding: 14px 18px; font-size: 14px; }}
    QLabel[role="loadingBubble"] {{ color: {TEXT_MUTED}; }}
    QLabel[deleteMode="true"]:hover {{ border: 1px solid {DANGER}; }}
    """
