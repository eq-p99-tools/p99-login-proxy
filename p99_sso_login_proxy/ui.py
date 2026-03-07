import datetime
import logging
import os
import platform
import threading

import wx
import wx.html

from p99_sso_login_proxy import config, eq_config, log_handler, utils, ws_client, zone_translate
from p99_sso_login_proxy.ui_classes import local_account_dialog, proxy_stats, taskbar_icon

logger = logging.getLogger("ui")

PROXY_STATS = proxy_stats.ProxyStats()

# UI color constants
COLOR_SUCCESS = wx.Colour(0, 128, 0)
COLOR_ERROR = wx.Colour(255, 0, 0)
COLOR_DARK_RED = wx.Colour(128, 0, 0)
COLOR_WARNING = wx.Colour(255, 130, 0)
COLOR_MUTED = wx.Colour(128, 128, 128)
COLOR_VALUE_TEXT = wx.Colour(44, 62, 80)
COLOR_ALT_ROW = wx.Colour(240, 245, 250)
COLOR_ACTIVE_RED = wx.Colour(255, 120, 120)

ACTIVITY_FADE_SECONDS = 120


def _activity_colour(last_login_iso: str | None) -> wx.Colour | None:
    """Return a background colour that fades from red to transparent over ACTIVITY_FADE_SECONDS.

    Returns None once fully faded so normal alternating-row colours apply.
    """
    if not last_login_iso:
        return None
    try:
        then = datetime.datetime.fromisoformat(last_login_iso)
    except (ValueError, TypeError):
        return None
    elapsed = (datetime.datetime.now(tz=then.tzinfo) - then).total_seconds()
    if elapsed < 0:
        elapsed = 0
    if elapsed >= ACTIVITY_FADE_SECONDS:
        return None
    # Blend from COLOR_ACTIVE_RED toward the default list background
    bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOX)
    t = elapsed / ACTIVITY_FADE_SECONDS
    r = int(COLOR_ACTIVE_RED.Red() + (bg.Red() - COLOR_ACTIVE_RED.Red()) * t)
    g = int(COLOR_ACTIVE_RED.Green() + (bg.Green() - COLOR_ACTIVE_RED.Green()) * t)
    b = int(COLOR_ACTIVE_RED.Blue() + (bg.Blue() - COLOR_ACTIVE_RED.Blue()) * t)
    return wx.Colour(r, g, b)


def warning(message):
    dialog = wx.MessageDialog(None, message, "Warning", wx.OK | wx.ICON_WARNING)
    dialog.ShowModal()
    dialog.Destroy()


def error(message):
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
        self.SetForegroundColour(COLOR_VALUE_TEXT)


