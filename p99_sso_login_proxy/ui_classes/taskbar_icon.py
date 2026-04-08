import logging

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from p99_sso_login_proxy import config, eq_config, updater, utils

logger = logging.getLogger("taskbar_icon")


def _icon_filename_for_state():
    """Return the tray icon filename matching the current proxy state."""
    using_proxy, _ = eq_config.is_using_proxy()
    if using_proxy and not config.PROXY_ONLY:
        return "tray_icon.png"
    if using_proxy and config.PROXY_ONLY:
        return "tray_icon_proxy_only.png"
    return "tray_icon_disabled.png"


def _load_qicon(filename: str) -> QIcon:
    path = utils.find_resource_path(filename)
    if not path:
        logger.warning("Icon file not found: %s", filename)
        return QIcon()
    try:

        def _load():
            return QIcon(path)

        return utils.retry_file_io(_load)
    except Exception:
        logger.warning("Failed to load icon %s", path, exc_info=True)
        return QIcon()


def create_tray_icon(frame: QWidget):
    """Return a TaskBarIcon, or None if creation fails."""
    try:
        return TaskBarIcon(frame)
    except Exception:
        logger.warning("Failed to create tray icon", exc_info=True)
        return None


class TaskBarIcon:
    """System tray icon using Qt."""

    def __init__(self, frame: QWidget):
        self.frame = frame
        self.last_tooltip = config.APP_NAME
        self._last_icon_filename = None

        icon_filename = _icon_filename_for_state()
        self._last_icon_filename = icon_filename
        self._tray = QSystemTrayIcon(_load_qicon(icon_filename), parent=frame)
        self._tray.setToolTip(self.last_tooltip)

        self._menu = QMenu()
        self._toggle_action = QAction("", frame)
        self._toggle_action.triggered.connect(self._toggle_frame)
        self._menu.addAction(self._toggle_action)

        launch = QAction("Launch EverQuest", frame)
        launch.triggered.connect(lambda: self.frame.on_launch_eq())
        self._menu.addAction(launch)

        check = QAction("Check for Updates", frame)
        check.triggered.connect(lambda: updater.check_update(notify_no_update=True))
        self._menu.addAction(check)

        self._menu.addSeparator()

        exit_act = QAction("Exit", frame)
        exit_act.triggered.connect(self.frame.close_application)
        self._menu.addAction(exit_act)

        self._menu.aboutToShow.connect(self._update_toggle_label)
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()
        logger.info("Tray icon started (Qt QSystemTrayIcon)")

    def _update_toggle_label(self):
        self._toggle_action.setText("Hide Application" if self.frame.isVisible() else "Show Application")

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_frame()

    def is_ready(self):
        """Return True if the tray icon is available (always True for Qt)."""
        return self._tray is not None

    def update_icon(self, tooltip=None):
        if not self._tray:
            return

        tooltip = tooltip or self.last_tooltip
        icon_filename = _icon_filename_for_state()

        icon_changed = icon_filename != self._last_icon_filename
        tooltip_changed = tooltip != self.last_tooltip

        if not icon_changed and not tooltip_changed:
            return

        self.last_tooltip = tooltip
        self._tray.setToolTip(tooltip)

        if icon_changed:
            self._tray.setIcon(_load_qicon(icon_filename))
            self._last_icon_filename = icon_filename
            path = utils.find_resource_path(self._last_icon_filename)
            if path:
                try:
                    self.frame.setWindowIcon(_load_qicon(self._last_icon_filename))
                except Exception:
                    logger.debug("Could not set frame window icon", exc_info=True)

    def ShowBalloon(self, title, text):
        if not self._tray:
            return
        try:
            self._tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 5000)
        except Exception:
            logger.debug("Tray message not supported", exc_info=True)

    def RemoveIcon(self):
        if self._tray:
            self._tray.hide()
            self._tray = None

    def Destroy(self):
        self.RemoveIcon()

    def _toggle_frame(self):
        if self.frame.isVisible():
            self.frame.hide()
        else:
            self.frame.show()
            self.frame.raise_()
            self.frame.activateWindow()
