"""Trailing eye toggle for password-style QLineEdit fields."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLineEdit


def _password_visibility_icons() -> tuple[QIcon, QIcon]:
    """Icons for masked vs visible (eye with optional slash)."""

    def _pixmap(masked: bool) -> QPixmap:
        size = 20
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = QColor(196, 198, 204)
        painter.setPen(QPen(ink, 1.25))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(3, 6, 14, 9)
        painter.setBrush(ink)
        painter.drawEllipse(8, 8, 4, 5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if masked:
            painter.drawLine(4, 5, 16, 15)
        painter.end()
        return pm

    return QIcon(_pixmap(True)), QIcon(_pixmap(False))


def add_password_visibility_toggle(
    line_edit: QLineEdit,
    *,
    show_tip: str = "Show password",
    hide_tip: str = "Hide password",
) -> None:
    """Add a trailing checkable action: Password echo when off, Normal when on."""
    ic_masked, ic_visible = _password_visibility_icons()
    action = QAction(line_edit)
    action.setCheckable(True)
    action.setChecked(False)
    action.setIcon(ic_masked)
    action.setToolTip(show_tip)
    line_edit.addAction(action, QLineEdit.ActionPosition.TrailingPosition)

    def on_toggled(checked: bool) -> None:
        line_edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
        action.setIcon(ic_visible if checked else ic_masked)
        action.setToolTip(hide_tip if checked else show_tip)

    action.toggled.connect(on_toggled)
