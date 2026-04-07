import datetime
import logging
import os
import platform
import threading
from collections import deque
from heapq import merge as _heapmerge

import wx
import wx.html

from p99_sso_login_proxy import config, eq_config, log_handler, update_scheduler, utils, ws_client, zone_translate
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
COLOR_ACTIVE_AMBER = wx.Colour(255, 195, 120)
COLOR_ACTIVE_BLUE = wx.Colour(130, 170, 255)

# Characters list key columns: wx.ListCtrl plain text — use BMP symbols (not emoji) for reliable display.
KEY_COLUMN_YES = "\u2713"  # check mark
KEY_COLUMN_NO = "\u2717"  # ballot X

# Characters list: ST, VP, Sb columns (indices 3-5); sort by logical key state, not Unicode order.
_KEY_COLUMNS = frozenset({3, 4, 5})
_KEY_SORT_ORDER = {KEY_COLUMN_YES: 0, KEY_COLUMN_NO: 1, "": 2}
# Search filter: stkey / vpkey / sebkey match only characters with that key (checkmark); no substring OR.
_KEY_FILTER_TERMS = {"stkey": 3, "vpkey": 4, "sebkey": 5}
# Substring filter skips these columns (Logged In By, Account Name).
_CHARACTERS_FILTER_SKIP_COLS = frozenset({8, 9})


def _characters_key_term_match(row: tuple, term: str) -> bool:
    col = _KEY_FILTER_TERMS.get(term)
    return col is not None and row[col] == KEY_COLUMN_YES


def _characters_tab_key_cell(value: bool | None) -> str:
    if value is True:
        return KEY_COLUMN_YES
    if value is False:
        return KEY_COLUMN_NO
    return ""


# SSO sends full CharacterClass enum names; shorten a few for the Characters tab column width
_CHARACTERS_TAB_CLASS_SHORT = {
    "Necromancer": "Necro",
    "ShadowKnight": "SK",
}


def _characters_tab_class_display(klass: str | None) -> str:
    if not klass:
        return ""
    return _CHARACTERS_TAB_CLASS_SHORT.get(klass, klass)


_LOG_LEVEL_COLORS = {
    logging.DEBUG: wx.Colour(128, 128, 128),
    logging.INFO: wx.Colour(0, 0, 0),
    logging.WARNING: wx.Colour(200, 120, 0),
    logging.ERROR: wx.Colour(220, 0, 0),
    logging.CRITICAL: wx.Colour(160, 0, 0),
}

