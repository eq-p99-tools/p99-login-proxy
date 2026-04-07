"""Dark theme: Fusion style, palette, and semantic colors for status UI."""

import ctypes
import logging
import platform
from ctypes import wintypes

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

# Native title bar / window chrome (must match QPalette.Window in apply_dark_theme)
WINDOW_CHROME_RGB = (45, 45, 48)

# Semantic colors tuned for dark backgrounds (labels, table stripes, swatches).
COLOR_SUCCESS = QColor(80, 200, 120)
COLOR_ERROR = QColor(255, 82, 82)
COLOR_DARK_RED = QColor(239, 83, 80)
COLOR_WARNING = QColor(255, 183, 77)
COLOR_MUTED = QColor(158, 158, 158)
COLOR_VALUE_TEXT = QColor(176, 190, 197)
COLOR_ALT_ROW = QColor(48, 52, 58)
# Character table + legend: muted tints for dark UI (still distinct from stripes / each other)
COLOR_ACTIVE_AMBER = QColor(130, 88, 42)
COLOR_ACTIVE_BLUE = QColor(52, 92, 132)

# QTextBrowser changelog surface
CHANGELOG_BG = "#252526"
CHANGELOG_FG = "#d4d4d4"

LOG_LEVEL_COLORS = {
    logging.DEBUG: QColor(120, 144, 156),
    logging.INFO: QColor(236, 239, 241),
    logging.WARNING: QColor(255, 183, 77),
    logging.ERROR: QColor(239, 83, 80),
    logging.CRITICAL: QColor(183, 28, 28),
}

_EXTRA_QSS = """
QGroupBox {
    font-weight: bold;
    border: 1px solid #555;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}
QTabWidget::pane {
    border: 1px solid #555;
    border-radius: 4px;
    top: -1px;
}
QHeaderView::section {
    background-color: #404040;
    color: #e0e0e0;
    padding: 2px 6px;
    border: 1px solid #555;
}
QTableView QTableCornerButton::section {
    border: none;
    background-color: #404040;
}
QTableWidget {
    gridline-color: #4a4a4a;
    background-color: #2a2a2e;
    alternate-background-color: #323236;
}
QTableWidget::item:selected {
    background-color: #0d47a1;
    color: #ffffff;
}
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit, QTextBrowser {
    background-color: #2a2a2e;
    color: #e8e8e8;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 2px 6px;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QPushButton {
    background-color: #3d3d42;
    color: #ececec;
    border: 1px solid #5a5a5a;
    border-radius: 4px;
    padding: 5px 14px;
}
QPushButton:hover {
    background-color: #4a4a52;
}
QPushButton:pressed {
    background-color: #353539;
}
QCheckBox {
    spacing: 8px;
}
QScrollBar:vertical {
    width: 12px;
    background: #2d2d30;
}
QScrollBar::handle:vertical {
    background: #5a5a5a;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #6e6e6e;
}
QScrollBar:horizontal {
    height: 12px;
    background: #2d2d30;
}
QScrollBar::handle:horizontal {
    background: #5a5a5a;
    min-width: 24px;
    border-radius: 4px;
}
"""


def apply_dark_theme(app: QApplication) -> None:
    """Apply Fusion + dark palette and app-wide stylesheet."""
    app.setStyle("Fusion")

    pal = QPalette()
    # Window chrome
    pal.setColor(QPalette.ColorRole.Window, QColor(*WINDOW_CHROME_RGB))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(230, 230, 230))
    # Inputs / views
    pal.setColor(QPalette.ColorRole.Base, QColor(42, 42, 46))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(52, 52, 58))
    pal.setColor(QPalette.ColorRole.Text, QColor(230, 230, 230))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(140, 140, 140))
    # Tooltips
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(60, 60, 65))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(240, 240, 240))
    # Buttons
    pal.setColor(QPalette.ColorRole.Button, QColor(58, 58, 62))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(235, 235, 235))
    pal.setColor(QPalette.ColorRole.BrightText, QColor(255, 80, 80))
    # Links & selection
    pal.setColor(QPalette.ColorRole.Link, QColor(100, 180, 255))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 215))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    # Disabled
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(127, 127, 127))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(127, 127, 127))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(127, 127, 127))

    app.setPalette(pal)
    app.setStyleSheet(_EXTRA_QSS)


def apply_windows_window_frame(widget: QWidget) -> None:
    """Dark native title bar on Windows via DWM (Qt cannot style the OS caption).

    Uses immersive dark mode (Win10 1809+) and optional caption/border tint (Win11)
    to match WINDOW_CHROME_RGB. No-op on other platforms or if APIs are unavailable.
    """
    if platform.system() != "Windows":
        return
    try:
        hwnd = int(widget.winId())
    except (TypeError, ValueError):
        return
    if hwnd == 0:
        return

    dwm = ctypes.windll.dwmapi
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    DWMWA_BORDER_COLOR = 34
    DWMWA_CAPTION_COLOR = 35

    def _set_attr(attr: int, data, size: int) -> None:
        hr = dwm.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(attr),
            data,
            wintypes.DWORD(size),
        )
        if hr != 0:
            logger.debug("DwmSetWindowAttribute attr=%s hr=%#x", attr, hr & 0xFFFFFFFF)

    # Light title bar -> dark (required on Win10/11 for non-UWP HWND)
    dark = ctypes.c_int(1)
    _set_attr(DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark), ctypes.sizeof(dark))

    # Win11+: tint caption and border to match app background (fails gracefully on older OS)
    r, g, b = WINDOW_CHROME_RGB
    colorref = wintypes.DWORD(r | (g << 8) | (b << 16))
    _set_attr(DWMWA_CAPTION_COLOR, ctypes.byref(colorref), ctypes.sizeof(colorref))
    _set_attr(DWMWA_BORDER_COLOR, ctypes.byref(colorref), ctypes.sizeof(colorref))
