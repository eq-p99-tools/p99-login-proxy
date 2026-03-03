import logging

import wx
import wx.adv

from p99_sso_login_proxy import config
from p99_sso_login_proxy import eq_config
from p99_sso_login_proxy import updater
from p99_sso_login_proxy import utils

logger = logging.getLogger("taskbar_icon")


class TaskBarIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame
        self.last_tooltip = f"{config.APP_NAME}"

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
        self.last_tooltip = tooltip = tooltip or self.last_tooltip

        using_proxy, _ = eq_config.is_using_proxy()

        if using_proxy and not config.PROXY_ONLY:
            icon_filename = "tray_icon.png"
        elif using_proxy and config.PROXY_ONLY:
            icon_filename = "tray_icon_proxy_only.png"
        else:
            icon_filename = "tray_icon_disabled.png"

        path = utils.find_resource_path(icon_filename)
        if path:
            try:
                icon = wx.Icon(path)
                self.SetIcon(icon, tooltip)
                self.frame.SetIcon(icon)
                return
            except Exception as e:
                logger.warning("Failed to load icon from %s: %s", path, e)

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
        try:
            if not updater.check_update():
                dlg = wx.MessageDialog(
                    self.frame,
                    f"Version: {config.APP_VERSION}\n\n"
                    "There is no update available, you are running the latest version.",
                    "No Update Available", wx.OK | wx.ICON_INFORMATION)
                dlg.ShowModal()
                dlg.Destroy()
        except Exception as e:
            logger.error("Failed to check for updates: %s", e)
            wx.MessageBox(
                f"Failed to check for updates: {e}",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )

    def on_exit(self, event):
        """Exit the application"""
        self.frame.close_application()

    def ShowBalloon(self, title, text, msec=0):
        """Show a balloon notification"""
        if wx.Platform == '__WXMSW__':
            super().ShowBalloon(title, text, msec)