class ProxyUI(wx.Frame):
    """Main UI window for the proxy application"""

    def __init__(self, parent=None, id=wx.ID_ANY, title=f"{config.APP_NAME} v{config.APP_VERSION}"):
        if platform.system() == "Windows":
            style = wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
            size = (616, 550)
        else:
            style = wx.DEFAULT_FRAME_STYLE
            size = (756, 664)
        super().__init__(parent, id, title, size=size, style=style)

        self.exit_event = threading.Event()
        self._list_filter_data = {}

        PROXY_STATS.add_listener(self)
        self.Bind(proxy_stats.EVT_STATS_UPDATED_BINDER, self.on_stats_updated)
        self.Bind(proxy_stats.EVT_USER_CONNECTED_BINDER, self.on_user_connected)

        self.init_ui()

        self.tray_icon = taskbar_icon.TaskBarIcon(self)

        self.uptime_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_stats, self.uptime_timer)
        self.uptime_timer.Start(1000)
        self.ws_status_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_ws_status_tick, self.ws_status_timer)
        self.ws_status_timer.Start(5000)
        self._ws_reconnect_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_ws_reconnect_debounce, self._ws_reconnect_timer)
        self._char_fade_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_char_fade_tick, self._char_fade_timer)
        self._char_fade_timer.Start(10000)

        self.set_icon()

        if config.PROXY_ENABLED and eq_config.find_eq_directory():
            eq_config.enable_proxy()

        wx.CallAfter(self.update_eq_status)

    # --- UI construction helpers ---

    def _add_label_value_row(self, parent, box_sizer, label_text, initial_value=""):
        """Create a horizontal StatusLabel + ValueLabel row and add it to box_sizer."""
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        label = StatusLabel(parent, label_text)
        value = ValueLabel(parent, initial_value)
        sizer.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(value, 1, wx.ALIGN_CENTER_VERTICAL)
        box_sizer.Add(sizer, 0, wx.EXPAND | wx.ALL, 5)
        return value

    def _populate_list(self, list_ctrl, rows, row_color_fn=None):
        """Store rows and render through the search filter if one exists."""
        if list_ctrl in self._list_filter_data:
            self._list_filter_data[list_ctrl]["rows"] = rows
            self._list_filter_data[list_ctrl]["row_color_fn"] = row_color_fn
            self._apply_filter(list_ctrl)
        else:
            self._render_list(list_ctrl, rows, row_color_fn)

    def _render_list(self, list_ctrl, rows, row_color_fn=None):
        """Render rows into a ListCtrl with optional per-row colouring.

        Row tuples may contain extra trailing elements beyond the column count;
        those are treated as metadata and not displayed.
        """
        list_ctrl.DeleteAllItems()
        num_cols = list_ctrl.GetColumnCount()
        for i, row in enumerate(rows):
            list_ctrl.InsertItem(i, row[0])
            for col, value in enumerate(row[1:num_cols], 1):
                list_ctrl.SetItem(i, col, value)
            colour = row_color_fn(row) if row_color_fn else None
            if colour:
                list_ctrl.SetItemBackgroundColour(i, colour)
            elif i % 2 == 1:
                list_ctrl.SetItemBackgroundColour(i, COLOR_ALT_ROW)

    def _apply_filter(self, list_ctrl):
        """Re-render a list applying the current search filter.

        Each whitespace-separated word acts as a stacking filter: a row must
        match every word (in any column) to be included.
        """
        data = self._list_filter_data[list_ctrl]
        num_cols = list_ctrl.GetColumnCount()
        row_color_fn = data.get("row_color_fn")
        terms = data["search"].GetValue().lower().split()
        if not terms:
            self._render_list(list_ctrl, data["rows"], row_color_fn)
        else:
            filtered = [
                row
                for row in data["rows"]
                if all(any(term in cell.lower() for cell in row[:num_cols]) for term in terms)
            ]
            self._render_list(list_ctrl, filtered, row_color_fn)

    def _add_search_ctrl(self, parent, sizer, list_ctrl):
        """Add a search box above a list control for typeahead filtering."""
        search = wx.SearchCtrl(parent, style=wx.TE_PROCESS_ENTER)
        search.SetDescriptiveText("Type to filter...")
        search.ShowCancelButton(True)
        sizer.Add(search, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self._list_filter_data[list_ctrl] = {"rows": [], "search": search}
        search.Bind(wx.EVT_TEXT, lambda evt: self._apply_filter(list_ctrl))
        search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda evt: search.SetValue(""))
        return search

    def _create_list_ctrl(self, parent, columns):
        """Create a styled ListCtrl with the given columns list of (name, width)."""
        list_ctrl = wx.ListCtrl(parent, style=wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_HRULES | wx.LC_VRULES)
        for i, (name, width) in enumerate(columns):
            list_ctrl.InsertColumn(i, name, width=width)
        return list_ctrl

    # --- Tab creation methods ---

    def _create_proxy_tab(self, notebook):
        proxy_tab = wx.Panel(notebook)
        proxy_sizer = wx.BoxSizer(wx.VERTICAL)

        # Status section
        status_box = wx.StaticBox(proxy_tab, label="Status")
        status_box_sizer = wx.StaticBoxSizer(status_box, wx.VERTICAL)

        self.address_value = self._add_label_value_row(
            proxy_tab,
            status_box_sizer,
            "Listening on:",
            f"{PROXY_STATS.listening_address}:{PROXY_STATS.listening_port}",
        )
        self.proxy_status_text = self._add_label_value_row(proxy_tab, status_box_sizer, "EQ Config:", "Checking...")
        self.last_username_label = self._add_label_value_row(proxy_tab, status_box_sizer, "Last Username:", "")
        self.uptime_value = self._add_label_value_row(proxy_tab, status_box_sizer, "Uptime:", PROXY_STATS.get_uptime())

        proxy_sizer.Add(status_box_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # Statistics section
        stats_box = wx.StaticBox(proxy_tab, label="Statistics")
        stats_box_sizer = wx.StaticBoxSizer(stats_box, wx.VERTICAL)

        self.total_value = self._add_label_value_row(
            proxy_tab, stats_box_sizer, "Total Connections:", str(PROXY_STATS.total_connections)
        )
        self.active_value = self._add_label_value_row(
            proxy_tab, stats_box_sizer, "Active Connections:", str(PROXY_STATS.active_connections)
        )
        self.completed_value = self._add_label_value_row(
            proxy_tab, stats_box_sizer, "Completed Connections:", str(PROXY_STATS.completed_connections)
        )

        proxy_sizer.Add(stats_box_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # Settings section
        action_box = wx.StaticBox(proxy_tab, label="Settings")
        action_sizer = wx.StaticBoxSizer(action_box, wx.VERTICAL)

        controls_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Proxy Mode dropdown
        mode_sizer = wx.BoxSizer(wx.HORIZONTAL)
        mode_label = StatusLabel(proxy_tab, "Proxy Mode:")
        mode_sizer.Add(mode_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        self.proxy_mode_choice = wx.Choice(proxy_tab, choices=["Enabled (SSO)", "Enabled (Proxy Only)", "Disabled"])

        using_proxy, _ = eq_config.is_using_proxy()
        if not using_proxy:
            self.proxy_mode_choice.SetSelection(2)
        elif config.PROXY_ONLY:
            self.proxy_mode_choice.SetSelection(1)
        else:
            self.proxy_mode_choice.SetSelection(0)

        self.proxy_mode_choice.Bind(wx.EVT_CHOICE, self.on_proxy_mode_changed)
        self.proxy_mode_choice.SetToolTip(
            "Enabled (SSO): Full proxy with SSO authentication\n"
            "Enabled (Proxy Only): Proxy active but no SSO interaction ('middlemand' mode)\n"
            "Disabled: Proxy inactive, direct connection to server"
        )

        mode_sizer.Add(self.proxy_mode_choice, 0, wx.ALIGN_CENTER_VERTICAL, 0)
        controls_sizer.Add(mode_sizer, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        aot_spacer_size = 140 if platform.system() == "Windows" else 60
        controls_sizer.AddSpacer(aot_spacer_size)

        # Always on top checkbox
        self.always_on_top_cb = wx.CheckBox(proxy_tab, label="Always On Top")
        self.always_on_top_cb.SetValue(config.ALWAYS_ON_TOP)
        if config.ALWAYS_ON_TOP:
            self.SetWindowStyle(self.GetWindowStyle() | wx.STAY_ON_TOP)
        self.always_on_top_cb.Bind(wx.EVT_CHECKBOX, self.on_always_on_top)
        self.always_on_top_cb.SetToolTip("Keep the application window on top of other windows")
        controls_sizer.Add(self.always_on_top_cb, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 0)

        action_sizer.Add(controls_sizer, 0, wx.ALL | wx.LEFT, 0)

        # API Token field
        token_field_sizer = wx.BoxSizer(wx.HORIZONTAL)
        token_label = StatusLabel(proxy_tab, "API Token:")
        self.api_token_field = wx.TextCtrl(proxy_tab, style=wx.TE_PASSWORD)
        self.api_token_field.SetValue(config.USER_API_TOKEN)
        self.api_token_field.SetToolTip(
            "API Token for auto-authentication. When this is set, the password entered in the EQ UI will be ignored."
        )
        token_field_sizer.Add(token_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        token_field_sizer.Add(self.api_token_field, 1, wx.EXPAND, 0)
        self.api_token_field.Bind(wx.EVT_TEXT, self.on_api_token_changed)
        self.api_token_field.Bind(wx.EVT_SET_FOCUS, self.on_token_focus)
        self.api_token_field.Bind(wx.EVT_KILL_FOCUS, self.on_token_blur)

        action_sizer.Add(token_field_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # SSO API dropdown
        sso_api_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sso_api_label = StatusLabel(proxy_tab, "SSO API:")
        sso_api_sizer.Add(sso_api_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        known_urls = {url for _, url in config.SSO_API_OPTIONS}
        choices = [name for name, _ in config.SSO_API_OPTIONS]
        self._sso_api_url_map = [url for _, url in config.SSO_API_OPTIONS]

        if config.SSO_API in known_urls:
            selection = self._sso_api_url_map.index(config.SSO_API)
        else:
            choices.append(f"Custom: {config.SSO_API}")
            self._sso_api_url_map.append(config.SSO_API)
            selection = len(choices) - 1

        self.sso_api_choice = wx.Choice(proxy_tab, choices=choices)
        self.sso_api_choice.SetSelection(selection)
        self.sso_api_choice.Bind(wx.EVT_CHOICE, self.on_sso_api_changed)
        self.sso_api_choice.SetToolTip("Select the SSO API server endpoint")
        sso_api_sizer.Add(self.sso_api_choice, 1, wx.EXPAND)

        action_sizer.Add(sso_api_sizer, 0, wx.EXPAND | wx.ALL, 5)
        proxy_sizer.Add(action_sizer, 0, wx.ALL | wx.EXPAND, 10)

        proxy_tab.SetSizer(proxy_sizer)
        return proxy_tab

    def _create_sso_tab(self, notebook):
        sso_tab = wx.Panel(notebook)
        sso_sizer = wx.BoxSizer(wx.VERTICAL)

        sso_notebook = wx.Notebook(sso_tab)

        # Accounts sub-tab
        accounts_tab = wx.Panel(sso_notebook)
        accounts_sizer = wx.BoxSizer(wx.VERTICAL)
        self.accounts_list = self._create_list_ctrl(
            accounts_tab, [("Account Name", 150), ("Aliases", 186), ("Tags", 186)]
        )
        self._add_search_ctrl(accounts_tab, accounts_sizer, self.accounts_list)
        accounts_sizer.Add(self.accounts_list, 1, wx.ALL | wx.EXPAND, 5)
        accounts_tab.SetSizer(accounts_sizer)

        # Aliases sub-tab
        aliases_tab = wx.Panel(sso_notebook)
        aliases_sizer = wx.BoxSizer(wx.VERTICAL)
        self.aliases_list = self._create_list_ctrl(aliases_tab, [("Alias", 150), ("Account Name", 372)])
        self._add_search_ctrl(aliases_tab, aliases_sizer, self.aliases_list)
        aliases_sizer.Add(self.aliases_list, 1, wx.ALL | wx.EXPAND, 5)
        aliases_tab.SetSizer(aliases_sizer)

        # Tags sub-tab
        tags_tab = wx.Panel(sso_notebook)
        tags_sizer = wx.BoxSizer(wx.VERTICAL)
        self.tags_list = self._create_list_ctrl(tags_tab, [("Tag", 150), ("Account Names", 372)])
        self._add_search_ctrl(tags_tab, tags_sizer, self.tags_list)
        tags_sizer.Add(self.tags_list, 1, wx.ALL | wx.EXPAND, 5)
        tags_tab.SetSizer(tags_sizer)

        # Characters sub-tab
        characters_tab = wx.Panel(sso_notebook)
        characters_sizer = wx.BoxSizer(wx.VERTICAL)
        self.characters_list = self._create_list_ctrl(
            characters_tab,
            [
                ("Character", 80),
                ("Class", 82),
                ("Level", 40),
                ("Park Location", 110),
                ("Bind Location", 110),
                ("Account Name", 100),
            ],
        )
        self.characters_list.Bind(wx.EVT_LIST_COL_CLICK, self.on_characters_list_col_click)
        self._characters_sort_col = 1
        self._characters_sort_asc = True
        self._add_search_ctrl(characters_tab, characters_sizer, self.characters_list)
        characters_sizer.Add(self.characters_list, 1, wx.ALL | wx.EXPAND, 5)
        characters_tab.SetSizer(characters_sizer)

        # Local accounts sub-tab
        local_tab = wx.Panel(sso_notebook)
        local_sizer = wx.BoxSizer(wx.VERTICAL)
        self.local_accounts_list = self._create_list_ctrl(local_tab, [("Account Name", 200), ("Aliases", 322)])
        self._add_search_ctrl(local_tab, local_sizer, self.local_accounts_list)
        local_sizer.Add(self.local_accounts_list, 1, wx.ALL | wx.EXPAND, 5)

        local_buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.add_local_account_btn = wx.Button(local_tab, label="Add Account")
        self.add_local_account_btn.Bind(wx.EVT_BUTTON, self.on_add_local_account)
        local_buttons_sizer.Add(self.add_local_account_btn, 0, wx.ALL, 5)

        self.edit_local_account_btn = wx.Button(local_tab, label="Edit Account")
        self.edit_local_account_btn.Bind(wx.EVT_BUTTON, self.on_edit_local_account)
        local_buttons_sizer.Add(self.edit_local_account_btn, 0, wx.ALL, 5)

        self.delete_local_account_btn = wx.Button(local_tab, label="Delete Account")
        self.delete_local_account_btn.Bind(wx.EVT_BUTTON, self.on_delete_local_account)
        local_buttons_sizer.Add(self.delete_local_account_btn, 0, wx.ALL, 5)

        local_sizer.Add(local_buttons_sizer, 0, wx.ALL | wx.CENTER, 5)
        local_tab.SetSizer(local_sizer)

        sso_notebook.AddPage(accounts_tab, "Accounts")
        sso_notebook.AddPage(aliases_tab, "Aliases")
        sso_notebook.AddPage(tags_tab, "Tags")
        sso_notebook.AddPage(characters_tab, "Characters")
        sso_notebook.AddPage(local_tab, "Local")

        sso_sizer.Add(sso_notebook, 1, wx.ALL | wx.EXPAND, 5)

        refresh_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_accounts_btn = wx.Button(sso_tab, label="Force Reconnect")
        self.refresh_accounts_btn.Bind(wx.EVT_BUTTON, self.on_refresh_account_cache)
        self.refresh_accounts_btn.SetToolTip("Disconnect and reconnect to the SSO server for fresh data")
        refresh_btn_sizer.Add(self.refresh_accounts_btn, 0, wx.BOTTOM, 5)

        sso_sizer.Add(refresh_btn_sizer, 0, wx.ALL | wx.CENTER, 5)

        sso_tab.SetSizer(sso_sizer)
        return sso_tab

    def _create_eq_tab(self, notebook):
        eq_tab = wx.Panel(notebook)
        eq_sizer = wx.BoxSizer(wx.VERTICAL)

        # EQ Configuration section
        eq_status_box = wx.StaticBox(eq_tab, label="EverQuest Configuration")
        eq_status_sizer = wx.StaticBoxSizer(eq_status_box, wx.VERTICAL)

        eq_dir_sizer = wx.BoxSizer(wx.HORIZONTAL)
        eq_dir_label = StatusLabel(eq_tab, "EverQuest Path:")
        self.eq_dir_text = ValueLabel(eq_tab, "Checking...")
        self.browse_eq_btn = wx.Button(eq_tab, label="Browse\u2026", size=(70, -1))
        self.browse_eq_btn.Bind(wx.EVT_BUTTON, self.on_browse_eq_directory)
        self.browse_eq_btn.SetToolTip("Select the EverQuest installation directory")
        eq_dir_sizer.Add(eq_dir_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        eq_dir_sizer.Add(self.eq_dir_text, 1, wx.ALIGN_CENTER_VERTICAL)
        eq_dir_sizer.Add(self.browse_eq_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        eq_status_sizer.Add(eq_dir_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.eqhost_text = self._add_label_value_row(eq_tab, eq_status_sizer, "eqhost.txt Path:", "Checking...")

        self.eqhost_contents = wx.TextCtrl(eq_tab, style=wx.TE_MULTILINE, size=(-1, 100))
        eq_status_sizer.Add(StatusLabel(eq_tab, "eqhost.txt Content:"), 0, wx.ALL, 5)
        eq_status_sizer.Add(self.eqhost_contents, 1, wx.ALL | wx.EXPAND, 5)

        eqhost_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.save_eqhost_btn = wx.Button(eq_tab, label="Save")
        self.save_eqhost_btn.Bind(wx.EVT_BUTTON, self.on_save_eqhost)
        eqhost_btn_sizer.Add(self.save_eqhost_btn, 0, wx.ALL, 5)

        self.reset_eqhost_btn = wx.Button(eq_tab, label="Reset")
        self.reset_eqhost_btn.Bind(wx.EVT_BUTTON, self.on_reset_eqhost)
        eqhost_btn_sizer.Add(self.reset_eqhost_btn, 0, wx.ALL, 5)

        eq_status_sizer.Add(eqhost_btn_sizer, 0, wx.ALL | wx.CENTER, 5)
        eq_sizer.Add(eq_status_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Account Data section
        account_cache_box = wx.StaticBox(eq_tab, label="Account Data")
        account_cache_sizer = wx.StaticBoxSizer(account_cache_box, wx.VERTICAL)

        cache_controls_sizer = wx.BoxSizer(wx.HORIZONTAL)
        cache_info_sizer = wx.BoxSizer(wx.VERTICAL)

        self.ws_status_text = self._add_label_value_row(eq_tab, cache_info_sizer, "Live Status:", "Connecting...")
        self.ws_status_text.SetToolTip("WebSocket connection status for real-time account updates")

        self.accounts_cached_text = self._add_label_value_row(eq_tab, cache_info_sizer, "Accounts Cached:", "0")
        self.accounts_cached_text.SetToolTip("Number of accounts and aliases/tags stored in the cache")

        cache_controls_sizer.Add(cache_info_sizer, 1, wx.EXPAND, 0)

        self.refresh_cache_btn = wx.Button(eq_tab, label="Force Reconnect")
        self.refresh_cache_btn.Bind(wx.EVT_BUTTON, self.on_refresh_account_cache)
        self.refresh_cache_btn.SetToolTip("Disconnect and reconnect to the SSO server for fresh data")
        cache_controls_sizer.Add(self.refresh_cache_btn, 0, wx.ALL | wx.ALIGN_CENTER, 5)

        account_cache_sizer.Add(cache_controls_sizer, 0, wx.ALL | wx.EXPAND, 5)
        eq_sizer.Add(account_cache_sizer, 0, wx.ALL | wx.EXPAND, 10)

        eq_tab.SetSizer(eq_sizer)
        return eq_tab

    def _create_changelog_tab(self, notebook):
        changelog_tab = wx.Panel(notebook)
        changelog_sizer = wx.BoxSizer(wx.VERTICAL)

        version_history_box = wx.StaticBox(changelog_tab, label="Version History")
        version_history_sizer = wx.StaticBoxSizer(version_history_box, wx.VERTICAL)

        self.changelog_html = wx.html.HtmlWindow(version_history_box)
        version_history_sizer.Add(self.changelog_html, 1, wx.EXPAND | wx.ALL, 10)

        changelog_sizer.Add(version_history_sizer, 1, wx.EXPAND | wx.ALL, 10)
        changelog_tab.SetSizer(changelog_sizer)
        return changelog_tab

    def init_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        line = wx.StaticLine(panel)
        main_sizer.Add(line, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 5)

        notebook = wx.Notebook(panel)

        proxy_tab = self._create_proxy_tab(notebook)
        sso_tab = self._create_sso_tab(notebook)
        eq_tab = self._create_eq_tab(notebook)
        changelog_tab = self._create_changelog_tab(notebook)

        notebook.AddPage(proxy_tab, "Proxy")
        notebook.AddPage(sso_tab, "SSO")
        notebook.AddPage(eq_tab, "Advanced")
        notebook.AddPage(changelog_tab, "Changelog")

        main_sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 10)

        # Bottom buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.launch_eq_btn = wx.Button(panel, label="Launch EverQuest")
        self.launch_eq_btn.Bind(wx.EVT_BUTTON, self.on_launch_eq)
        button_sizer.Add(self.launch_eq_btn, 0, wx.ALL, 5)

        button_sizer.AddSpacer(60)

        self.exit_btn = wx.Button(panel, label="Exit")
        self.exit_btn.Bind(wx.EVT_BUTTON, self.on_exit_button)
        button_sizer.Add(self.exit_btn, 0, wx.ALL, 5)

        main_sizer.Add(button_sizer, 0, wx.ALL | wx.CENTER, 5)

        panel.SetSizer(main_sizer)
        self.Centre()

    # --- Event handlers ---

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
        self.address_value.SetLabel(f"{PROXY_STATS.listening_address}:{PROXY_STATS.listening_port}")
        self.uptime_value.SetLabel(PROXY_STATS.get_uptime())
        self.total_value.SetLabel(str(PROXY_STATS.total_connections))
        self.active_value.SetLabel(str(PROXY_STATS.active_connections))
        self.completed_value.SetLabel(str(PROXY_STATS.completed_connections))

        if self.tray_icon:
            tooltip = (
                f"{config.APP_NAME}\n"
                f"Status: {PROXY_STATS.proxy_status}\n"
                f"Connections: {PROXY_STATS.active_connections} active, "
                f"{PROXY_STATS.total_connections} total\n"
                f"Local Accounts: {len(config.LOCAL_ACCOUNTS)}\n"
                f"SSO Accounts: {config.ACCOUNTS_CACHE_REAL_COUNT}"
            )
            self.tray_icon.update_icon(tooltip=tooltip)

    def show_user_connected_notification(self, username):
        """Show a tray notification when a user connects"""
        if self.tray_icon:
            self.tray_icon.ShowBalloon(
                "User Connected",
                f"User has connected to the proxy as '{username}'.",
                3000,
            )

    def on_close(self, event):
        """Handle window close event - minimize to tray instead of closing"""
        self.Hide()
        if self.tray_icon:
            self.tray_icon.ShowBalloon(
                config.APP_NAME,
                f"{config.APP_NAME} is still running in the system tray.",
                2000,
            )

    def close_application(self):
        """Actually close the application"""
        if self.tray_icon:
            self.tray_icon.RemoveIcon()
            self.tray_icon.Destroy()

        using_proxy, _ = eq_config.is_using_proxy()
        if using_proxy:
            eq_config.disable_proxy()

        self.exit_event.set()
        self.Destroy()

    # --- Action handlers ---

    def on_launch_eq(self, event):
        eq_dir = eq_config.find_eq_directory()

        if not eq_dir:
            wx.MessageBox("EverQuest directory not found.", "Error", wx.OK | wx.ICON_ERROR)
            return

        eqgame_path = os.path.join(eq_dir, "eqgame.exe")
        try:
            if os.path.exists(eqgame_path):
                self.start_eq_func(eq_dir)
            else:
                wx.MessageBox(f"EverQuest executable not found in {eq_dir}", "Error", wx.OK | wx.ICON_ERROR)
        except Exception as e:
            logger.exception("Failed to launch EverQuest")
            wx.MessageBox(f"Failed to launch EverQuest: {e!s}", "Error", wx.OK | wx.ICON_ERROR)

    def on_proxy_mode_changed(self, event):
        selection = self.proxy_mode_choice.GetSelection()
        using_proxy, _ = eq_config.is_using_proxy()

        if selection == 0:  # Enabled (SSO)
            if not using_proxy:
                success, err = eq_config.enable_proxy()
                if not success:
                    wx.MessageBox(
                        err or "Failed to enable proxy. EverQuest directory or eqhost.txt not found.",
                        "Error",
                        wx.OK | wx.ICON_ERROR,
                    )
                    self.proxy_mode_choice.SetSelection(2)
                    return

            if config.PROXY_ONLY:
                config.set_proxy_only(False)
            if not config.PROXY_ENABLED:
                config.set_proxy_enabled(True)

        elif selection == 1:  # Enabled (Proxy Only)
            if not using_proxy:
                success, err = eq_config.enable_proxy()
                if not success:
                    wx.MessageBox(
                        err or "Failed to enable proxy. EverQuest directory or eqhost.txt not found.",
                        "Error",
                        wx.OK | wx.ICON_ERROR,
                    )
                    self.proxy_mode_choice.SetSelection(2)
                    return

            if not config.PROXY_ONLY:
                config.set_proxy_only(True)
            if not config.PROXY_ENABLED:
                config.set_proxy_enabled(True)

        elif selection == 2:  # Disabled
            if using_proxy:
                success, err = eq_config.disable_proxy()
                if not success:
                    wx.MessageBox(
                        err or "Failed to disable proxy. EverQuest directory or eqhost.txt not found.",
                        "Error",
                        wx.OK | wx.ICON_ERROR,
                    )
                    self.proxy_mode_choice.SetSelection(0 if not config.PROXY_ONLY else 1)
                    return

            if config.PROXY_ONLY:
                config.set_proxy_only(False)
            if config.PROXY_ENABLED:
                config.set_proxy_enabled(False)

        self.update_eq_status()

    def on_updated_changelog(self):
        self.changelog_html.SetPage(config.CHANGELOG)
        self.changelog_html.SetHTMLBackgroundColour("#f9f9f9")

    def on_sso_api_changed(self, event):
        """Handle SSO API dropdown selection change."""
        idx = self.sso_api_choice.GetSelection()
        url = self._sso_api_url_map[idx]
        if url != config.SSO_API:
            config.set_sso_api(url)
            ws_client.request_reconnect()

    def on_browse_eq_directory(self, event):
        """Let the user pick the EverQuest installation directory."""
        dlg = wx.DirDialog(
            self,
            "Select EverQuest Directory",
            defaultPath=config.EQ_DIRECTORY or "",
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            chosen = dlg.GetPath()
            if not eq_config.is_valid_eq_directory(chosen):
                wx.MessageBox(
                    f"eqgame.exe was not found in:\n{chosen}\n\nPlease select a directory containing eqgame.exe.",
                    "Invalid Directory",
                    wx.OK | wx.ICON_WARNING,
                )
            else:
                config.set_eq_directory(chosen)
                eq_config.clear_cache()
                self.update_eq_status()
        dlg.Destroy()

    def on_save_eqhost(self, event):
        eq_dir = eq_config.find_eq_directory()
        if not eq_dir:
            logger.error("EverQuest directory not found when trying to save eqhost.txt")
            return

        eqhost_path = os.path.join(eq_dir, "eqhost.txt")
        content = self.eqhost_contents.GetValue()

        try:
            with open(eqhost_path, "w") as f:
                f.write(content)
            logger.info("Successfully wrote to eqhost.txt at %s", eqhost_path)
            self.update_eq_status()
        except Exception:
            logger.exception("Failed to save eqhost.txt")

    def on_reset_eqhost(self, event):
        self.update_eq_status()

    def on_always_on_top(self, event):
        is_checked = self.always_on_top_cb.GetValue()
        if is_checked:
            self.SetWindowStyle(self.GetWindowStyle() | wx.STAY_ON_TOP)
        else:
            self.SetWindowStyle(self.GetWindowStyle() & ~wx.STAY_ON_TOP)
        config.set_always_on_top(is_checked)

    def on_api_token_changed(self, event):
        token = self.api_token_field.GetValue()
        config.set_user_api_token(token)
        self._schedule_ws_reconnect()

    def on_token_focus(self, event):
        logger.debug("API token field focused")
        handle = self.api_token_field.GetHandle()
        if handle:
            if platform.system() == "Windows":
                import win32api
                import win32con

                win32api.SendMessage(handle, win32con.EM_SETPASSWORDCHAR, 0, 0)
            else:
                style = self.api_token_field.GetWindowStyleFlag()
                style &= ~wx.TE_PASSWORD
                self.api_token_field.SetWindowStyleFlag(style)
        event.Skip()

    def on_token_blur(self, event):
        logger.debug("API token field blurred")
        handle = self.api_token_field.GetHandle()
        if handle:
            if platform.system() == "Windows":
                import win32api
                import win32con

                win32api.SendMessage(handle, win32con.EM_SETPASSWORDCHAR, 0x25CF, 0)
            else:
                style = self.api_token_field.GetWindowStyleFlag()
                style |= wx.TE_PASSWORD
                self.api_token_field.SetWindowStyleFlag(style)
        event.Skip()

    def on_refresh_account_cache(self, event):
        """Force a WebSocket reconnect for a fresh full_state."""
        config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNT_NAME_MAP = utils.load_local_accounts(config.LOCAL_ACCOUNTS_FILE)
        ws_client.request_reconnect()
        if hasattr(self, "ws_status_text"):
            self.ws_status_text.SetLabel("Connecting...")
            self.ws_status_text.SetForegroundColour(COLOR_WARNING)
            self.ws_status_text.Refresh()
        self.update_account_cache_display()

    def on_exit_button(self, event):
        """Exit the application when the exit button is clicked"""
        self.close_application()

    def set_icon(self):
        path = utils.find_resource_path("tray_icon.png")
        if path:
            try:
                icon = wx.Icon(path, wx.BITMAP_TYPE_ANY)
                self.SetIcon(icon)
                if self.tray_icon:
                    self.tray_icon.SetIcon(icon, config.APP_NAME)
            except Exception:
                logger.warning("Failed to load icon from %s", path, exc_info=True)

    def _on_char_fade_tick(self, event=None):
        """Re-render the characters list so activity background colours fade over time."""
        if hasattr(self, "characters_list") and self.characters_list in self._list_filter_data:
            self._apply_filter(self.characters_list)

    def _schedule_ws_reconnect(self, delay_ms=1500):
        """Debounce: restart the timer so the reconnect fires only after the user stops typing."""
        self._ws_reconnect_timer.Stop()
        self._ws_reconnect_timer.StartOnce(delay_ms)

    def _on_ws_reconnect_debounce(self, event=None):
        """Fires after the debounce period -- trigger a WS reconnect."""
        ws_client.request_reconnect()

    def _on_ws_status_tick(self, event=None):
        """Periodically update the WebSocket connection status label."""
        if not hasattr(self, "ws_status_text"):
            return
        if ws_client.is_connected():
            self.ws_status_text.SetLabel("Connected (Live)")
            self.ws_status_text.SetForegroundColour(COLOR_SUCCESS)
        elif ws_client.is_auth_failed():
            self.ws_status_text.SetLabel("Auth Failed")
            self.ws_status_text.SetForegroundColour(COLOR_ERROR)
        elif config.USER_API_TOKEN:
            self.ws_status_text.SetLabel("Connecting...")
            self.ws_status_text.SetForegroundColour(COLOR_WARNING)
        else:
            self.ws_status_text.SetLabel("No API Token")
            self.ws_status_text.SetForegroundColour(COLOR_MUTED)
        self.ws_status_text.Refresh()

    # --- Local account management ---

    def on_add_local_account(self, event):
        """Add a new local account"""
        dialog = local_account_dialog.LocalAccountDialog(self, title="Add Local Account")
        if dialog.ShowModal() == wx.ID_OK:
            account_name = dialog.account_name.GetValue().strip()
            password = dialog.password.GetValue().strip()
            aliases_text = dialog.aliases.GetValue().strip()

            if not account_name:
                wx.MessageBox("Account name cannot be empty.", "Error", wx.OK | wx.ICON_ERROR)
                return

            if not password:
                wx.MessageBox("Password cannot be empty.", "Error", wx.OK | wx.ICON_ERROR)
                return

            if account_name in config.LOCAL_ACCOUNTS:
                wx.MessageBox(f"Account '{account_name}' already exists.", "Error", wx.OK | wx.ICON_ERROR)
                return

            aliases = [alias.strip() for alias in aliases_text.split(",") if alias.strip()]
            config.LOCAL_ACCOUNTS[account_name] = {
                "password": password,
                "aliases": aliases,
            }
            config.LOCAL_ACCOUNT_NAME_MAP[account_name] = account_name
            for alias in aliases:
                config.LOCAL_ACCOUNT_NAME_MAP[alias] = account_name

            if not utils.save_local_accounts(config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNTS_FILE):
                wx.MessageBox("Failed to save local accounts.", "Error", wx.OK | wx.ICON_ERROR)
            self.update_account_cache_display()

        dialog.Destroy()

    def on_edit_local_account(self, event):
        """Edit an existing local account"""
        selected_index = self.local_accounts_list.GetFirstSelected()
        if selected_index == -1:
            wx.MessageBox("Please select an account to edit.", "Error", wx.OK | wx.ICON_ERROR)
            return

        account_name = self.local_accounts_list.GetItemText(selected_index, 0)
        if account_name not in config.LOCAL_ACCOUNTS:
            wx.MessageBox(f"Account '{account_name}' not found.", "Error", wx.OK | wx.ICON_ERROR)
            return

        account_data = config.LOCAL_ACCOUNTS[account_name]
        dialog = local_account_dialog.LocalAccountDialog(
            self,
            title="Edit Local Account",
            account_name=account_name,
            password=account_data.get("password", ""),
            aliases=", ".join(account_data.get("aliases", [])),
        )
        dialog.account_name.Disable()

        if dialog.ShowModal() == wx.ID_OK:
            password = dialog.password.GetValue().strip()
            aliases_text = dialog.aliases.GetValue().strip()

            if not password:
                wx.MessageBox("Password cannot be empty.", "Error", wx.OK | wx.ICON_ERROR)
                return

            aliases = [alias.strip() for alias in aliases_text.split(",") if alias.strip()]

            for alias in account_data.get("aliases", []):
                if alias in config.LOCAL_ACCOUNT_NAME_MAP:
                    del config.LOCAL_ACCOUNT_NAME_MAP[alias]

            config.LOCAL_ACCOUNTS[account_name] = {
                "password": password,
                "aliases": aliases,
            }
            for alias in aliases:
                config.LOCAL_ACCOUNT_NAME_MAP[alias] = account_name

            if not utils.save_local_accounts(config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNTS_FILE):
                wx.MessageBox("Failed to save local accounts.", "Error", wx.OK | wx.ICON_ERROR)
            self.update_account_cache_display()

        dialog.Destroy()

    def on_delete_local_account(self, event):
        """Delete a local account"""
        selected_index = self.local_accounts_list.GetFirstSelected()
        if selected_index == -1:
            wx.MessageBox("Please select an account to delete.", "Error", wx.OK | wx.ICON_ERROR)
            return

        account_name = self.local_accounts_list.GetItemText(selected_index, 0)
        if account_name not in config.LOCAL_ACCOUNTS:
            wx.MessageBox(f"Account '{account_name}' not found.", "Error", wx.OK | wx.ICON_ERROR)
            return

        if (
            wx.MessageBox(
                f"Are you sure you want to delete the account '{account_name}'?",
                "Confirm Deletion",
                wx.YES_NO | wx.ICON_QUESTION,
            )
            != wx.YES
        ):
            return

        account_data = config.LOCAL_ACCOUNTS[account_name]
        for alias in account_data.get("aliases", []):
            if alias in config.LOCAL_ACCOUNT_NAME_MAP:
                del config.LOCAL_ACCOUNT_NAME_MAP[alias]

        if account_name in config.LOCAL_ACCOUNT_NAME_MAP:
            del config.LOCAL_ACCOUNT_NAME_MAP[account_name]

        del config.LOCAL_ACCOUNTS[account_name]

        if not utils.save_local_accounts(config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNTS_FILE):
            wx.MessageBox("Failed to save local accounts.", "Error", wx.OK | wx.ICON_ERROR)
        self.update_account_cache_display()

    def on_characters_list_col_click(self, event):
        col = event.GetColumn()
        if self._characters_sort_col == col:
            self._characters_sort_asc = not self._characters_sort_asc
        else:
            self._characters_sort_col = col
            self._characters_sort_asc = True
        self.update_account_cache_display()

    # --- Display update methods ---

    def update_account_cache_display(self):
        """Update the account cache display"""
        total_accounts = len(config.ALL_CACHED_NAMES)
        real_accounts = config.ACCOUNTS_CACHE_REAL_COUNT

        if total_accounts == 0:
            self.accounts_cached_text.SetLabel("None")
            self.accounts_cached_text.SetForegroundColour(COLOR_MUTED)
        else:
            self.accounts_cached_text.SetLabel(
                f"{real_accounts} accounts, {total_accounts - real_accounts} aliases/tags"
            )
            self.accounts_cached_text.SetForegroundColour(COLOR_SUCCESS)

        # Local accounts
        local_rows = []
        for account, data in sorted(config.LOCAL_ACCOUNTS.items()):
            aliases = data.get("aliases", [])
            local_rows.append((account, ", ".join(sorted(aliases)) if aliases else ""))
        self._populate_list(self.local_accounts_list, local_rows)

        # SSO accounts
        account_rows = []
        for account, data in sorted(config.ACCOUNTS_CACHED.items()):
            aliases = ", ".join(sorted(data.get("aliases", [])))
            tags = ", ".join(sorted(data.get("tags", [])))
            account_rows.append((account, aliases, tags))
        self._populate_list(self.accounts_list, account_rows)

        # Aliases
        all_aliases = []
        for account, data in config.ACCOUNTS_CACHED.items():
            for alias in sorted(data.get("aliases", [])):
                all_aliases.append((alias, account))
        all_aliases.sort()
        self._populate_list(self.aliases_list, all_aliases)

        # Tags
        tag_to_accounts = {}
        for account, data in config.ACCOUNTS_CACHED.items():
            for tag in sorted(data.get("tags", [])):
                tag_to_accounts.setdefault(tag, []).append(account)
        tag_rows = [(tag, ", ".join(sorted(accounts))) for tag, accounts in sorted(tag_to_accounts.items())]
        self._populate_list(self.tags_list, tag_rows)

        # Characters -- last_login appended as hidden 7th element for activity colouring
        all_characters = []
        for account, data in config.ACCOUNTS_CACHED.items():
            last_login = data.get("last_login")
            characters = data.get("characters", {})
            for character in sorted(characters):
                bind_text = zone_translate.zonekey_to_zone(characters[character]["bind"])
                park_text = zone_translate.zonekey_to_zone(characters[character]["park"])
                class_text = characters[character]["class"]
                level = characters[character].get("level")
                level_text = str(level) if level is not None else ""
                all_characters.append((character, class_text, level_text, park_text, bind_text, account, last_login))

        sort_col = self._characters_sort_col
        sort_asc = self._characters_sort_asc
        all_characters.sort(key=lambda x: ((x[sort_col] or ""), x[0]), reverse=not sort_asc)

        char_rows = [
            (char, klass, lvl, park or "Unknown", bind or "Unknown", acct, ll)
            for char, klass, lvl, park, bind, acct, ll in all_characters
        ]
        self._populate_list(
            self.characters_list,
            char_rows,
            row_color_fn=lambda row: _activity_colour(row[6]),
        )

    def update_eq_status(self):
        """Update the EverQuest configuration status display"""
        status = eq_config.get_eq_status()

        self.update_account_cache_display()

        if status["eq_directory_found"]:
            self.eq_dir_text.SetLabel(f"{status['eq_directory']}")
            self.eq_dir_text.SetForegroundColour(COLOR_SUCCESS)
            log_handler.set_log_watch_directory(status["eq_directory"], self)
        else:
            self.eq_dir_text.SetLabel("Not Found")
            self.eq_dir_text.SetForegroundColour(COLOR_ERROR)

        if status["eqhost_found"]:
            self.eqhost_text.SetLabel(f"{status['eqhost_path']}")
            self.eqhost_text.SetForegroundColour(COLOR_SUCCESS)
        else:
            self.eqhost_text.SetLabel("Not Found")
            self.eqhost_text.SetForegroundColour(COLOR_ERROR)

        if status["using_proxy"]:
            self.proxy_status_text.SetLabel("Enabled")
            self.proxy_status_text.SetForegroundColour(COLOR_SUCCESS)
        else:
            self.proxy_status_text.SetLabel("Disabled")
            self.proxy_status_text.SetForegroundColour(COLOR_DARK_RED)

        self.eqhost_contents.Clear()
        if status["eqhost_contents"]:
            self.eqhost_contents.AppendText("\n".join(status["eqhost_contents"]))

        if not status["using_proxy"]:
            self.proxy_mode_choice.SetSelection(2)
        elif config.PROXY_ONLY:
            self.proxy_mode_choice.SetSelection(1)
        else:
            self.proxy_mode_choice.SetSelection(0)

        if self.tray_icon:
            self.tray_icon.update_icon()


def start_ui():
    """Initialize and start the UI"""
    main_window = ProxyUI()
    main_window.Show()
    main_window.Bind(wx.EVT_CLOSE, main_window.on_close)
    return main_window
