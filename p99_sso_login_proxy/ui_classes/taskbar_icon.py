import logging
import sys
import threading

import pystray
import wx
from PIL import Image

from p99_sso_login_proxy import config, eq_config, updater, utils

logger = logging.getLogger("taskbar_icon")


def _icon_filename_for_state():
    """Return the tray icon filename matching the current proxy state."""
    using_proxy, _ = eq_config.is_using_proxy()
    if using_proxy and not config.PROXY_ONLY:
        return "tray_icon.png"
    elif using_proxy and config.PROXY_ONLY:
        return "tray_icon_proxy_only.png"
    return "tray_icon_disabled.png"


def create_tray_icon(frame):
    """Return a TaskBarIcon, or None if creation fails."""
    try:
        icon = TaskBarIcon(frame)
        if not icon.is_ready():
            logger.warning("Tray icon did not start within timeout")
            return None
        return icon
    except Exception:
        logger.warning("Failed to create tray icon", exc_info=True)
        return None


class TaskBarIcon:
    """System tray icon backed by pystray."""

    def __init__(self, frame):
        self.frame = frame
        self.last_tooltip = config.APP_NAME
        self._last_icon_filename = None
        self._icon = None
        self._started = threading.Event()
        self._run_error = None

        icon_filename = _icon_filename_for_state()
        image = self._load_image(icon_filename)
        if image is None:
            raise RuntimeError(f"Cannot load tray icon image: {icon_filename}")

        self._last_icon_filename = icon_filename

        self._icon = pystray.Icon(
            config.APP_NAME,
            icon=image,
            title=self.last_tooltip,
            menu=pystray.Menu(
                pystray.MenuItem(
                    lambda item: "Hide Application" if self.frame.IsShown() else "Show Application",
                    self._on_toggle_visibility,
                    default=True,
                ),
                pystray.MenuItem("Launch EverQuest", self._on_launch_eq),
                pystray.MenuItem("Check for Updates", self._on_check_updates),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", self._on_exit),
            ),
        )

        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        self._started.wait(timeout=10)

        if self._run_error:
            raise self._run_error
        if self._started.is_set():
            logger.info("Tray icon started (pystray)")
        else:
            logger.warning("Tray icon startup timed out")

    def _run(self):
        def on_ready(icon):
            icon.visible = True
            self._started.set()

        try:
            self._icon.run(setup=on_ready)
        except Exception as exc:
            logger.error("pystray run failed", exc_info=True)
            self._run_error = exc
            self._started.set()

    @staticmethod
    def _load_image(filename):
        path = utils.find_resource_path(filename)
        if not path:
            logger.warning("Icon file not found: %s", filename)
            return None
        try:
            img = Image.open(path)
            img.load()
            img = img.convert("RGBA")
            return img
        except Exception:
            logger.warning("Failed to load image %s", path, exc_info=True)
            return None

    # -- public interface used by ui.py --

    def is_ready(self):
        """Return True if the tray icon started successfully."""
        return self._started.is_set() and self._run_error is None

    def update_icon(self, tooltip=None):
        if not self._icon:
            return

        tooltip = tooltip or self.last_tooltip
        icon_filename = _icon_filename_for_state()

        icon_changed = icon_filename != self._last_icon_filename
        tooltip_changed = tooltip != self.last_tooltip

        if not icon_changed and not tooltip_changed:
            return

        self.last_tooltip = tooltip
        self._icon.title = tooltip

        if icon_changed:
            image = self._load_image(icon_filename)
            if image:
                self._icon.icon = image
                self._last_icon_filename = icon_filename
                wx.CallAfter(self._update_frame_icon)

    def _update_frame_icon(self):
        path = utils.find_resource_path(self._last_icon_filename)
        if path:
            try:
                self.frame.SetIcon(wx.Icon(path))
            except Exception:
                pass

    def ShowBalloon(self, title, text):
        if not self._icon:
            return

        icon_filename = _icon_filename_for_state()
        image = self._load_image(icon_filename)
        if image:
            self._icon._icon = image
            self._icon._icon_valid = False
            self._last_icon_filename = icon_filename

        try:
            if sys.platform == "win32":
                self._notify_win32(title, text)
            else:
                self._icon.notify(text, title)
        except Exception:
            logger.debug("Notification not supported on this platform", exc_info=True)

    def _notify_win32(self, title, text):
        """Send notification with the current tray icon as the balloon icon.

        Windows 10/11 caches the icon from the original NIM_ADD for the
        toast header's corner icon.  NIM_MODIFY with NIF_ICON updates the
        tray but not the toast cache.  We re-register (NIM_DELETE + NIM_ADD)
        so the toast picks up the current icon, then send NIF_INFO.
        """
        from pystray._util import win32

        self._icon._release_icon()
        self._icon._assert_icon_handle()

        self._icon._hide()
        self._icon._show()

        self._icon._message(
            win32.NIM_MODIFY,
            win32.NIF_INFO,
            szInfo=text,
            szInfoTitle=title,
        )
        self._icon._icon_valid = True

    def RemoveIcon(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    def Destroy(self):
        self.RemoveIcon()

    # -- menu callbacks (called from pystray thread, marshal to wx) --

    def _on_toggle_visibility(self, icon, item):
        wx.CallAfter(self._toggle_frame)

    def _toggle_frame(self):
        if self.frame.IsShown():
            self.frame.Hide()
        else:
            self.frame.Show()
            self.frame.Raise()

    def _on_launch_eq(self, icon, item):
        wx.CallAfter(self.frame.on_launch_eq, None)

    def _on_check_updates(self, icon, item):
        wx.CallAfter(updater.check_update, notify_no_update=True)

    def _on_exit(self, icon, item):
        wx.CallAfter(self.frame.close_application)
