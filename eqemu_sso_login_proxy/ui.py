import os
import time
import threading
import logging
import wx
import wx.adv
from PIL import Image
from . import eq_config

# Define custom event IDs
EVT_STATS_UPDATED = wx.NewEventType()
EVT_USER_CONNECTED = wx.NewEventType()

# Create event binder objects
EVT_STATS_UPDATED_BINDER = wx.PyEventBinder(EVT_STATS_UPDATED, 1)
EVT_USER_CONNECTED_BINDER = wx.PyEventBinder(EVT_USER_CONNECTED, 1)

# Custom event classes
class StatsUpdatedEvent(wx.PyCommandEvent):
    def __init__(self, etype, eid):
        wx.PyCommandEvent.__init__(self, etype, eid)

class UserConnectedEvent(wx.PyCommandEvent):
    def __init__(self, etype, eid, username=""):
        wx.PyCommandEvent.__init__(self, etype, eid)
        self._username = username
        
    def GetUsername(self):
        return self._username

# Global connection statistics
class ProxyStats:
    """Class to track and update proxy statistics"""
    def __init__(self):
        self.total_connections = 0
        self.active_connections = 0
        self.completed_connections = 0
        self.proxy_status = "Initializing..."
        self.listening_address = "0.0.0.0"
        self.listening_port = 0
        self.start_time = time.time()
        self.listeners = []
    
    def add_listener(self, listener):
        """Add a listener for events"""
        if listener not in self.listeners:
            self.listeners.append(listener)
    
    def remove_listener(self, listener):
        """Remove a listener"""
        if listener in self.listeners:
            self.listeners.remove(listener)
    
    def notify_stats_updated(self):
        """Notify all listeners that stats have been updated"""
        for listener in self.listeners:
            evt = StatsUpdatedEvent(EVT_STATS_UPDATED, listener.GetId())
            wx.PostEvent(listener, evt)
    
    def notify_user_connected(self, username):
        """Notify all listeners that a user has connected"""
        for listener in self.listeners:
            evt = UserConnectedEvent(EVT_USER_CONNECTED, listener.GetId(), username)
            wx.PostEvent(listener, evt)
    
    def update_status(self, status):
        """Update the proxy status"""
        self.proxy_status = status
        self.notify_stats_updated()
    
    def update_listening_info(self, address, port):
        """Update the listening address and port"""
        self.listening_address = address
        self.listening_port = port
        self.notify_stats_updated()
    
    def connection_started(self):
        """Increment connection counters when a new connection starts"""
        self.total_connections += 1
        self.active_connections += 1
        self.notify_stats_updated()
    
    def connection_completed(self):
        """Update counters when a connection completes"""
        self.active_connections = max(0, self.active_connections - 1)
        self.completed_connections += 1
        self.notify_stats_updated()
    
    def get_uptime(self):
        """Return uptime in human-readable format"""
        uptime_seconds = int(time.time() - self.start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def user_login(self, username):
        """Signal that a user has logged in"""
        self.notify_user_connected(username)

# Create a global stats instance
proxy_stats = ProxyStats()

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
            self.show_user_connected_notification(username)
            
        def update_stats(self, event=None):
            """Update all statistics in the UI"""
            self.status_value.SetLabel(proxy_stats.proxy_status)
            self.address_value.SetLabel(f"{proxy_stats.listening_address}:{proxy_stats.listening_port}")
            self.uptime_value.SetLabel(proxy_stats.get_uptime())
            self.total_value.SetLabel(str(proxy_stats.total_connections))
            self.active_value.SetLabel(str(proxy_stats.active_connections))
            self.completed_value.SetLabel(str(proxy_stats.completed_connections))
            
            # Update tray tooltip with basic stats if tray icon exists
            if hasattr(self, 'tray_icon'):
                tooltip = f"EQEmu Login Proxy\nStatus: {proxy_stats.proxy_status}\n"
                tooltip += f"Connections: {proxy_stats.active_connections} active, "
                tooltip += f"{proxy_stats.total_connections} total"
                
                # The icon itself is managed by update_icon, we just update the tooltip here
                if self.tray_icon.using_proxy:
                    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray_icon.png")
                else:
                    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray_icon_disabled.png")
                    
                if os.path.exists(icon_path):
                    icon = wx.Icon(icon_path)
                    self.tray_icon.SetIcon(icon, tooltip)
        
        def show_user_connected_notification(self, username):
            """Show a tray notification when a user connects"""
            if hasattr(self, 'tray_icon'):
                self.tray_icon.ShowBalloon(
                    "User Connected",
                    f"User '{username}' has connected to the proxy.",
                    3000  # Show for 3 seconds
                )
        
        def on_close(self, event):
            """Handle window close event"""
            # Minimize to tray instead of closing
            self.Hide()
            if hasattr(self, 'tray_icon'):
                self.tray_icon.ShowBalloon(
                    "EQEmu Login Proxy",
                    "Application is still running in the system tray.",
                    2000
                )
        
        def close_application(self):
            """Actually close the application"""
            # Remove the tray icon first to prevent it from lingering
            if hasattr(self, 'tray_icon'):
                self.tray_icon.RemoveIcon()
                self.tray_icon.Destroy()
            
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
    
    def __init__(self, parent=None, id=wx.ID_ANY, title="EQEmu Login Proxy"):
        super().__init__(parent, id, title, size=(550, 500))
        
        # Initialize event handlers
        self.__init_event_handlers()
        
        # Register as a listener for proxy stats events
        proxy_stats.add_listener(self)
        
        # Bind event handlers
        self.Bind(EVT_STATS_UPDATED_BINDER, self.on_stats_updated)
        self.Bind(EVT_USER_CONNECTED_BINDER, self.on_user_connected)
        
        # Initialize UI components
        self.init_ui()
        self.setup_tray()
        
        # Update stats periodically
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_stats, self.timer)
        self.timer.Start(1000)  # Update every second
        
        # Store updater reference
        self.updater = None
        self.update_progress_dialog = None
        
        # Set icon
        self.set_icon()
        
        # Update EQ status
        wx.CallAfter(self.update_eq_status)
        
        # Automatically check for updates on startup
        wx.CallAfter(self.check_for_updates_on_startup)
    
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
        status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        status_label = StatusLabel(proxy_tab, "Server:")
        self.status_value = ValueLabel(proxy_tab, proxy_stats.proxy_status)
        status_sizer.Add(status_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        status_sizer.Add(self.status_value, 1, wx.ALIGN_CENTER_VERTICAL)
        status_box_sizer.Add(status_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Proxy status
        proxy_status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        proxy_status_label = StatusLabel(proxy_tab, "EQ Config:")
        self.proxy_status_text = ValueLabel(proxy_tab, "Checking...")
        proxy_status_sizer.Add(proxy_status_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        proxy_status_sizer.Add(self.proxy_status_text, 1, wx.ALIGN_CENTER_VERTICAL)
        status_box_sizer.Add(proxy_status_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Listening address
        address_sizer = wx.BoxSizer(wx.HORIZONTAL)
        address_label = StatusLabel(proxy_tab, "Listening on:")
        self.address_value = ValueLabel(proxy_tab, f"{proxy_stats.listening_address}:{proxy_stats.listening_port}")
        address_sizer.Add(address_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        address_sizer.Add(self.address_value, 1, wx.ALIGN_CENTER_VERTICAL)
        status_box_sizer.Add(address_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Uptime
        uptime_sizer = wx.BoxSizer(wx.HORIZONTAL)
        uptime_label = StatusLabel(proxy_tab, "Uptime:")
        self.uptime_value = ValueLabel(proxy_tab, proxy_stats.get_uptime())
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
        self.total_value = ValueLabel(proxy_tab, str(proxy_stats.total_connections))
        total_sizer.Add(total_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        total_sizer.Add(self.total_value, 1, wx.ALIGN_CENTER_VERTICAL)
        stats_box_sizer.Add(total_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Active connections
        active_sizer = wx.BoxSizer(wx.HORIZONTAL)
        active_label = StatusLabel(proxy_tab, "Active Connections:")
        self.active_value = ValueLabel(proxy_tab, str(proxy_stats.active_connections))
        active_sizer.Add(active_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        active_sizer.Add(self.active_value, 1, wx.ALIGN_CENTER_VERTICAL)
        stats_box_sizer.Add(active_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Completed connections
        completed_sizer = wx.BoxSizer(wx.HORIZONTAL)
        completed_label = StatusLabel(proxy_tab, "Completed Connections:")
        self.completed_value = ValueLabel(proxy_tab, str(proxy_stats.completed_connections))
        completed_sizer.Add(completed_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        completed_sizer.Add(self.completed_value, 1, wx.ALIGN_CENTER_VERTICAL)
        stats_box_sizer.Add(completed_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Add the statistics box to the main proxy sizer
        proxy_sizer.Add(stats_box_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # EQ Configuration Actions section
        action_box = wx.StaticBox(proxy_tab, label="Actions")
        action_sizer = wx.StaticBoxSizer(action_box, wx.VERTICAL)
        
        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.refresh_btn = wx.Button(proxy_tab, label="Refresh Status")
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh_eq_status)
        button_sizer.Add(self.refresh_btn, 0, wx.ALL, 5)
        
        self.enable_btn = wx.Button(proxy_tab, label="Enable Proxy")
        self.enable_btn.Bind(wx.EVT_BUTTON, self.on_enable_proxy)
        button_sizer.Add(self.enable_btn, 0, wx.ALL, 5)
        
        self.disable_btn = wx.Button(proxy_tab, label="Disable Proxy")
        self.disable_btn.Bind(wx.EVT_BUTTON, self.on_disable_proxy)
        button_sizer.Add(self.disable_btn, 0, wx.ALL, 5)
        
        action_sizer.Add(button_sizer, 0, wx.ALL | wx.CENTER, 5)
        
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
        
        eq_sizer.Add(eq_status_sizer, 1, wx.ALL | wx.EXPAND, 10)
        
        # UI Options section
        ui_options_box = wx.StaticBox(eq_tab, label="UI Options")
        ui_options_sizer = wx.StaticBoxSizer(ui_options_box, wx.VERTICAL)
        
        # Always on top checkbox
        self.always_on_top_cb = wx.CheckBox(eq_tab, label="Always On Top")
        self.always_on_top_cb.SetValue(False)  # Default to unchecked
        self.always_on_top_cb.Bind(wx.EVT_CHECKBOX, self.on_always_on_top)
        ui_options_sizer.Add(self.always_on_top_cb, 0, wx.ALL, 5)
        
        eq_sizer.Add(ui_options_sizer, 0, wx.ALL | wx.EXPAND, 10)
        
        # Set the EQ tab sizer
        eq_tab.SetSizer(eq_sizer)
        
        # Add tabs to notebook
        notebook.AddPage(proxy_tab, "Proxy Status")
        notebook.AddPage(eq_tab, "Debug Info")
        
        # Add notebook to main sizer
        main_sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 10)
        
        # Launch EverQuest button at the bottom
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.launch_eq_btn = wx.Button(panel, label="Launch EverQuest")
        self.launch_eq_btn.Bind(wx.EVT_BUTTON, self.on_launch_eq)
        button_sizer.Add(self.launch_eq_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(button_sizer, 0, wx.ALL | wx.CENTER, 5)
        
        panel.SetSizer(main_sizer)
        
        # Center the window
        self.Centre()
    
    # Handle launch EverQuest button click
    def on_launch_eq(self, event):
        from . import eq_config
        import os
        import sys
        import ctypes
        import win32api
        import win32con
        import win32gui
        
        # Get the EverQuest directory
        eq_dir = eq_config.find_eq_directory()
        
        if not eq_dir:
            wx.MessageBox("EverQuest directory not found.", "Error", wx.OK | wx.ICON_ERROR)
            return
        
        # Path to eqgame.exe
        eqgame_path = os.path.join(eq_dir, "eqgame.exe")
        
        if not os.path.exists(eqgame_path):
            wx.MessageBox(f"EverQuest executable not found at {eqgame_path}", "Error", wx.OK | wx.ICON_ERROR)
            return
        
        try:
            # Launch EverQuest with elevated privileges using ShellExecute
            win32api.ShellExecute(
                win32gui.GetDesktopWindow(),
                "runas",  # This verb requests elevation
                eqgame_path,
                "patchme",  # No parameters
                eq_dir,  # Working directory
                win32con.SW_SHOWNORMAL
            )
            
            # Minimize the proxy to tray after launching EQ
            # self.Hide()
            # if hasattr(self, 'tray_icon'):
            #     self.tray_icon.ShowBalloon(
            #         "EQEmu Login Proxy",
            #         "EverQuest launched. The proxy is still running in the system tray.",
            #         2000
            #     )
        except Exception as e:
            wx.MessageBox(f"Failed to launch EverQuest: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)
    
    # Handle minimize to tray button click (kept for reference but not used)
    def on_minimize(self, event):
        self.Hide()
        if hasattr(self, 'tray_icon'):
            self.tray_icon.ShowBalloon(
                "EQEmu Login Proxy",
                "Application is still running in the system tray.",
                2000  # Show for 2 seconds
            )
    
    # Refresh EverQuest configuration status
    def on_refresh_eq_status(self, event):
        self.update_eq_status()
    
    # Enable proxy in EverQuest configuration
    def on_enable_proxy(self, event):
        success = eq_config.enable_proxy()
        if not success:
            wx.MessageBox("Failed to enable proxy. EverQuest directory or eqhost.txt not found.", 
                         "Error", wx.OK | wx.ICON_ERROR)
        self.update_eq_status()
    
    # Disable proxy in EverQuest configuration
    def on_disable_proxy(self, event):
        success = eq_config.disable_proxy()
        if not success:
            wx.MessageBox("Failed to disable proxy. EverQuest directory or eqhost.txt not found.", 
                         "Error", wx.OK | wx.ICON_ERROR)
        self.update_eq_status()
    
    # Save eqhost.txt content
    def on_save_eqhost(self, event):
        from . import eq_config
        import os
        import logging
        
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
        
    # Set the application icon
    def set_icon(self):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray_icon.png")
        if os.path.exists(icon_path):
            icon = wx.Icon(icon_path)
            self.SetIcon(icon)
    
    # Update EverQuest configuration status display
    def update_eq_status(self):
        """Update the EverQuest configuration status display"""

        # Get current status
        status = eq_config.get_eq_status()
        
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
        
        # Update button states
        self.enable_btn.Enable(not status["using_proxy"])
        self.disable_btn.Enable(status["using_proxy"])
        
        # Update tray icon based on proxy status
        if hasattr(self, 'tray_icon'):
            self.tray_icon.update_icon(status["using_proxy"])
    
    # Set up system tray icon and menu
    def setup_tray(self):
        # Create a TaskBarIcon
        self.tray_icon = TaskBarIcon(self)
        
        # Ensure both tray icons exist
        normal_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray_icon.png")
        disabled_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray_icon_disabled.png")
        
        if not os.path.exists(normal_icon_path):
            create_tray_icon(disabled=False)
            
        if not os.path.exists(disabled_icon_path):
            create_tray_icon(disabled=True)
    
    # Check for updates on startup (no UI feedback)
    def check_for_updates_on_startup(self):
        from . import updater
        if self.updater is None:
            self.updater = updater.Updater()
            self.updater.update_available_callback = self.on_update_available
            self.updater.update_progress_callback = self.on_update_progress
            self.updater.update_complete_callback = self.on_update_complete
        
        # Store the result for the tray menu
        self.has_update = False
        self.new_version = None
        
        # Set callbacks for startup check
        original_callback = self.updater.update_available_callback
        
        def startup_update_callback(current_version, new_version):
            self.has_update = True
            self.new_version = new_version
            # Update the tray menu
            if hasattr(self, 'tray_icon'):
                self.tray_icon.update_menu()
        
        # Use our special callback for the startup check
        self.updater.update_available_callback = startup_update_callback
        
        # Check for updates silently
        self.updater.check_for_updates()
        
        # Restore original callback
        self.updater.update_available_callback = original_callback
    
    # Check for updates manually
    def check_for_updates(self):
        from . import updater
        if self.updater is None:
            self.updater = updater.Updater()
            self.updater.update_available_callback = self.on_update_available
            self.updater.update_progress_callback = self.on_update_progress
            self.updater.update_complete_callback = self.on_update_complete
        
        self.updater.check_for_updates()
    
    # Handle when an update is available
    def on_update_available(self, current_version, new_version):
        message = f"A new version ({new_version}) is available. You are currently running {current_version}.\n\nWould you like to update now?"
        dialog = wx.MessageDialog(self, message, "Update Available", wx.YES_NO | wx.ICON_INFORMATION)
        result = dialog.ShowModal()
        dialog.Destroy()
        
        if result == wx.ID_YES:
            # Create progress dialog
            self.update_progress_dialog = wx.ProgressDialog(
                "Updating",
                "Downloading update...",
                maximum=100,
                parent=self,
                style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
            )
            
            # Start the update process
            self.updater.download_and_install_update()
    
    # Handle update progress updates
    def on_update_progress(self, message, progress):
        if self.update_progress_dialog:
            self.update_progress_dialog.Update(progress, message)
    
    # Handle update completion
    def on_update_complete(self, success, message):
        if self.update_progress_dialog:
            self.update_progress_dialog.Destroy()
            self.update_progress_dialog = None
        
        if success:
            dialog = wx.MessageDialog(self, message + "\n\nThe application will now restart.", "Update Complete", wx.OK | wx.ICON_INFORMATION)
            dialog.ShowModal()
            dialog.Destroy()
            
            # Restart the application
            self.close_application()
            import sys
            import os
            import subprocess
            subprocess.Popen([sys.executable] + sys.argv)
        else:
            wx.MessageBox(message, "Update Failed", wx.OK | wx.ICON_ERROR)
    
    # Cancel the update process
    def cancel_update(self):
        if self.updater:
            self.updater.cancel_update()
        
        if self.update_progress_dialog:
            self.update_progress_dialog.Destroy()
            self.update_progress_dialog = None

class TaskBarIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame
        self.using_proxy = True  # Default state
        
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
        
        # Add update menu item based on update status
        if hasattr(self.frame, 'has_update') and self.frame.has_update and self.frame.new_version:
            update_item = menu.Append(wx.ID_ANY, f"New version: {self.frame.new_version}")
            self.Bind(wx.EVT_MENU, self.on_do_update, update_item)
        else:
            update_item = menu.Append(wx.ID_ANY, "No update available.")
            update_item.Enable(False)
        
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
    def update_icon(self, using_proxy=True):
        self.using_proxy = using_proxy
        
        # Choose the appropriate icon
        if using_proxy:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray_icon.png")
            tooltip = "EQEmu Login Proxy - Enabled"
        else:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray_icon_disabled.png")
            tooltip = "EQEmu Login Proxy - Disabled"
        
        # Set the icon
        if os.path.exists(icon_path):
            icon = wx.Icon(icon_path)
            self.SetIcon(icon, tooltip)
    
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
                "EQEmu Login Proxy",
                "Application is still running in the system tray.",
                2000  # Show for 2 seconds
            )
    

    
    def on_check_updates(self, event):
        """Check for updates"""
        self.frame.check_for_updates()
    
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
    
    # These methods are used by the tray icon menu
    def on_do_update(self, event):
        """Perform the update"""
        if self.frame.has_update and self.frame.new_version:
            # Create progress dialog for update
            self.frame.update_progress_dialog = wx.ProgressDialog(
                "Updating",
                "Preparing to update...",
                maximum=100,
                parent=self.frame,
                style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_CAN_ABORT
            )
            
            # Start update in background
            self.frame.updater.download_and_install_update()
    
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
    
    # No duplicated update methods needed in TaskBarIcon class

def create_tray_icon(disabled=False):
    """Create a tray icon image with a circle and '99' text
    
    Args:
        disabled (bool): If True, creates a red-tinted version of the icon
    """
    from PIL import Image, ImageDraw, ImageFont
    import os
    
    # Create a new image with a transparent background
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Choose color based on disabled status
    if disabled:
        # Red color for disabled state
        color = (219, 52, 52)  # Red
        filename = "tray_icon_disabled.png"
    else:
        # Blue color for normal state
        color = (52, 152, 219)  # Blue
        filename = "tray_icon.png"
    
    # Draw a circle
    circle_margin = 0
    circle_radius = (size - 2 * circle_margin) // 2
    circle_center = (size // 2, size // 2)
    circle_bbox = [
        circle_center[0] - circle_radius,
        circle_center[1] - circle_radius,
        circle_center[0] + circle_radius,
        circle_center[1] + circle_radius
    ]
    
    # Draw filled circle with some transparency
    circle_fill = color + (200,)  # Add alpha channel (200/255 opacity)
    draw.ellipse(circle_bbox, fill=circle_fill, outline=color, width=2)
    
    # Try to load a font, fall back to default if not available
    try:
        # Try to find a bold font for the text
        font_path = None
        # Common font locations
        potential_fonts = [
            ("C:\\Windows\\Fonts\\lucon.ttf", 1.5, 2),      # Lucida Console
            ("C:\\Windows\\Fonts\\arialbd.ttf", 1.7, 1.3),  # Arial Bold
            ("C:\\Windows\\Fonts\\impact.ttf", 1.5, 1.3),   # Impact Regular
        ]
        
        for path, scale, position_mod in potential_fonts:
            if os.path.exists(path):
                font_path = path
                font_scale = scale
                font_position_mod = position_mod
                break
        
        if font_path:
            # Increase font size by 40% for better visibility
            font_size = int(circle_radius * font_scale)
            font = ImageFont.truetype(font_path, size=font_size)
        else:
            # Fall back to default font
            font = ImageFont.load_default()
    except Exception:
        # If any error occurs with fonts, use default
        font = ImageFont.load_default()
    
    # Draw "99" text in white
    text = "99"
    text_color = (255, 255, 255)  # White
    
    # Get text size to center it
    try:
        # For newer Pillow versions
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
    except AttributeError:
        # For older Pillow versions
        text_width, text_height = draw.textsize(text, font=font)
    
    text_position = (
        circle_center[0] - text_width // 2,
        circle_center[1] - text_height // font_position_mod
    )
    
    # Draw text with a slight shadow for better visibility
    shadow_offset = 1
    draw.text((text_position[0] + shadow_offset, text_position[1] + shadow_offset), 
              text, fill=(0, 0, 0, 128), font=font)  # Semi-transparent black shadow
    draw.text(text_position, text, fill=text_color, font=font)
    
    # Save the image
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    
    # Force the icon to be recreated by deleting any existing icon first
    if os.path.exists(icon_path):
        try:
            os.remove(icon_path)
        except:
            pass
    
    image.save(icon_path)
    return icon_path

def start_ui():
    """Initialize and start the UI"""
    # Always recreate both tray icons to ensure consistency
    create_tray_icon(disabled=False)
    create_tray_icon(disabled=True)
    
    # Create the wxPython application
    app = wx.App(False)
    app.SetVendorName("Toald (P99 Green)")
    
    # Create and show the main window
    main_window = ProxyUI()
    main_window.Show()
    
    # Bind the close handler
    main_window.Bind(wx.EVT_CLOSE, main_window.on_close)
    
    return app, main_window
