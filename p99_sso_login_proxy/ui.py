import logging
import os
import sys
import threading
import datetime
import platform

import wx
import wx.html

from p99_sso_login_proxy import config
from p99_sso_login_proxy import eq_config
from p99_sso_login_proxy import sso_api
from p99_sso_login_proxy import utils
from p99_sso_login_proxy.ui_classes import local_account_dialog
from p99_sso_login_proxy.ui_classes import proxy_stats
from p99_sso_login_proxy.ui_classes import taskbar_icon

# Create a global stats instance
PROXY_STATS = proxy_stats.ProxyStats()


def warning(message):
    # Display a warning popup and wait for the user to click ok
    dialog = wx.MessageDialog(None, message, "Warning", wx.OK | wx.ICON_WARNING)
    dialog.ShowModal()
    dialog.Destroy()


def error(message):
    # Display an error popup and wait for the user to click ok
    dialog = wx.MessageDialog(None, message, "Error", wx.OK | wx.ICON_ERROR)
    dialog.ShowModal()
    dialog.Destroy()


class StatusLabel(wx.StaticText):
    """Custom styled status label"""
    def __init__(self, parent, text="", id=wx.ID_ANY):
        super().__init__(parent, id, text)
        font = self.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.SetFont(font)


class ValueLabel(wx.StaticText):
    """Custom styled value label"""
    def __init__(self, parent, text="", id=wx.ID_ANY):
        super().__init__(parent, id, text)
        self.SetForegroundColour(wx.Colour(44, 62, 80))  # #2c3e50