_LOG_LEVEL_NAMES = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class WxLogHandler(logging.Handler):
    """Logging handler with independent per-level ring buffers.

    Each standard level (DEBUG … CRITICAL) keeps its own history so a flood of
    DEBUG messages never evicts WARNING/ERROR history.  When the display level
    changes the buffers are merged in chronological order and re-rendered.
    """

    MAX_PER_LEVEL = 5_000
    MAX_DISPLAY_CHARS = 500_000
    _LEVELS = (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL)

    def __init__(self, text_ctrl: wx.TextCtrl, auto_scroll_cb: wx.CheckBox, level_choice: wx.Choice):
        super().__init__(level=logging.DEBUG)
        self._text_ctrl = text_ctrl
        self._auto_scroll_cb = auto_scroll_cb
        self._level_choice = level_choice
        self._buffers: dict[int, deque[tuple[int, str, int]]] = {
            lvl: deque(maxlen=self.MAX_PER_LEVEL) for lvl in self._LEVELS
        }
        self._seq = 0
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    @property
    def _display_level(self) -> int:
        name = self._level_choice.GetStringSelection()
        return getattr(logging, name, logging.INFO)

    def _bucket(self, levelno: int) -> int:
        """Map an arbitrary numeric level to the nearest standard level."""
        for lvl in reversed(self._LEVELS):
            if levelno >= lvl:
                return lvl
        return self._LEVELS[0]

    def emit(self, record):
        try:
            msg = self.format(record)
            wx.CallAfter(self._on_record, msg, record.levelno)
        except Exception:
            self.handleError(record)

    def _on_record(self, msg: str, levelno: int):
        try:
            ctrl = self._text_ctrl
            if not ctrl:
                return
        except RuntimeError:
            return

        self._seq += 1
        self._buffers[self._bucket(levelno)].append((self._seq, msg, levelno))
        if levelno >= self._display_level:
            self._write_line(msg, levelno)

    def _write_line(self, msg: str, levelno: int):
        ctrl = self._text_ctrl
        auto = self._auto_scroll_cb.GetValue()
        if not auto:
            ctrl.Freeze()

        colour = _LOG_LEVEL_COLORS.get(levelno, wx.Colour(0, 0, 0))
        ctrl.SetDefaultStyle(wx.TextAttr(colour))
        ctrl.AppendText(msg + "\n")

        if ctrl.GetLastPosition() > self.MAX_DISPLAY_CHARS:
            ctrl.Remove(0, ctrl.GetLastPosition() // 4)

        if auto:
            ctrl.ShowPosition(ctrl.GetLastPosition())
        else:
            ctrl.Thaw()

    def refilter(self):
        """Re-render the display by merging per-level buffers chronologically."""
        try:
            ctrl = self._text_ctrl
            if not ctrl:
                return
        except RuntimeError:
            return

        display_level = self._display_level
        merged = _heapmerge(*(buf for lvl, buf in self._buffers.items() if lvl >= display_level))

        # Avoid Freeze/Thaw here: wx.TE_RICH2 on Windows often leaves the viewport
        # blank until the next paint if frozen while repopulating a large buffer.
        ctrl.Clear()
        for _seq, msg, levelno in merged:
            colour = _LOG_LEVEL_COLORS.get(levelno, wx.Colour(0, 0, 0))
            ctrl.SetDefaultStyle(wx.TextAttr(colour))
            ctrl.AppendText(msg + "\n")

        auto = self._auto_scroll_cb.GetValue()

        def _scroll_after_layout() -> None:
            """Run after layout: RichEdit needs a deferred scroll or the view stays blank."""
            try:
                c = self._text_ctrl
                if not c:
                    return
            except RuntimeError:
                return
            last = c.GetLastPosition()
            if auto:
                c.SetInsertionPointEnd()
                if last > 0:
                    c.ShowPosition(last)
            else:
                c.SetInsertionPoint(0)
                c.ShowPosition(0)
            c.Refresh()
            c.Update()

        wx.CallAfter(_scroll_after_layout)

    def clear_buffer(self):
        """Clear both the display and all backing buffers."""
        for buf in self._buffers.values():
            buf.clear()
        self._seq = 0
        try:
            if self._text_ctrl:
                self._text_ctrl.Clear()
        except RuntimeError:
            pass


def _activity_colour(last_login_iso: str | None, base_color: wx.Colour = COLOR_ACTIVE_AMBER) -> wx.Colour | None:
    """Return a background colour that fades from *base_color* to transparent over config.ACTIVITY_FADE_SECONDS.

    Returns None once fully faded so normal alternating-row colours apply.
    """
    if not last_login_iso:
        return None
    try:
        then = datetime.datetime.fromisoformat(last_login_iso)
    except (ValueError, TypeError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=datetime.UTC)
    elapsed = (datetime.datetime.now(tz=datetime.UTC) - then).total_seconds()
    if elapsed < 0:
        elapsed = 0
    if elapsed >= config.ACTIVITY_FADE_SECONDS:
        return None
    bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOX)
    t = elapsed / config.ACTIVITY_FADE_SECONDS
    r = int(base_color.Red() + (bg.Red() - base_color.Red()) * t)
    g = int(base_color.Green() + (bg.Green() - base_color.Green()) * t)
    b = int(base_color.Blue() + (bg.Blue() - base_color.Blue()) * t)
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
        size = (708, 550) if platform.system() == "Windows" else (760, 664)
        super().__init__(parent, id, title, size=size, style=wx.DEFAULT_FRAME_STYLE)
        self.SetMinSize((708, 550))

        self.exit_event = threading.Event()
        self._list_filter_data = {}
        self._ws_error_shown = False

        PROXY_STATS.add_listener(self)
        self.Bind(proxy_stats.EVT_STATS_UPDATED_BINDER, self.on_stats_updated)
        self.Bind(proxy_stats.EVT_USER_CONNECTED_BINDER, self.on_user_connected)
        self.Bind(proxy_stats.EVT_AUTH_ERROR_BINDER, self.on_auth_error)

        self.init_ui()

        self._log_handler = WxLogHandler(self.log_text, self.log_auto_scroll_cb, self.log_level_choice)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(self._log_handler)

        self.tray_icon = taskbar_icon.create_tray_icon(self)

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

        update_scheduler.start()

        self.set_icon()

        if config.PROXY_ENABLED and eq_config.find_eq_directory():
            eq_config.enable_proxy()

        eq_config.ensure_eqclient_log_enabled()

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
        top_item = list_ctrl.GetTopItem()
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
        if top_item > 0 and rows:
            target = min(top_item, len(rows) - 1)
            list_ctrl.EnsureVisible(len(rows) - 1)
            list_ctrl.EnsureVisible(target)

    def _apply_filter(self, list_ctrl):
        """Re-render a list applying the current search filter.

        Each whitespace-separated word acts as a stacking filter: a row must
        match every word (in any column) to be included. Optional
        filter_skip_columns excludes column indices from substring matching.
        """
        data = self._list_filter_data[list_ctrl]
        num_cols = list_ctrl.GetColumnCount()
        row_color_fn = data.get("row_color_fn")
        term_match_fn = data.get("term_match_fn")
        skip_cols = data.get("filter_skip_columns") or frozenset()
        terms = data["search"].GetValue().lower().split()
        if not terms:
            self._render_list(list_ctrl, data["rows"], row_color_fn)
        else:

            def matches(row, t):
                if term_match_fn and t in _KEY_FILTER_TERMS:
                    return term_match_fn(row, t)
                if any(t in str(row[i]).lower() for i in range(num_cols) if i not in skip_cols and i < len(row)):
                    return True
                return term_match_fn(row, t) if term_match_fn else False

            filtered = [row for row in data["rows"] if all(matches(row, t) for t in terms)]
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

        top_row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        top_row_sizer.Add(status_box_sizer, 1, wx.EXPAND | wx.RIGHT, 5)
        top_row_sizer.Add(stats_box_sizer, 1, wx.EXPAND | wx.LEFT, 5)
        proxy_sizer.Add(top_row_sizer, 0, wx.EXPAND | wx.ALL, 10)

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

        controls_sizer.AddStretchSpacer(1)

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

        known_names = {name for name, _ in config.SSO_API_OPTIONS}
        choices = [name for name, _ in config.SSO_API_OPTIONS]
        self._sso_api_url_map = [url for _, url in config.SSO_API_OPTIONS]
        self._sso_api_name_map = list(choices)

        if config.SSO_API_NAME in known_names:
            selection = self._sso_api_name_map.index(config.SSO_API_NAME)
        else:
            custom_label = f"Custom: {config.SSO_API}"
            choices.append(custom_label)
            self._sso_api_url_map.append(config.SSO_API)
            self._sso_api_name_map.append(custom_label)
            selection = len(choices) - 1

        self.sso_api_choice = wx.Choice(proxy_tab, choices=choices)
        self.sso_api_choice.SetSelection(selection)
        self.sso_api_choice.Bind(wx.EVT_CHOICE, self.on_sso_api_changed)
        self.sso_api_choice.SetToolTip("Select the SSO API server endpoint")
        sso_api_sizer.Add(self.sso_api_choice, 1, wx.EXPAND)

        action_sizer.Add(sso_api_sizer, 0, wx.EXPAND | wx.ALL, 5)
        proxy_sizer.Add(action_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Account Data section
        account_cache_box = wx.StaticBox(proxy_tab, label="Account Data")
        account_cache_sizer = wx.StaticBoxSizer(account_cache_box, wx.VERTICAL)

        cache_controls_sizer = wx.BoxSizer(wx.HORIZONTAL)
        cache_info_sizer = wx.BoxSizer(wx.VERTICAL)

        self.ws_status_text = self._add_label_value_row(proxy_tab, cache_info_sizer, "SSO Service:", "Connecting...")
        self.ws_status_text.SetToolTip("WebSocket connection status for real-time account updates")

        self.accounts_cached_text = self._add_label_value_row(proxy_tab, cache_info_sizer, "Accounts:", "0")
        self.accounts_cached_text.SetToolTip("Number of accounts, characters, and aliases/tags")

        cache_controls_sizer.Add(cache_info_sizer, 1, wx.EXPAND, 0)

        self.refresh_cache_btn = wx.Button(proxy_tab, label="Force Reconnect")
        self.refresh_cache_btn.Bind(wx.EVT_BUTTON, self.on_refresh_account_cache)
        self.refresh_cache_btn.SetToolTip("Disconnect and reconnect to the SSO server for fresh data")
        cache_controls_sizer.Add(self.refresh_cache_btn, 0, wx.ALL | wx.ALIGN_CENTER, 5)

        account_cache_sizer.Add(cache_controls_sizer, 0, wx.ALL | wx.EXPAND, 5)
        proxy_sizer.Add(account_cache_sizer, 0, wx.ALL | wx.EXPAND, 10)

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
            accounts_tab, [("Account Name", 114), ("Aliases", 250), ("Tags", 250)]
        )
        self._add_search_ctrl(accounts_tab, accounts_sizer, self.accounts_list)
        accounts_sizer.Add(self.accounts_list, 1, wx.ALL | wx.EXPAND, 5)
        accounts_tab.SetSizer(accounts_sizer)

        # Aliases sub-tab
        aliases_tab = wx.Panel(sso_notebook)
        aliases_sizer = wx.BoxSizer(wx.VERTICAL)
        self.aliases_list = self._create_list_ctrl(aliases_tab, [("Alias", 100), ("Account Name", 114)])
        self._add_search_ctrl(aliases_tab, aliases_sizer, self.aliases_list)
        aliases_sizer.Add(self.aliases_list, 1, wx.ALL | wx.EXPAND, 5)
        aliases_tab.SetSizer(aliases_sizer)

        # Tags sub-tab
        tags_tab = wx.Panel(sso_notebook)
        tags_sizer = wx.BoxSizer(wx.VERTICAL)
        self.tags_list = self._create_list_ctrl(tags_tab, [("Tag", 100), ("Account Names", 514)])
        self._add_search_ctrl(tags_tab, tags_sizer, self.tags_list)
        tags_sizer.Add(self.tags_list, 1, wx.ALL | wx.EXPAND, 5)
        tags_tab.SetSizer(tags_sizer)

        # Characters sub-tab
        characters_tab = wx.Panel(sso_notebook)
        characters_sizer = wx.BoxSizer(wx.VERTICAL)
        self.characters_list = self._create_list_ctrl(
            characters_tab,
            [
                ("Character", 90),
                ("Class", 68),
                ("Lvl", 30),
                ("ST", 26),
                ("VP", 26),
                ("Sb", 26),
                ("Park Location", 124),
                ("Bind Location", 124),
                ("Logged In By", 98),
                ("Account Name", 100),
            ],
        )
        self.characters_list.Bind(wx.EVT_LIST_COL_CLICK, self.on_characters_list_col_click)
        self._characters_sort_col = 1
        self._characters_sort_asc = True
        search_ctrl = self._add_search_ctrl(characters_tab, characters_sizer, self.characters_list)
        self._list_filter_data[self.characters_list]["term_match_fn"] = _characters_key_term_match
        self._list_filter_data[self.characters_list]["filter_skip_columns"] = _CHARACTERS_FILTER_SKIP_COLS
        characters_sizer.Detach(search_ctrl)

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_row.Add(search_ctrl, 1, wx.EXPAND)

        def _make_swatch(parent, colour, label):
            swatch = wx.Panel(parent, size=(12, 12))
            swatch.SetBackgroundColour(colour)
            swatch.SetMinSize((12, 12))
            text = wx.StaticText(parent, label=label)
            return swatch, text

        for colour, label in ((COLOR_ACTIVE_AMBER, "Logged In"), (COLOR_ACTIVE_BLUE, "Blocked")):
            swatch, text = _make_swatch(characters_tab, colour, label)
            search_row.Add(swatch, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
            search_row.Add(text, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 3)

        characters_sizer.Add(search_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)
        characters_sizer.Add(self.characters_list, 1, wx.ALL | wx.EXPAND, 5)
        characters_tab.SetSizer(characters_sizer)

        # Local accounts sub-tab
        local_tab = wx.Panel(sso_notebook)
        local_sizer = wx.BoxSizer(wx.VERTICAL)
        self.local_accounts_list = self._create_list_ctrl(local_tab, [("Account Name", 114), ("Aliases", 500)])
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

        sso_notebook.AddPage(characters_tab, "Characters")
        sso_notebook.AddPage(accounts_tab, "Accounts")
        sso_notebook.AddPage(aliases_tab, "Aliases")
        sso_notebook.AddPage(tags_tab, "Tags")
        sso_notebook.AddPage(local_tab, "Local Accounts")

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

        self.eqhost_contents = wx.TextCtrl(eq_tab, style=wx.TE_MULTILINE)
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
        eq_sizer.Add(eq_status_sizer, 1, wx.ALL | wx.EXPAND, 10)

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

    def _make_log_text_ctrl(self, parent, word_wrap=False):
        style = wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2
        if not word_wrap:
            style |= wx.HSCROLL
        ctrl = wx.TextCtrl(parent, style=style)
        ctrl.SetFont(self._log_font)
        return ctrl

    def _create_log_tab(self, notebook):
        log_tab = wx.Panel(notebook)
        log_sizer = wx.BoxSizer(wx.VERTICAL)

        controls_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.log_auto_scroll_cb = wx.CheckBox(log_tab, label="Auto-scroll")
        self.log_auto_scroll_cb.SetValue(True)
        controls_sizer.Add(self.log_auto_scroll_cb, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        self.log_word_wrap_cb = wx.CheckBox(log_tab, label="Word wrap")
        self.log_word_wrap_cb.SetValue(False)
        self.log_word_wrap_cb.Bind(wx.EVT_CHECKBOX, self._on_log_word_wrap)
        controls_sizer.Add(self.log_word_wrap_cb, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 15)

        level_label = wx.StaticText(log_tab, label="Level:")
        controls_sizer.Add(level_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        self.log_level_choice = wx.Choice(log_tab, choices=_LOG_LEVEL_NAMES)
        self.log_level_choice.SetSelection(_LOG_LEVEL_NAMES.index("INFO"))
        self.log_level_choice.Bind(wx.EVT_CHOICE, self._on_log_level_changed)
        controls_sizer.Add(self.log_level_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 15)

        clear_btn = wx.Button(log_tab, label="Clear")
        clear_btn.Bind(wx.EVT_BUTTON, self._on_log_clear)
        controls_sizer.Add(clear_btn, 0, wx.ALIGN_CENTER_VERTICAL)

        log_sizer.Add(controls_sizer, 0, wx.ALL, 5)

        self._log_font = wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        self.log_text = self._make_log_text_ctrl(log_tab, word_wrap=False)
        log_sizer.Add(self.log_text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        log_tab.SetSizer(log_sizer)
        return log_tab

    def init_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        line = wx.StaticLine(panel)
        main_sizer.Add(line, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 5)

        notebook = wx.Notebook(panel)

        proxy_tab = self._create_proxy_tab(notebook)
        sso_tab = self._create_sso_tab(notebook)
        eq_tab = self._create_eq_tab(notebook)
        log_tab = self._create_log_tab(notebook)
        changelog_tab = self._create_changelog_tab(notebook)

        notebook.AddPage(proxy_tab, "Proxy")
        notebook.AddPage(sso_tab, "SSO")
        notebook.AddPage(eq_tab, "Advanced")
        notebook.AddPage(log_tab, "Log")
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
        self._update_tray_tooltip()

    def on_user_connected(self, event):
        """Handle user connected event"""
        alias = event.GetAlias()
        account = event.GetAccount()
        method = event.GetMethod()

        if alias != account:
            self.last_username_label.SetLabel(f"{alias} \u2192 {account}")
        else:
            self.last_username_label.SetLabel(account)

        self.show_user_connected_notification(alias, account, method)

    def on_auth_error(self, event):
        """Handle server-rejected auth attempt — show a one-time popup per message."""
        detail = event.GetDetail() or "Authentication rejected by server"
        wx.MessageBox(detail, "SSO Login Rejected", wx.OK | wx.ICON_WARNING)

    def update_stats(self, event=None):
        """Update all statistics in the UI"""
        self.address_value.SetLabel(f"{PROXY_STATS.listening_address}:{PROXY_STATS.listening_port}")
        self.uptime_value.SetLabel(PROXY_STATS.get_uptime())
        self.total_value.SetLabel(str(PROXY_STATS.total_connections))
        self.active_value.SetLabel(str(PROXY_STATS.active_connections))
        self.completed_value.SetLabel(str(PROXY_STATS.completed_connections))

    def _update_tray_tooltip(self):
        """Rebuild the tray icon tooltip and image from current state."""
        if not self.tray_icon:
            return
        tooltip = (
            f"{config.APP_NAME}\n"
            f"Status: {PROXY_STATS.proxy_status}\n"
            f"Connections: {PROXY_STATS.active_connections} active, "
            f"{PROXY_STATS.total_connections} total\n"
            f"Local Accounts: {len(config.LOCAL_ACCOUNTS)}\n"
            f"SSO Accounts: {config.ACCOUNTS_CACHE_REAL_COUNT}"
        )
        self.tray_icon.update_icon(tooltip=tooltip)

    def show_user_connected_notification(self, alias, account, method):
        """Show a tray notification summarising the login."""
        if not self.tray_icon:
            return

        method_labels = {
            "sso": "SSO",
            "local": "Local Account",
            "proxy_only": "Proxy Only",
            "skip_sso": "SSO Skipped",
            "passthrough": "Passthrough",
        }
        label = method_labels.get(method, method)

        body = f"{alias} \u2192 {account} ({label})" if alias != account else f"{account} ({label})"

        self.tray_icon.ShowBalloon("Login Proxied", body)

    def on_close(self, event):
        """Handle window close event - minimize to tray if available, otherwise really close."""
        if self.tray_icon:
            self.Hide()
            self.tray_icon.ShowBalloon(
                "Minimized to Tray",
                "Still running in the background.",
            )
        else:
            self.close_application()

    def close_application(self):
        """Actually close the application"""
        update_scheduler.shutdown()

        if hasattr(self, "_log_handler"):
            logging.getLogger().removeHandler(self._log_handler)

        if self.tray_icon:
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
        name = self._sso_api_name_map[idx]
        url = self._sso_api_url_map[idx]
        if name != config.SSO_API_NAME:
            self._ws_error_shown = False
            new_token = config.set_sso_api(name, url)
            self.api_token_field.ChangeValue(new_token)
            if hasattr(self, "ws_status_text"):
                self.ws_status_text.SetLabel("Connecting...")
                self.ws_status_text.SetForegroundColour(COLOR_WARNING)
                self.ws_status_text.Refresh()
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
        config.set_api_token_for_backend(config.SSO_API_NAME, token)
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
        self._ws_error_shown = False
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
                icon = utils.retry_file_io(lambda: wx.Icon(path, wx.BITMAP_TYPE_ANY))
                self.SetIcon(icon)
            except Exception:
                logger.warning("Failed to load icon from %s", path, exc_info=True)

    def _on_char_fade_tick(self, event=None):
        """Re-render the characters list so activity colours and text fade over time."""
        if hasattr(self, "characters_list") and self.characters_list in self._list_filter_data:
            self._refresh_characters_list()

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
            self._ws_error_shown = False
            self.ws_status_text.SetLabel("Connected (Live)")
            self.ws_status_text.SetForegroundColour(COLOR_SUCCESS)
        elif ws_client.is_auth_failed():
            detail = ws_client.get_auth_failed_detail() or "Auth Failed"
            label = detail if len(detail) <= 60 else detail[:57] + "..."
            self.ws_status_text.SetLabel(label)
            self.ws_status_text.SetToolTip(detail)
            self.ws_status_text.SetForegroundColour(COLOR_ERROR)
            if not self._ws_error_shown:
                self._ws_error_shown = True
                wx.MessageBox(detail, "SSO Connection Error", wx.OK | wx.ICON_ERROR)
        elif config.USER_API_TOKEN:
            self.ws_status_text.SetLabel("Connecting...")
            self.ws_status_text.SetForegroundColour(COLOR_WARNING)
        else:
            self.ws_status_text.SetLabel("No API Token")
            self.ws_status_text.SetForegroundColour(COLOR_MUTED)
        self.ws_status_text.Refresh()

    # --- Log tab handlers ---

    def _on_log_level_changed(self, event):
        self._log_handler.refilter()

    def _on_log_clear(self, event):
        self._log_handler.clear_buffer()

    def _on_log_word_wrap(self, event):
        parent = self.log_text.GetParent()
        sizer = parent.GetSizer()

        old = self.log_text
        new = self._make_log_text_ctrl(parent, word_wrap=self.log_word_wrap_cb.GetValue())
        sizer.Replace(old, new)
        old.Destroy()

        self.log_text = new
        self._log_handler._text_ctrl = new
        self._log_handler.refilter()
        sizer.Layout()

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
        real_accounts = config.ACCOUNTS_CACHE_REAL_COUNT

        if real_accounts == 0:
            self.accounts_cached_text.SetLabel("None")
            self.accounts_cached_text.SetForegroundColour(COLOR_MUTED)
        else:
            total_characters = sum(len(data.get("characters", {})) for data in config.ACCOUNTS_CACHED.values())
            total_aliases = sum(len(data.get("aliases", [])) for data in config.ACCOUNTS_CACHED.values())
            unique_tags = len({tag for data in config.ACCOUNTS_CACHED.values() for tag in data.get("tags", [])})
            self.accounts_cached_text.SetLabel(
                f"{real_accounts} accounts, {total_characters} characters, {total_aliases + unique_tags} aliases/tags"
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

        self._refresh_characters_list()
        self._update_tray_tooltip()

    def _refresh_characters_list(self):
        """Rebuild and render the characters list from cached account data."""
        all_characters = []
        for account, data in config.ACCOUNTS_CACHED.items():
            last_login = data.get("last_login")
            last_login_by = data.get("last_login_by") or ""
            active_character = data.get("active_character") or ""
            characters = data.get("characters", {})
            for character in sorted(characters):
                bind_text = zone_translate.zonekey_to_zone(characters[character]["bind"])
                park_text = zone_translate.zonekey_to_zone(characters[character]["park"])
                class_text = _characters_tab_class_display(characters[character]["class"])
                level = characters[character].get("level")
                level_text = str(level) if level is not None else ""
                keys_raw = characters[character].get("keys") or {}
                st_mark = _characters_tab_key_cell(keys_raw.get("st"))
                vp_mark = _characters_tab_key_cell(keys_raw.get("vp"))
                seb_mark = _characters_tab_key_cell(keys_raw.get("seb"))
                is_blocked = bool(active_character) and character != active_character
                all_characters.append(
                    (
                        character,
                        class_text,
                        level_text,
                        st_mark,
                        vp_mark,
                        seb_mark,
                        park_text,
                        bind_text,
                        account,
                        last_login_by,
                        last_login,
                        is_blocked,
                    )
                )

        char_rows = [
            (
                char,
                klass,
                lvl,
                st,
                vp,
                sb,
                park or "Unknown",
                bind or "Unknown",
                login_by if _activity_colour(ll) is not None else "",
                acct,
                ll,
                is_li,
            )
            for char, klass, lvl, st, vp, sb, park, bind, acct, login_by, ll, is_li in all_characters
        ]

        sort_col = self._characters_sort_col
        sort_asc = self._characters_sort_asc
        if sort_col in _KEY_COLUMNS:
            char_rows.sort(key=lambda x: (_KEY_SORT_ORDER.get(x[sort_col], 2), x[0]), reverse=not sort_asc)
        else:
            char_rows.sort(key=lambda x: ((x[sort_col] or ""), x[0]), reverse=not sort_asc)
        self._populate_list(
            self.characters_list,
            char_rows,
            row_color_fn=lambda row: _activity_colour(row[10], COLOR_ACTIVE_BLUE if row[11] else COLOR_ACTIVE_AMBER),
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

        self._update_tray_tooltip()


def start_ui():
    """Initialize and start the UI"""
    main_window = ProxyUI()
    main_window.Show()
    main_window.Bind(wx.EVT_CLOSE, main_window.on_close)
    return main_window
