import wx

class TextCtrlWithHint(wx.TextCtrl):
    """A text control with a hint/watermark when empty"""
    def __init__(self, parent, value="", hint="", size=wx.DefaultSize):
        super().__init__(parent, value=value, size=size)
        self.hint = hint
        self.hint_shown = False
        self.hint_color = wx.Colour(169, 169, 169)  # Light gray
        self.default_color = self.GetForegroundColour()
        
        # Show hint initially if needed
        if not value:
            self.ShowHint()
        
        # Bind events
        self.Bind(wx.EVT_SET_FOCUS, self.OnSetFocus)
        self.Bind(wx.EVT_KILL_FOCUS, self.OnKillFocus)
    
    def ShowHint(self):
        if not self.GetValue() and not self.hint_shown:
            self.SetValue(self.hint)
            self.SetForegroundColour(self.hint_color)
            self.hint_shown = True
    
    def HideHint(self):
        if self.hint_shown:
            self.SetValue("")
            self.SetForegroundColour(self.default_color)
            self.hint_shown = False
    
    def OnSetFocus(self, event):
        if self.hint_shown:
            self.HideHint()
        event.Skip()
    
    def OnKillFocus(self, event):
        if not self.GetValue():
            self.ShowHint()
        event.Skip()
    
    def GetValue(self):
        if self.hint_shown:
            return ""
        return super().GetValue()

class LocalAccountDialog(wx.Dialog):
    """Dialog for adding or editing local accounts"""
    def __init__(self, parent, title="Local Account", account_name="", password="", aliases=""):
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE)
        
        # Create a panel
        panel = wx.Panel(self)
        
        # Create a sizer for the panel
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Create a FlexGridSizer for better alignment
        field_sizer = wx.FlexGridSizer(3, 2, 10, 10)  # rows, cols, vgap, hgap
        field_sizer.AddGrowableCol(1)  # Make the second column (text controls) growable
        
        # Account name field
        name_label = wx.StaticText(panel, label="Account Name:")
        self.account_name = wx.TextCtrl(panel, value=account_name, size=(250, -1))
        field_sizer.Add(name_label, 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        field_sizer.Add(self.account_name, 1, wx.EXPAND)
        
        # Password field
        password_label = wx.StaticText(panel, label="Password:")
        self.password = wx.TextCtrl(panel, value=password, size=(250, -1))
        field_sizer.Add(password_label, 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        field_sizer.Add(self.password, 1, wx.EXPAND)
        
        # Aliases field
        aliases_label = wx.StaticText(panel, label="Aliases:")
        self.aliases = TextCtrlWithHint(panel, value=aliases, hint="Separate with commas (e.g., alias1, alias2)", size=(250, -1))
        field_sizer.Add(aliases_label, 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        field_sizer.Add(self.aliases, 1, wx.EXPAND)
        
        # Add the field sizer to the main sizer with some padding
        sizer.Add(field_sizer, 0, wx.ALL | wx.EXPAND, 10)
        
        # Buttons
        button_sizer = wx.StdDialogButtonSizer()
        ok_button = wx.Button(panel, wx.ID_OK)
        ok_button.SetDefault()
        button_sizer.AddButton(ok_button)
        cancel_button = wx.Button(panel, wx.ID_CANCEL)
        button_sizer.AddButton(cancel_button)
        button_sizer.Realize()
        sizer.Add(button_sizer, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        # Set the sizer for the panel
        panel.SetSizer(sizer)
        
        # Fit the dialog to its contents
        sizer.Fit(self)
        self.Centre()
