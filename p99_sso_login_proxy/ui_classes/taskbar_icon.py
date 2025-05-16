import os
import sys

import wx
import wx.adv

from p99_sso_login_proxy import config
from p99_sso_login_proxy import eq_config
from p99_sso_login_proxy import updater


class TaskBarIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame
        self.last_tooltip = f"{config.APP_NAME}"
        
        # Set initial icon
        self.update_icon()
        
        # Bind events
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_left_dclick)
    
    # Handle double-click on the taskbar icon
    def on_left_dclick(self, event):
        if not self.frame.IsShown():
            self.frame.Show()
            self.frame.Raise()
    
    # Create the popup menu for the taskbar icon
    def CreatePopupMenu(self):
        menu = wx.Menu()
        
        # Show/Hide application menu item
        if self.frame.IsShown():
            visibility_item = menu.Append(wx.ID_ANY, "Hide Application")
            self.Bind(wx.EVT_MENU, self.on_hide, visibility_item)
        else:
            visibility_item = menu.Append(wx.ID_ANY, "Show Application")
            self.Bind(wx.EVT_MENU, self.on_show, visibility_item)
        
        # Add Launch EverQuest menu item
        launch_eq_item = menu.Append(wx.ID_ANY, "Launch EverQuest")
        self.Bind(wx.EVT_MENU, self.frame.on_launch_eq, launch_eq_item)
        
        # Add update menu item
        update_item = menu.Append(wx.ID_ANY, "Check for Updates")
        self.Bind(wx.EVT_MENU, self.on_check_updates, update_item)
        
        menu.AppendSeparator()
        
        exit_item = menu.Append(wx.ID_ANY, "Exit")
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        
        return menu
    
    # Update the menu (called when update status changes)
    def update_menu(self):
        # Force the menu to be rebuilt next time it's shown
        if wx.Platform == '__WXMSW__':
            self.PopupMenu(self.CreatePopupMenu())
            # Hide the menu immediately
            wx.CallAfter(self.PopupMenu, None)
    
    # Update the tray icon based on proxy status
    def update_icon(self, tooltip=None):
        self.last_tooltip = tooltip = tooltip or self.last_tooltip
        # Get current proxy status directly from eq_config
        using_proxy, _ = eq_config.is_using_proxy()
        
        # Choose the appropriate icon filename
        if using_proxy and not config.PROXY_ONLY:
            icon_filename = "tray_icon.png"
        elif using_proxy and config.PROXY_ONLY:
            icon_filename = "tray_icon_proxy_only.png"
        else:
            icon_filename = "tray_icon_disabled.png"
        
        # Try multiple possible locations for the icon file
        icon_paths = [
            # When running from source
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", icon_filename),
            # When running from PyInstaller bundle
            os.path.join(os.path.dirname(sys.executable), icon_filename),
            # Current directory
            icon_filename
        ]
        
        # Try to load the icon from each possible path
        for path in icon_paths:
            if os.path.exists(path):
                try:
                    icon = wx.Icon(path)
                    self.SetIcon(icon, tooltip)
                    self.frame.SetIcon(icon)
                    return  # Successfully set the icon
                except Exception as e:
                    print(f"Failed to load icon from {path}: {e}")
        
        # If we get here, we couldn't find or load the icon
        print(f"Warning: Could not find or load icon {icon_filename}")
    
    # Show the main window
    def on_show(self, event):
        if not self.frame.IsShown():
            self.frame.Show()
            self.frame.Raise()
    
    # Hide the main window
    def on_hide(self, event):
        if self.frame.IsShown():
            self.frame.Hide()
            # Show notification when hiding
            self.ShowBalloon(
                config.APP_NAME,
                f"{config.APP_NAME} is still running in the system tray.",
                2000  # Show for 2 seconds
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
            print(f"[UI] Failed to check for updates: {e}")
            wx.MessageBox(
                f"Failed to check for updates: {e}",
                "Error",
                wx.OK | wx.ICON_ERROR
            )
    
    # These methods are used by the tray icon menu
    def on_exit(self, event):
        """Exit the application"""
        self.frame.close_application()
    
    def ShowBalloon(self, title, text, msec=0):
        """Show a balloon notification"""
        if wx.Platform == '__WXMSW__':
            # Only available on Windows
            super().ShowBalloon(title, text, msec)
        else:
            # For other platforms, we could implement a custom notification
            pass