class ProxyUI(wx.Frame):
    """Main UI window for the proxy application"""
    def __init_event_handlers(self):
        """Initialize event handlers"""
        # Define an event to notify when application should exit
        self.exit_event = threading.Event()
        
        # Define event handler methods
        def on_stats_updated(self, event):
            """Handle stats updated event"""
            self.update_stats()
            
        def on_user_connected(self, event):
            """Handle user connected event"""
            username = event.GetUsername()
            self.last_username_label.SetLabel(username)
            self.show_user_connected_notification(username)
            
        def update_stats(self, event=None):
            """Update all statistics in the UI"""
            # self.status_value.SetLabel(proxy_stats.proxy_status)
            self.address_value.SetLabel(f"{PROXY_STATS.listening_address}:{PROXY_STATS.listening_port}")
            self.uptime_value.SetLabel(PROXY_STATS.get_uptime())
            self.total_value.SetLabel(str(PROXY_STATS.total_connections))
            self.active_value.SetLabel(str(PROXY_STATS.active_connections))
            self.completed_value.SetLabel(str(PROXY_STATS.completed_connections))

            if self.tray_icon:
                # Update tray tooltip with basic stats if tray icon exists
                tooltip = f"{config.APP_NAME}\n"
                tooltip += f"Status: {PROXY_STATS.proxy_status}\n"
                tooltip += f"Connections: {PROXY_STATS.active_connections} active, "
                tooltip += f"{PROXY_STATS.total_connections} total\n"
                tooltip += f"Local Accounts: {len(config.LOCAL_ACCOUNTS)}\n"
                tooltip += f"SSO Accounts: {config.ACCOUNTS_CACHE_REAL_COUNT}"
                self.tray_icon.update_icon(tooltip=tooltip)
        
        def show_user_connected_notification(self, username):
            """Show a tray notification when a user connects"""
            if hasattr(self, 'tray_icon'):
                self.tray_icon.ShowBalloon(
                    "User Connected",
                    f"User has connected to the proxy as '{username}'.",
                    3000  # Show for 3 seconds
                )
        
        def on_close(self, event):
            """Handle window close event"""
            # Minimize to tray instead of closing
            self.Hide()
            if hasattr(self, 'tray_icon'):
                self.tray_icon.ShowBalloon(
                    config.APP_NAME,
                    f"{config.APP_NAME} is still running in the system tray.",
                    2000
                )
        
        def close_application(self):
            """Actually close the application"""
            # Remove the tray icon first to prevent it from lingering
            if hasattr(self, 'tray_icon'):
                self.tray_icon.RemoveIcon()
                self.tray_icon.Destroy()

            # Disable the proxy if it's enabled
            if eq_config.is_using_proxy():
                eq_config.disable_proxy()
            
            # Set the exit event to notify the main application to exit
            self.exit_event.set()
            
            # This will close the UI, but the main event loop needs to be stopped separately
            self.Destroy()

        # Add the methods to the class
        self.on_stats_updated = on_stats_updated.__get__(self)
        self.on_user_connected = on_user_connected.__get__(self)
        self.update_stats = update_stats.__get__(self)
        self.show_user_connected_notification = show_user_connected_notification.__get__(self)
        self.on_close = on_close.__get__(self)
        self.close_application = close_application.__get__(self)
    
    def __init__(self, parent=None, id=wx.ID_ANY, title=f"{config.APP_NAME} v{config.APP_VERSION}"):
        # Create a frame with a fixed size (non-resizable)
        if platform.system() == "Windows":
            style = wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
            size = (550, 520)
        else:
            style = wx.DEFAULT_FRAME_STYLE
            size = (700, 640)
        super().__init__(parent, id, title, size=size, style=style)

        # Initialize event handlers
        self.__init_event_handlers()
        
        # Register as a listener for proxy stats events
        PROXY_STATS.add_listener(self)
        
        # Bind event handlers
        self.Bind(proxy_stats.EVT_STATS_UPDATED_BINDER, self.on_stats_updated)
        self.Bind(proxy_stats.EVT_USER_CONNECTED_BINDER, self.on_user_connected)
        
        # Initialize UI components
        self.init_ui()
        
        # Create a TaskBarIcon
        self.tray_icon = taskbar_icon.TaskBarIcon(self)
        
        # Update stats periodically
        self.uptime_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_stats, self.uptime_timer)
        self.uptime_timer.Start(1000)  # Update every second
        self.cache_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_account_cache_time, self.cache_timer)
        self.cache_timer.Start(10 * 60 * 1000)  # Update every 10 minutes
        # Set icon
        self.set_icon()
        
        # Enable the proxy if it's enabled in the config
        if config.PROXY_ENABLED and eq_config.find_eq_directory():
            eq_config.enable_proxy()

        # Update EQ status
        wx.CallAfter(self.update_eq_status)

    
    def init_ui(self):
        # Create main panel
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Add horizontal line
        line = wx.StaticLine(panel)
        main_sizer.Add(line, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 5)
        
        # Create a notebook for tabbed interface
        notebook = wx.Notebook(panel)
        
        # Proxy Status tab
        proxy_tab = wx.Panel(notebook)
        proxy_sizer = wx.BoxSizer(wx.VERTICAL)

        # Status section
        status_box = wx.StaticBox(proxy_tab, label="Status")
        status_box_sizer = wx.StaticBoxSizer(status_box, wx.VERTICAL)
        
        # Server status
        # status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        # status_label = StatusLabel(proxy_tab, "Server:")
        # self.status_value = ValueLabel(proxy_tab, proxy_stats.proxy_status)
        # status_sizer.Add(status_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        # status_sizer.Add(self.status_value, 1, wx.ALIGN_CENTER_VERTICAL)
        # status_box_sizer.Add(status_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Listening address
        address_sizer = wx.BoxSizer(wx.HORIZONTAL)
        address_label = StatusLabel(proxy_tab, "Listening on:")
        self.address_value = ValueLabel(proxy_tab, f"{PROXY_STATS.listening_address}:{PROXY_STATS.listening_port}")
        address_sizer.Add(address_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        address_sizer.Add(self.address_value, 1, wx.ALIGN_CENTER_VERTICAL)
        status_box_sizer.Add(address_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Proxy status
        proxy_status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        proxy_status_label = StatusLabel(proxy_tab, "EQ Config:")
        self.proxy_status_text = ValueLabel(proxy_tab, "Checking...")
        proxy_status_sizer.Add(proxy_status_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        proxy_status_sizer.Add(self.proxy_status_text, 1, wx.ALIGN_CENTER_VERTICAL)
        status_box_sizer.Add(proxy_status_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Last username connected
        last_user_sizer = wx.BoxSizer(wx.HORIZONTAL)
        last_user_label = StatusLabel(proxy_tab, "Last Username:")
        self.last_username_label = ValueLabel(proxy_tab, "")
        last_user_sizer.Add(last_user_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        last_user_sizer.Add(self.last_username_label, 1, wx.ALIGN_CENTER_VERTICAL)
        status_box_sizer.Add(last_user_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Uptime
        uptime_sizer = wx.BoxSizer(wx.HORIZONTAL)
        uptime_label = StatusLabel(proxy_tab, "Uptime:")
        self.uptime_value = ValueLabel(proxy_tab, PROXY_STATS.get_uptime())
        uptime_sizer.Add(uptime_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        uptime_sizer.Add(self.uptime_value, 1, wx.ALIGN_CENTER_VERTICAL)
        status_box_sizer.Add(uptime_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Add the status box to the main proxy sizer
        proxy_sizer.Add(status_box_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Statistics section
        stats_box = wx.StaticBox(proxy_tab, label="Statistics")
        stats_box_sizer = wx.StaticBoxSizer(stats_box, wx.VERTICAL)
        
        # Total connections
        total_sizer = wx.BoxSizer(wx.HORIZONTAL)
        total_label = StatusLabel(proxy_tab, "Total Connections:")
        self.total_value = ValueLabel(proxy_tab, str(PROXY_STATS.total_connections))
        total_sizer.Add(total_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        total_sizer.Add(self.total_value, 1, wx.ALIGN_CENTER_VERTICAL)
        stats_box_sizer.Add(total_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Active connections
        active_sizer = wx.BoxSizer(wx.HORIZONTAL)
        active_label = StatusLabel(proxy_tab, "Active Connections:")
        self.active_value = ValueLabel(proxy_tab, str(PROXY_STATS.active_connections))
        active_sizer.Add(active_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        active_sizer.Add(self.active_value, 1, wx.ALIGN_CENTER_VERTICAL)
        stats_box_sizer.Add(active_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Completed connections
        completed_sizer = wx.BoxSizer(wx.HORIZONTAL)
        completed_label = StatusLabel(proxy_tab, "Completed Connections:")
        self.completed_value = ValueLabel(proxy_tab, str(PROXY_STATS.completed_connections))
        completed_sizer.Add(completed_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        completed_sizer.Add(self.completed_value, 1, wx.ALIGN_CENTER_VERTICAL)
        stats_box_sizer.Add(completed_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Add the statistics box to the main proxy sizer
        proxy_sizer.Add(stats_box_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # EQ Configuration Settings section
        action_box = wx.StaticBox(proxy_tab, label="Settings")
        action_sizer = wx.StaticBoxSizer(action_box, wx.VERTICAL)
        
        # Controls row
        controls_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Add Proxy Mode dropdown selector
        mode_sizer = wx.BoxSizer(wx.HORIZONTAL)
        mode_label = StatusLabel(proxy_tab, "Proxy Mode:")
        mode_sizer.Add(mode_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        
        # Create the dropdown with the three options
        self.proxy_mode_choice = wx.Choice(proxy_tab, choices=[
            "Enabled (SSO)",
            "Enabled (Proxy Only)",
            "Disabled"
        ])
        
        # Set the initial selection based on current config
        using_proxy, _ = eq_config.is_using_proxy()
        if not using_proxy:
            self.proxy_mode_choice.SetSelection(2)  # Disabled
        elif config.PROXY_ONLY:
            self.proxy_mode_choice.SetSelection(1)  # Enabled (Proxy Only)
        else:
            self.proxy_mode_choice.SetSelection(0)  # Enabled (SSO)
        
        # Bind the event handler
        self.proxy_mode_choice.Bind(wx.EVT_CHOICE, self.on_proxy_mode_changed)
        
        # Add a tooltip to explain the options
        self.proxy_mode_choice.SetToolTip(
            "Enabled (SSO): Full proxy with SSO authentication\n"
            "Enabled (Proxy Only): Proxy active but no SSO interaction ('middlemand' mode)\n"
            "Disabled: Proxy inactive, direct connection to server")
        
        mode_sizer.Add(self.proxy_mode_choice, 0, wx.ALIGN_CENTER_VERTICAL, 0)
        controls_sizer.Add(mode_sizer, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        
        # Add some spacing between the dropdown and checkbox
        if platform.system() == "Windows":
            aot_spacer_size = 140
        else:
            aot_spacer_size = 60
        controls_sizer.AddSpacer(aot_spacer_size)
        
        # Always on top checkbox
        self.always_on_top_cb = wx.CheckBox(proxy_tab, label="Always On Top")
        self.always_on_top_cb.SetValue(config.ALWAYS_ON_TOP)  # Default to value in config
        if config.ALWAYS_ON_TOP:
            # Set the window to be always on top
            self.SetWindowStyle(self.GetWindowStyle() | wx.STAY_ON_TOP)

        self.always_on_top_cb.Bind(wx.EVT_CHECKBOX, self.on_always_on_top)
        self.always_on_top_cb.SetToolTip("Keep the application window on top of other windows")
        
        # Add checkbox to the controls row
        controls_sizer.Add(self.always_on_top_cb, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 0)
        
        action_sizer.Add(controls_sizer, 0, wx.ALL | wx.LEFT, 0)
        
        # API Token field (moved from Advanced tab)
        token_field_sizer = wx.BoxSizer(wx.HORIZONTAL)
        token_label = StatusLabel(proxy_tab, "API Token:")
        self.password_field = wx.TextCtrl(proxy_tab, style=wx.TE_PASSWORD)
        self.password_field.SetValue(config.USER_API_TOKEN)  # Set to value from config
        self.password_field.SetToolTip("API Token for auto-authentication. When this is set, "
                                      "the password entered in the EQ UI will be ignored.")
        token_field_sizer.Add(token_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        token_field_sizer.Add(self.password_field, 1, wx.EXPAND, 0)
        self.password_field.Bind(wx.EVT_TEXT, self.on_save_debug_password)
        
        # Bind focus events to show/hide password
        self.password_field.Bind(wx.EVT_SET_FOCUS, self.on_password_focus)
        self.password_field.Bind(wx.EVT_KILL_FOCUS, self.on_password_blur)
        
        # Add token field to the action section
        action_sizer.Add(token_field_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        proxy_sizer.Add(action_sizer, 0, wx.ALL | wx.EXPAND, 10)
        
        # Set the proxy tab sizer
        proxy_tab.SetSizer(proxy_sizer)
        
        # EverQuest Configuration tab
        eq_tab = wx.Panel(notebook)
        eq_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # EQ Configuration Status section
        eq_status_box = wx.StaticBox(eq_tab, label="EverQuest Configuration")
        eq_status_sizer = wx.StaticBoxSizer(eq_status_box, wx.VERTICAL)
        
        # EQ Directory status
        eq_dir_sizer = wx.BoxSizer(wx.HORIZONTAL)
        eq_dir_label = StatusLabel(eq_tab, "EverQuest Path:")
        self.eq_dir_text = ValueLabel(eq_tab, "Checking...")
        eq_dir_sizer.Add(eq_dir_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        eq_dir_sizer.Add(self.eq_dir_text, 1, wx.ALIGN_CENTER_VERTICAL)
        eq_status_sizer.Add(eq_dir_sizer, 0, wx.ALL | wx.EXPAND, 5)
        
        # eqhost.txt status
        eqhost_sizer = wx.BoxSizer(wx.HORIZONTAL)
        eqhost_label = StatusLabel(eq_tab, "eqhost.txt Path:")
        self.eqhost_text = ValueLabel(eq_tab, "Checking...")
        eqhost_sizer.Add(eqhost_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        eqhost_sizer.Add(self.eqhost_text, 1, wx.ALIGN_CENTER_VERTICAL)
        eq_status_sizer.Add(eqhost_sizer, 0, wx.ALL | wx.EXPAND, 5)
        
        # eqhost.txt contents
        self.eqhost_contents = wx.TextCtrl(eq_tab, style=wx.TE_MULTILINE, size=(-1, 100))
        eq_status_sizer.Add(StatusLabel(eq_tab, "eqhost.txt Content:"), 0, wx.ALL, 5)
        eq_status_sizer.Add(self.eqhost_contents, 1, wx.ALL | wx.EXPAND, 5)
        
        # eqhost.txt action buttons
        eqhost_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.save_eqhost_btn = wx.Button(eq_tab, label="Save")
        self.save_eqhost_btn.Bind(wx.EVT_BUTTON, self.on_save_eqhost)
        eqhost_btn_sizer.Add(self.save_eqhost_btn, 0, wx.ALL, 5)
        
        self.reset_eqhost_btn = wx.Button(eq_tab, label="Reset")
        self.reset_eqhost_btn.Bind(wx.EVT_BUTTON, self.on_reset_eqhost)
        eqhost_btn_sizer.Add(self.reset_eqhost_btn, 0, wx.ALL, 5)
        
        eq_status_sizer.Add(eqhost_btn_sizer, 0, wx.ALL | wx.CENTER, 5)
        
        # The API Token field has been moved to the Proxy Status tab
        
        # Add the EQ status sizer to the main EQ tab sizer
        eq_sizer.Add(eq_status_sizer, 0, wx.ALL | wx.EXPAND, 10)
        
        # Account Cache section
        account_cache_box = wx.StaticBox(eq_tab, label="Account Cache")
        account_cache_sizer = wx.StaticBoxSizer(account_cache_box, wx.VERTICAL)
        
        # Create a horizontal sizer for the cache controls section
        cache_controls_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Create a vertical sizer for the cache info (time and accounts)
        cache_info_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Cache Time field
        cache_time_sizer = wx.BoxSizer(wx.HORIZONTAL)
        cache_time_label = StatusLabel(eq_tab, "Cache Time:")
        self.cache_time_text = ValueLabel(eq_tab, "Unset")
        self.cache_time_text.SetToolTip("Time when account data was last fetched from the SSO server")
        cache_time_sizer.Add(cache_time_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        cache_time_sizer.Add(self.cache_time_text, 1, wx.ALIGN_CENTER_VERTICAL)
        cache_info_sizer.Add(cache_time_sizer, 0, wx.ALL | wx.EXPAND, 5)
        self.update_account_cache_time()
        
        # Accounts Cached field
        accounts_cached_sizer = wx.BoxSizer(wx.HORIZONTAL)
        accounts_cached_label = StatusLabel(eq_tab, "Accounts Cached:")
        self.accounts_cached_text = ValueLabel(eq_tab, "0")
        self.accounts_cached_text.SetToolTip("Number of accounts and aliases/tags stored in the cache")
        accounts_cached_sizer.Add(accounts_cached_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        accounts_cached_sizer.Add(self.accounts_cached_text, 1, wx.ALIGN_CENTER_VERTICAL)
        cache_info_sizer.Add(accounts_cached_sizer, 0, wx.ALL | wx.EXPAND, 5)
        
        # Add the cache info sizer to the controls sizer
        cache_controls_sizer.Add(cache_info_sizer, 1, wx.EXPAND, 0)
        
        # Refresh button
        self.refresh_cache_btn = wx.Button(eq_tab, label="Refresh Cache")
        self.refresh_cache_btn.Bind(wx.EVT_BUTTON, self.on_refresh_account_cache)
        self.refresh_cache_btn.SetToolTip("Refresh the account cache from the SSO server")
        
        # Add the button directly to the controls sizer
        cache_controls_sizer.Add(self.refresh_cache_btn, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        
        # Add the controls sizer to the account cache sizer
        account_cache_sizer.Add(cache_controls_sizer, 0, wx.ALL | wx.EXPAND, 5)
        
        # Add the account cache sizer to the main EQ tab sizer
        eq_sizer.Add(account_cache_sizer, 0, wx.ALL | wx.EXPAND, 10)
        
        # Set the EQ tab sizer
        eq_tab.SetSizer(eq_sizer)
        
        # SSO Accounts tab
        sso_tab = wx.Panel(notebook)
        sso_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Create a nested notebook for the different account views
        sso_notebook = wx.Notebook(sso_tab)
        
        # Accounts tab
        accounts_tab = wx.Panel(sso_notebook)
        accounts_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Create a list control for the accounts
        self.accounts_list = wx.ListCtrl(accounts_tab, style=wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_HRULES | wx.LC_VRULES)
        self.accounts_list.InsertColumn(0, "Account Name", width=150)
        self.accounts_list.InsertColumn(1, "Aliases", width=150)
        self.accounts_list.InsertColumn(2, "Tags", width=150)
        
        # We'll set alternating row colors in the update_account_cache_display method
        
        # Add the list control to the accounts tab
        accounts_sizer.Add(self.accounts_list, 1, wx.ALL | wx.EXPAND, 5)
        accounts_tab.SetSizer(accounts_sizer)
        
        # Aliases tab
        aliases_tab = wx.Panel(sso_notebook)
        aliases_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Create a list control for the aliases
        self.aliases_list = wx.ListCtrl(aliases_tab, style=wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_HRULES | wx.LC_VRULES)
        self.aliases_list.InsertColumn(0, "Alias", width=150)
        self.aliases_list.InsertColumn(1, "Account Name", width=300)
        
        # We'll set alternating row colors in the update_account_cache_display method
        
        # Add the list control to the aliases tab
        aliases_sizer.Add(self.aliases_list, 1, wx.ALL | wx.EXPAND, 5)
        aliases_tab.SetSizer(aliases_sizer)
        
        # Tags tab
        tags_tab = wx.Panel(sso_notebook)
        tags_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Create a list control for the tags
        self.tags_list = wx.ListCtrl(tags_tab, style=wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_HRULES | wx.LC_VRULES)
        self.tags_list.InsertColumn(0, "Tag", width=150)
        self.tags_list.InsertColumn(1, "Account Names", width=300)
        
        # We'll set alternating row colors in the update_account_cache_display method
        
        # Add the list control to the tags tab
        tags_sizer.Add(self.tags_list, 1, wx.ALL | wx.EXPAND, 5)
        tags_tab.SetSizer(tags_sizer)
        
        # Local accounts tab
        local_tab = wx.Panel(sso_notebook)
        local_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Create a list control for the local accounts
        self.local_accounts_list = wx.ListCtrl(local_tab, style=wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_HRULES | wx.LC_VRULES)
        self.local_accounts_list.InsertColumn(0, "Account Name", width=200)
        self.local_accounts_list.InsertColumn(1, "Aliases", width=250)
        
        # We'll set alternating row colors in the update_account_cache_display method
        
        # Add the list control to the local tab
        local_sizer.Add(self.local_accounts_list, 1, wx.ALL | wx.EXPAND, 5)
        
        # Add buttons for managing local accounts
        local_buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Add account button
        self.add_local_account_btn = wx.Button(local_tab, label="Add Account")
        self.add_local_account_btn.Bind(wx.EVT_BUTTON, self.on_add_local_account)
        local_buttons_sizer.Add(self.add_local_account_btn, 0, wx.ALL, 5)
        
        # Edit account button
        self.edit_local_account_btn = wx.Button(local_tab, label="Edit Account")
        self.edit_local_account_btn.Bind(wx.EVT_BUTTON, self.on_edit_local_account)
        local_buttons_sizer.Add(self.edit_local_account_btn, 0, wx.ALL, 5)
        
        # Delete account button
        self.delete_local_account_btn = wx.Button(local_tab, label="Delete Account")
        self.delete_local_account_btn.Bind(wx.EVT_BUTTON, self.on_delete_local_account)
        local_buttons_sizer.Add(self.delete_local_account_btn, 0, wx.ALL, 5)
        
        # Add the buttons sizer to the local tab
        local_sizer.Add(local_buttons_sizer, 0, wx.ALL | wx.CENTER, 5)
        local_tab.SetSizer(local_sizer)
        
        # Add the tabs to the nested notebook
        sso_notebook.AddPage(accounts_tab, "Accounts")
        sso_notebook.AddPage(aliases_tab, "Aliases")
        sso_notebook.AddPage(tags_tab, "Tags")
        sso_notebook.AddPage(local_tab, "Local")
        
        # Add the nested notebook to the main SSO tab sizer
        sso_sizer.Add(sso_notebook, 1, wx.ALL | wx.EXPAND, 5)
        
        # Add refresh button below the notebook
        refresh_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_accounts_btn = wx.Button(sso_tab, label="Refresh SSO Account List")
        self.refresh_accounts_btn.Bind(wx.EVT_BUTTON, self.on_refresh_account_cache)
        self.refresh_accounts_btn.SetToolTip("Refresh the account cache from the SSO server")
        refresh_btn_sizer.Add(self.refresh_accounts_btn, 0, wx.BOTTOM, 5)
        
        sso_sizer.Add(refresh_btn_sizer, 0, wx.ALL | wx.CENTER, 5)
        
        # Set the SSO tab sizer
        sso_tab.SetSizer(sso_sizer)
        
        # Create Changelog tab
        changelog_tab = wx.Panel(notebook)
        changelog_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Create a static box with the label "Version History"
        version_history_box = wx.StaticBox(changelog_tab, label="Version History")
        version_history_sizer = wx.StaticBoxSizer(version_history_box, wx.VERTICAL)
        
        # Create an HTML window for the changelog
        self.changelog_html = wx.html.HtmlWindow(version_history_box)

        # Add the HTML window to the static box sizer
        version_history_sizer.Add(self.changelog_html, 1, wx.EXPAND | wx.ALL, 10)
        
        # Add the static box sizer to the main changelog sizer
        changelog_sizer.Add(version_history_sizer, 1, wx.EXPAND | wx.ALL, 10)
        changelog_tab.SetSizer(changelog_sizer)
        
        # Add tabs to notebook
        notebook.AddPage(proxy_tab, "Proxy")
        notebook.AddPage(sso_tab, "SSO")
        notebook.AddPage(eq_tab, "Advanced")
        notebook.AddPage(changelog_tab, "Changelog")
        
        # Add notebook to main sizer
        main_sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 10)
        
        # Buttons at the bottom
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Launch EverQuest button
        self.launch_eq_btn = wx.Button(panel, label="Launch EverQuest")
        self.launch_eq_btn.Bind(wx.EVT_BUTTON, self.on_launch_eq)
        button_sizer.Add(self.launch_eq_btn, 0, wx.ALL, 5)
        
        # Add some space between buttons
        button_sizer.AddSpacer(60)
        
        # Exit button
        self.exit_btn = wx.Button(panel, label="Exit")
        self.exit_btn.Bind(wx.EVT_BUTTON, self.on_exit_button)
        button_sizer.Add(self.exit_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(button_sizer, 0, wx.ALL | wx.CENTER, 5)
        
        panel.SetSizer(main_sizer)
        
        # Center the window
        self.Centre()
    
    # Handle launch EverQuest button click
    def on_launch_eq(self, event):
        # Get the EverQuest directory
        eq_dir = eq_config.find_eq_directory()
        
        if not eq_dir:
            wx.MessageBox("EverQuest directory not found.", "Error", wx.OK | wx.ICON_ERROR)
            return
        
        # Path to eqgame.exe
        eqgame_path = os.path.join(eq_dir, "eqgame.exe")
        try:
            if os.path.exists(eqgame_path):
                self.start_eq_func(eq_dir)
            else:
                wx.MessageBox(f"EverQuest executable not found in {eq_dir}", "Error", wx.OK | wx.ICON_ERROR)
        except Exception as e:
            wx.MessageBox(f"Failed to launch EverQuest: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)

    # Handle proxy mode selection change
    def on_proxy_mode_changed(self, event):
        selection = self.proxy_mode_choice.GetSelection()

        # Get current status to avoid unnecessary changes
        using_proxy, _ = eq_config.is_using_proxy()

        if selection == 0:  # Enabled (SSO)
            # Enable proxy if it's not already enabled
            if not using_proxy:
                success = eq_config.enable_proxy()
                if not success:
                    wx.MessageBox("Failed to enable proxy. EverQuest directory or eqhost.txt not found.", 
                                "Error", wx.OK | wx.ICON_ERROR)
                    # Revert selection if failed
                    self.proxy_mode_choice.SetSelection(2)
                    return

            if config.PROXY_ONLY:
                config.set_proxy_only(False)
            if not config.PROXY_ENABLED:
                config.set_proxy_enabled(True)

        elif selection == 1:  # Enabled (Proxy Only)
            # Enable proxy if it's not already enabled
            if not using_proxy:
                success = eq_config.enable_proxy()
                if not success:
                    wx.MessageBox("Failed to enable proxy. EverQuest directory or eqhost.txt not found.", 
                                "Error", wx.OK | wx.ICON_ERROR)
                    # Revert selection if failed
                    self.proxy_mode_choice.SetSelection(2)
                    return
            
            if not config.PROXY_ONLY:
                config.set_proxy_only(True)
            if not config.PROXY_ENABLED:
                config.set_proxy_enabled(True)
        
        elif selection == 2:  # Disabled
            # Disable proxy if it's currently enabled
            if using_proxy:
                success = eq_config.disable_proxy()
                if not success:
                    wx.MessageBox("Failed to disable proxy. EverQuest directory or eqhost.txt not found.", 
                                "Error", wx.OK | wx.ICON_ERROR)
                    # Revert selection if failed
                    self.proxy_mode_choice.SetSelection(0 if not config.PROXY_ONLY else 1)
                    return
            
            if config.PROXY_ONLY:
                config.set_proxy_only(False)
            if config.PROXY_ENABLED:
                config.set_proxy_enabled(False)
        
        # Update UI to reflect new status
        self.update_eq_status()
    
    def on_updated_changelog(self):
        # Update the changelog HTML
        self.changelog_html.SetPage(config.CHANGELOG)

        # Set background color to match the panel background
        self.changelog_html.SetHTMLBackgroundColour("#f9f9f9")

    # Save eqhost.txt content
    def on_save_eqhost(self, event):
        # Get the EverQuest directory
        eq_dir = eq_config.find_eq_directory()
        
        if not eq_dir:
            logging.error("EverQuest directory not found when trying to save eqhost.txt")
            return
        
        # Path to eqhost.txt
        eqhost_path = os.path.join(eq_dir, "eqhost.txt")
        
        # Get content from text control
        content = self.eqhost_contents.GetValue()
        
        try:
            # Write content to file
            with open(eqhost_path, 'w') as f:
                f.write(content)
            
            logging.info(f"Successfully wrote to eqhost.txt at {eqhost_path}")
            # Update status after save
            self.update_eq_status()
        except Exception as e:
            logging.error(f"Failed to save eqhost.txt: {str(e)}")
    
    # Reset eqhost.txt content from disk
    def on_reset_eqhost(self, event):
        # Simply update the status which will reload the file content
        self.update_eq_status()
    
    # Handle Always On Top checkbox
    def on_always_on_top(self, event):
        # Get the checkbox state
        is_checked = self.always_on_top_cb.GetValue()
        
        # Set the window style
        if is_checked:
            # Set the window to be always on top
            self.SetWindowStyle(self.GetWindowStyle() | wx.STAY_ON_TOP)
        else:
            # Remove the always on top style
            self.SetWindowStyle(self.GetWindowStyle() & ~wx.STAY_ON_TOP)
            
        # Update the checkbox state in the config
        config.set_always_on_top(is_checked)
    
    # Handle saving the password on typing
    def on_save_debug_password(self, event):
        # Get the password from the field
        password = self.password_field.GetValue()
        
        # Save the password to config
        config.set_user_api_token(password)
    
    # Show password when field gets focus
    def on_password_focus(self, event):
        # Update the style to show the password
        print("Password field focused")

        handle = self.password_field.GetHandle()
        if handle:
            # In windows, we need to use win32api to unset the password character
            if platform.system() == "Windows":
                import win32api
                import win32con
                win32api.SendMessage(handle, win32con.EM_SETPASSWORDCHAR, 0, 0)
            else:
                style = self.password_field.GetWindowStyleFlag()
                style &= ~wx.TE_PASSWORD
                self.password_field.SetWindowStyleFlag(style)
        # Ensure the event propagates
        event.Skip()
    
    # Hide password when field loses focus
    def on_password_blur(self, event):
        # Add password style back
        print("Password field blurred")
        handle = self.password_field.GetHandle()
        if handle:
            # In windows, we need to use win32api to set the password character
            if platform.system() == "Windows":
                import win32api
                import win32con
                win32api.SendMessage(handle, win32con.EM_SETPASSWORDCHAR, 0x25cf, 0)
            else:
                style = self.password_field.GetWindowStyleFlag()
                style |= wx.TE_PASSWORD
                self.password_field.SetWindowStyleFlag(style)
        # Ensure the event propagates
        event.Skip()
        
    # Handle refresh account cache button click
    def on_refresh_account_cache(self, event):
        """Refresh the account cache from the SSO server"""
        try:
            # Show a busy cursor
            wx.BeginBusyCursor()
            
            # Refresh the account cache
            sso_api.fetch_user_accounts()
            
            # Reload local accounts
            config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNT_NAME_MAP = utils.load_local_accounts(config.LOCAL_ACCOUNTS_FILE)
            
            # Update the UI
            self.update_account_cache_display()
            
            # Update the cache time
            self.update_account_cache_time()
        except Exception as e:
            print(f"[UI] Failed to refresh account cache: {str(e)}")
            wx.MessageBox(f"Failed to refresh account cache: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)
        finally:
            # Restore the cursor
            if wx.IsBusy():
                wx.EndBusyCursor()
    
    # Handle exit button click
    def on_exit_button(self, event):
        """Exit the application when the exit button is clicked"""
        self.close_application()
        
    # Set the application icon
    def set_icon(self):
        # Try multiple possible locations for the icon file
        icon_paths = [
            # When running from source
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tray_icon.png"),
            # When running from PyInstaller bundle
            os.path.join(os.path.dirname(sys.executable), "tray_icon.png"),
            # Current directory
            "tray_icon.png"
        ]
        
        icon = None
        for path in icon_paths:
            if os.path.exists(path):
                try:
                    icon = wx.Icon(path, wx.BITMAP_TYPE_ANY)
                    break
                except Exception as e:
                    print(f"Failed to load icon from {path}: {e}")
        
        # TODO: Revisit for cleanup
        if icon:
            self.SetIcon(icon)
            # Also set the taskbar icon explicitly
            if hasattr(self, 'tray_icon'):
                self.tray_icon.SetIcon(icon, config.APP_NAME)
    
    def update_account_cache_time(self, event=None) -> None:
        """Update the account cache time display"""
        cache_text_color = wx.Colour(0, 128, 0)  # Green
        if config.ACCOUNTS_CACHE_TIMESTAMP == datetime.datetime.min:
            cache_time = "Not cached yet"
            cache_text_color = wx.RED
        else:
            cache_time = config.ACCOUNTS_CACHE_TIMESTAMP.strftime("%Y-%m-%d %H:%M:%S")
            time_diff = datetime.datetime.now() - config.ACCOUNTS_CACHE_TIMESTAMP

            if time_diff.seconds > 24 * 60 * 60:  # 24 hours
                print(f"Account cache is stale, updating: {time_diff}")
                cache_text_color = wx.RED
                sso_api.fetch_user_accounts()
                self.update_account_cache_time()
            elif time_diff.seconds > 12 * 60 * 60:  # 12 hours
                # print(f"Account cache is getting stale: {time_diff}")
                cache_text_color = wx.Colour(255, 130, 0)  # Orange
            # print(f"Updating account cache time: {cache_time} ({time_diff})")

        if hasattr(self, 'cache_time_text'):
            self.cache_time_text.SetForegroundColour(cache_text_color)
            self.cache_time_text.SetLabel(cache_time)
            self.cache_time_text.Refresh()

    # Handle adding a local account
    def on_add_local_account(self, event):
        """Add a new local account"""
        dialog = local_account_dialog.LocalAccountDialog(self, title="Add Local Account")
        if dialog.ShowModal() == wx.ID_OK:
            account_name = dialog.account_name.GetValue().strip()
            password = dialog.password.GetValue().strip()
            aliases_text = dialog.aliases.GetValue().strip()
            
            # Validate input
            if not account_name:
                wx.MessageBox("Account name cannot be empty.", "Error", wx.OK | wx.ICON_ERROR)
                return
            
            if not password:
                wx.MessageBox("Password cannot be empty.", "Error", wx.OK | wx.ICON_ERROR)
                return
            
            # Check if account already exists
            if account_name in config.LOCAL_ACCOUNTS:
                wx.MessageBox(f"Account '{account_name}' already exists.", "Error", wx.OK | wx.ICON_ERROR)
                return
            
            # Parse aliases
            aliases = [alias.strip() for alias in aliases_text.split(",") if alias.strip()]
            
            # Add the account
            config.LOCAL_ACCOUNTS[account_name] = {
                "password": password,
                "aliases": aliases
            }
            
            # Update the name map
            config.LOCAL_ACCOUNT_NAME_MAP[account_name] = account_name
            for alias in aliases:
                config.LOCAL_ACCOUNT_NAME_MAP[alias] = account_name
            
            # Save to file
            if not utils.save_local_accounts(config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNTS_FILE):
                wx.MessageBox("Failed to save local accounts.", "Error", wx.OK | wx.ICON_ERROR)
            
            # Update the UI
            self.update_account_cache_display()
        
        dialog.Destroy()
    
    # Handle editing a local account
    def on_edit_local_account(self, event):
        """Edit an existing local account"""
        # Get the selected account
        selected_index = self.local_accounts_list.GetFirstSelected()
        if selected_index == -1:
            wx.MessageBox("Please select an account to edit.", "Error", wx.OK | wx.ICON_ERROR)
            return
        
        account_name = self.local_accounts_list.GetItemText(selected_index, 0)
        if account_name not in config.LOCAL_ACCOUNTS:
            wx.MessageBox(f"Account '{account_name}' not found.", "Error", wx.OK | wx.ICON_ERROR)
            return
        
        # Get the current account data
        account_data = config.LOCAL_ACCOUNTS[account_name]
        
        # Create and show the dialog
        dialog = local_account_dialog.LocalAccountDialog(
            self, 
            title="Edit Local Account",
            account_name=account_name,
            password=account_data.get("password", ""),
            aliases=", ".join(account_data.get("aliases", []))
        )
        dialog.account_name.Disable()  # Don't allow changing the account name
        
        if dialog.ShowModal() == wx.ID_OK:
            password = dialog.password.GetValue().strip()
            aliases_text = dialog.aliases.GetValue().strip()
            
            # Validate input
            if not password:
                wx.MessageBox("Password cannot be empty.", "Error", wx.OK | wx.ICON_ERROR)
                return
            
            # Parse aliases
            aliases = [alias.strip() for alias in aliases_text.split(",") if alias.strip()]
            
            # Remove old aliases from the name map
            for alias in account_data.get("aliases", []):
                if alias in config.LOCAL_ACCOUNT_NAME_MAP:
                    del config.LOCAL_ACCOUNT_NAME_MAP[alias]
            
            # Update the account
            config.LOCAL_ACCOUNTS[account_name] = {
                "password": password,
                "aliases": aliases
            }
            
            # Update the name map
            for alias in aliases:
                config.LOCAL_ACCOUNT_NAME_MAP[alias] = account_name
            
            # Save to file
            if not utils.save_local_accounts(config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNTS_FILE):
                wx.MessageBox("Failed to save local accounts.", "Error", wx.OK | wx.ICON_ERROR)
            
            # Update the UI
            self.update_account_cache_display()
        
        dialog.Destroy()
    
    # Handle deleting a local account
    def on_delete_local_account(self, event):
        """Delete a local account"""
        # Get the selected account
        selected_index = self.local_accounts_list.GetFirstSelected()
        if selected_index == -1:
            wx.MessageBox("Please select an account to delete.", "Error", wx.OK | wx.ICON_ERROR)
            return
        
        account_name = self.local_accounts_list.GetItemText(selected_index, 0)
        if account_name not in config.LOCAL_ACCOUNTS:
            wx.MessageBox(f"Account '{account_name}' not found.", "Error", wx.OK | wx.ICON_ERROR)
            return
        
        # Confirm deletion
        if wx.MessageBox(f"Are you sure you want to delete the account '{account_name}'?", 
                        "Confirm Deletion", wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
            return
        
        # Get the account data
        account_data = config.LOCAL_ACCOUNTS[account_name]
        
        # Remove aliases from the name map
        for alias in account_data.get("aliases", []):
            if alias in config.LOCAL_ACCOUNT_NAME_MAP:
                del config.LOCAL_ACCOUNT_NAME_MAP[alias]
        
        # Remove the account from the name map
        if account_name in config.LOCAL_ACCOUNT_NAME_MAP:
            del config.LOCAL_ACCOUNT_NAME_MAP[account_name]
        
        # Remove the account
        del config.LOCAL_ACCOUNTS[account_name]
        
        # Save to file
        if not utils.save_local_accounts(config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNTS_FILE):
            wx.MessageBox("Failed to save local accounts.", "Error", wx.OK | wx.ICON_ERROR)
        
        # Update the UI
        self.update_account_cache_display()

    # Update EverQuest configuration status display
    def update_account_cache_display(self):
        """Update the account cache display"""
        # Update accounts cached
        total_accounts = len(config.ALL_CACHED_NAMES)
        real_accounts = config.ACCOUNTS_CACHE_REAL_COUNT
        
        # Update the text with account counts
        if total_accounts == 0:
            self.accounts_cached_text.SetLabel("None")
            self.accounts_cached_text.SetForegroundColour(wx.Colour(128, 128, 128))  # Gray
        else:
            self.accounts_cached_text.SetLabel(f"{real_accounts} accounts, {total_accounts - real_accounts} aliases/tags")
            self.accounts_cached_text.SetForegroundColour(wx.Colour(0, 128, 0))  # Green
            
        # Update the local accounts list
        if hasattr(self, 'local_accounts_list'):
            self.local_accounts_list.DeleteAllItems()
            
            # Add each local account to the list
            for i, (account, data) in enumerate(sorted(config.LOCAL_ACCOUNTS.items())):
                self.local_accounts_list.InsertItem(i, account)
                
                # Add aliases as comma-separated list
                aliases = data.get("aliases", [])
                if aliases:
                    self.local_accounts_list.SetItem(i, 1, ", ".join(sorted(aliases)))
                
                # Set alternating row colors
                if i % 2 == 1:
                    self.local_accounts_list.SetItemBackgroundColour(i, wx.Colour(240, 245, 250))
        
        # Update the accounts list in the SSO tab
        if hasattr(self, 'accounts_list'):
            self.accounts_list.DeleteAllItems()
            
            # Add each account to the list
            index = 0
            for account, data in sorted(config.ACCOUNTS_CACHED.items()):
                # Add the account
                self.accounts_list.InsertItem(index, account)
                
                # Add aliases as comma-separated list
                aliases = data.get("aliases", [])
                if aliases:
                    self.accounts_list.SetItem(index, 1, ", ".join(sorted(aliases)))
                
                # Add tags as comma-separated list
                tags = data.get("tags", [])
                if tags:
                    self.accounts_list.SetItem(index, 2, ", ".join(sorted(tags)))
                
                # Set alternating row colors
                if index % 2 == 1:
                    self.accounts_list.SetItemBackgroundColour(index, wx.Colour(240, 245, 250))
                
                index += 1
        
        # Update the aliases list
        if hasattr(self, 'aliases_list'):
            self.aliases_list.DeleteAllItems()
            
            # Create a list of all aliases with their account names
            all_aliases = []
            for account, data in config.ACCOUNTS_CACHED.items():
                aliases = data.get("aliases", [])
                for alias in sorted(aliases):
                    all_aliases.append((alias, account))
            
            # Sort by alias name
            all_aliases.sort()
            
            # Add each alias to the list
            for i, (alias, account) in enumerate(all_aliases):
                self.aliases_list.InsertItem(i, alias)
                self.aliases_list.SetItem(i, 1, account)
                
                # Set alternating row colors
                if i % 2 == 1:
                    self.aliases_list.SetItemBackgroundColour(i, wx.Colour(240, 245, 250))
        
        # Update the tags list
        if hasattr(self, 'tags_list'):
            self.tags_list.DeleteAllItems()
            
            # Create a dictionary of tags to accounts
            tag_to_accounts = {}
            for account, data in config.ACCOUNTS_CACHED.items():
                tags = data.get("tags", [])
                for tag in sorted(tags):
                    if tag not in tag_to_accounts:
                        tag_to_accounts[tag] = []
                    tag_to_accounts[tag].append(account)
            
            # Add each tag to the list
            for i, (tag, accounts) in enumerate(sorted(tag_to_accounts.items())):
                self.tags_list.InsertItem(i, tag)
                self.tags_list.SetItem(i, 1, ", ".join(sorted(accounts)))
                
                # Set alternating row colors
                if i % 2 == 1:
                    self.tags_list.SetItemBackgroundColour(i, wx.Colour(240, 245, 250))

    def update_eq_status(self):
        """Update the EverQuest configuration status display"""

        # Get current status
        status = eq_config.get_eq_status()
        
        # Update account cache display
        self.update_account_cache_display()
        
        # Update EQ directory status
        if status["eq_directory_found"]:
            self.eq_dir_text.SetLabel(f"{status['eq_directory']}")
            self.eq_dir_text.SetForegroundColour(wx.Colour(0, 128, 0))  # Green
        else:
            self.eq_dir_text.SetLabel("Not Found")
            self.eq_dir_text.SetForegroundColour(wx.Colour(255, 0, 0))  # Red
        
        # Update eqhost.txt status
        if status["eqhost_found"]:
            self.eqhost_text.SetLabel(f"{status['eqhost_path']}")
            self.eqhost_text.SetForegroundColour(wx.Colour(0, 128, 0))  # Green
        else:
            self.eqhost_text.SetLabel("Not Found")
            self.eqhost_text.SetForegroundColour(wx.Colour(255, 0, 0))  # Red
        
        # Update proxy status
        if status["using_proxy"]:
            self.proxy_status_text.SetLabel("Enabled")
            self.proxy_status_text.SetForegroundColour(wx.Colour(0, 128, 0))  # Green
        else:
            self.proxy_status_text.SetLabel("Disabled")
            self.proxy_status_text.SetForegroundColour(wx.Colour(128, 0, 0))  # Red
        
        # Update eqhost.txt contents
        self.eqhost_contents.Clear()
        if status["eqhost_contents"]:
            self.eqhost_contents.AppendText("\n".join(status["eqhost_contents"]))
        
        # Update proxy mode dropdown based on current state
        if not status["using_proxy"]:
            self.proxy_mode_choice.SetSelection(2)  # Disabled
        elif config.PROXY_ONLY:
            self.proxy_mode_choice.SetSelection(1)  # Enabled (Proxy Only)
        else:
            self.proxy_mode_choice.SetSelection(0)  # Enabled (SSO)
        
        # Update tray icon based on proxy status
        if hasattr(self, 'tray_icon'):
            self.tray_icon.update_icon()


def start_ui():
    """Initialize and start the UI"""
    
    # Create and show the main window
    main_window = ProxyUI()
    main_window.Show()
    
    # Bind the close handler
    main_window.Bind(wx.EVT_CLOSE, main_window.on_close)
    
    return main_window
