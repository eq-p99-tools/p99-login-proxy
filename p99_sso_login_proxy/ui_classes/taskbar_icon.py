import logging

import wx
import wx.adv

from p99_sso_login_proxy import config, eq_config, updater, utils

logger = logging.getLogger("taskbar_icon")


def create_tray_icon(frame):
    """Return a TaskBarIcon, or None if the tray isn't usable."""
    if not wx.adv.TaskBarIcon.IsAvailable():
        logger.warning(
            "System tray not available. On Linux, install "
            "libayatana-appindicator3 (or libappindicator3)"
            " and restart to enable tray icon support."
        )
        return None
    try:
        return TaskBarIcon(frame)
    except Exception:
        logger.warning(
            "Failed to create tray icon", exc_info=True
        )
        return None


class TaskBarIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame
        self.last_tooltip = f"{config.APP_NAME}"
        self._last_icon_filename = None

        self.update_icon()
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_left_dclick)

    def on_left_dclick(self, event):
        if not self.frame.IsShown():
            self.frame.Show()
            self.frame.Raise()

    def CreatePopupMenu(self):
        menu = wx.Menu()

        if self.frame.IsShown():
            visibility_item = menu.Append(wx.ID_ANY, "Hide Application")
            self.Bind(wx.EVT_MENU, self.on_hide, visibility_item)
        else:
            visibility_item = menu.Append(wx.ID_ANY, "Show Application")
            self.Bind(wx.EVT_MENU, self.on_show, visibility_item)

        launch_eq_item = menu.Append(wx.ID_ANY, "Launch EverQuest")
        self.Bind(wx.EVT_MENU, self.frame.on_launch_eq, launch_eq_item)

        update_item = menu.Append(wx.ID_ANY, "Check for Updates")
        self.Bind(wx.EVT_MENU, self.on_check_updates, update_item)

        menu.AppendSeparator()

        exit_item = menu.Append(wx.ID_ANY, "Exit")
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)

        return menu

    def update_icon(self, tooltip=None):
        tooltip = tooltip or self.last_tooltip

        using_proxy, _ = eq_config.is_using_proxy()

        if using_proxy and not config.PROXY_ONLY:
            icon_filename = "tray_icon.png"
        elif using_proxy and config.PROXY_ONLY:
            icon_filename = "tray_icon_proxy_only.png"
        else:
            icon_filename = "tray_icon_disabled.png"

        icon_changed = icon_filename != self._last_icon_filename
        tooltip_changed = tooltip != self.last_tooltip

        if not icon_changed and not tooltip_changed:
            return

        self.last_tooltip = tooltip

        path = utils.find_resource_path(icon_filename)
        if path:
            try:
                icon = wx.Icon(path)
                self.SetIcon(icon, tooltip)
                if icon_changed:
                    self.frame.SetIcon(icon)
                self._last_icon_filename = icon_filename
                return
            except Exception:
                logger.warning("Failed to load icon from %s", path, exc_info=True)

        logger.warning("Could not find or load icon %s", icon_filename)

    def on_show(self, event):
        if not self.frame.IsShown():
            self.frame.Show()
            self.frame.Raise()

    def on_hide(self, event):
        if self.frame.IsShown():
            self.frame.Hide()
            self.ShowBalloon(
                config.APP_NAME,
                f"{config.APP_NAME} is still running in the system tray.",
                2000,
            )

    def on_check_updates(self, event):
        """Check for updates"""
        updater.check_update(notify_no_update=True)

    def on_exit(self, event):
        """Exit the application"""
        self.frame.close_application()

    def ShowBalloon(self, title, text, msec=0):
        """Show a balloon notification"""
        if wx.Platform == "__WXMSW__":
            super().ShowBalloon(title, text, msec)
