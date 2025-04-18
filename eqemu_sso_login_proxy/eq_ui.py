"""
EverQuest Configuration UI

This module provides UI components for managing EverQuest configuration,
specifically for enabling/disabling the login proxy in the eqhost.txt file.
"""

import wx
import logging
from . import eq_config

# Set up logging
logger = logging.getLogger("eq_ui")


class EQConfigPanel(wx.Panel):
    """Panel for EverQuest configuration management"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        
        # Initialize UI
        self.init_ui()
        
        # Update status display
        self.update_status()
    
    def init_ui(self):
        """Initialize the UI components"""
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Status section
        status_box = wx.StaticBox(self, label="EverQuest Configuration Status")
        status_sizer = wx.StaticBoxSizer(status_box, wx.VERTICAL)
        
        # EQ Directory status
        self.eq_dir_text = wx.StaticText(self, label="EverQuest Directory: Not Found")
        status_sizer.Add(self.eq_dir_text, 0, wx.ALL | wx.EXPAND, 5)
        
        # eqhost.txt status
        self.eqhost_text = wx.StaticText(self, label="eqhost.txt: Not Found")
        status_sizer.Add(self.eqhost_text, 0, wx.ALL | wx.EXPAND, 5)
        
        # Proxy status
        self.proxy_status_text = wx.StaticText(self, label="Proxy Status: Disabled")
        status_sizer.Add(self.proxy_status_text, 0, wx.ALL | wx.EXPAND, 5)
        
        # eqhost.txt contents
        self.eqhost_contents = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 100))
        status_sizer.Add(wx.StaticText(self, label="eqhost.txt Contents:"), 0, wx.ALL, 5)
        status_sizer.Add(self.eqhost_contents, 1, wx.ALL | wx.EXPAND, 5)
        
        main_sizer.Add(status_sizer, 0, wx.ALL | wx.EXPAND, 10)
        
        # Actions section
        action_box = wx.StaticBox(self, label="Actions")
        action_sizer = wx.StaticBoxSizer(action_box, wx.VERTICAL)
        
        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.refresh_btn = wx.Button(self, label="Refresh Status")
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        button_sizer.Add(self.refresh_btn, 0, wx.ALL, 5)
        
        self.enable_btn = wx.Button(self, label="Enable Proxy")
        self.enable_btn.Bind(wx.EVT_BUTTON, self.on_enable_proxy)
        button_sizer.Add(self.enable_btn, 0, wx.ALL, 5)
        
        self.disable_btn = wx.Button(self, label="Disable Proxy")
        self.disable_btn.Bind(wx.EVT_BUTTON, self.on_disable_proxy)
        button_sizer.Add(self.disable_btn, 0, wx.ALL, 5)
        
        action_sizer.Add(button_sizer, 0, wx.ALL | wx.CENTER, 5)
        
        main_sizer.Add(action_sizer, 0, wx.ALL | wx.EXPAND, 10)
        
        # Set the main sizer
        self.SetSizer(main_sizer)
    
    def update_status(self):
        """Update the status display with current EQ configuration"""
        status = eq_config.get_eq_status()
        
        # Update EQ directory status
        if status["eq_directory_found"]:
            self.eq_dir_text.SetLabel(f"EverQuest Directory: {status['eq_directory']}")
            self.eq_dir_text.SetForegroundColour(wx.Colour(0, 128, 0))  # Green
        else:
            self.eq_dir_text.SetLabel("EverQuest Directory: Not Found")
            self.eq_dir_text.SetForegroundColour(wx.Colour(255, 0, 0))  # Red
        
        # Update eqhost.txt status
        if status["eqhost_found"]:
            self.eqhost_text.SetLabel(f"eqhost.txt: {status['eqhost_path']}")
            self.eqhost_text.SetForegroundColour(wx.Colour(0, 128, 0))  # Green
        else:
            self.eqhost_text.SetLabel("eqhost.txt: Not Found")
            self.eqhost_text.SetForegroundColour(wx.Colour(255, 0, 0))  # Red
        
        # Update proxy status
        if status["using_proxy"]:
            self.proxy_status_text.SetLabel("Proxy Status: Enabled")
            self.proxy_status_text.SetForegroundColour(wx.Colour(0, 128, 0))  # Green
        else:
            self.proxy_status_text.SetLabel("Proxy Status: Disabled")
            self.proxy_status_text.SetForegroundColour(wx.Colour(128, 128, 128))  # Gray
        
        # Update eqhost.txt contents
        self.eqhost_contents.Clear()
        if status["eqhost_contents"]:
            self.eqhost_contents.AppendText("\n".join(status["eqhost_contents"]))
        
        # Update button states
        self.enable_btn.Enable(not status["using_proxy"])
        self.disable_btn.Enable(status["using_proxy"])
        
        # Layout update
        self.Layout()
    
    def on_refresh(self, event):
        """Handle refresh button click"""
        self.update_status()
    
    def on_enable_proxy(self, event):
        """Handle enable proxy button click"""
        success = eq_config.enable_proxy()
        self.update_status()
    
    def on_disable_proxy(self, event):
        """Handle disable proxy button click"""
        success = eq_config.disable_proxy()
        self.update_status()


def create_eq_config_dialog(parent):
    """Create a dialog for EverQuest configuration"""
    dialog = wx.Dialog(parent, title="EverQuest Configuration", size=(500, 400))
    panel = EQConfigPanel(dialog)
    
    # Add buttons at the bottom
    button_sizer = wx.StdDialogButtonSizer()
    ok_button = wx.Button(dialog, wx.ID_OK)
    ok_button.SetDefault()
    button_sizer.AddButton(ok_button)
    button_sizer.Realize()
    
    # Main sizer for the dialog
    dialog_sizer = wx.BoxSizer(wx.VERTICAL)
    dialog_sizer.Add(panel, 1, wx.EXPAND | wx.ALL, 5)
    dialog_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 5)
    
    dialog.SetSizer(dialog_sizer)
    return dialog
