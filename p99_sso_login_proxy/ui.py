import ctypes
import datetime
import logging
import os
import platform
import threading
from collections import deque
from heapq import merge as _heapmerge

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QCloseEvent, QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from p99_sso_login_proxy import (
    config,
    eq_config,
    log_handler,
    update_scheduler,
    updater,
    utils,
    ws_client,
    zone_translate,
)
from p99_sso_login_proxy.ui_classes import local_account_dialog, proxy_stats, taskbar_icon

logger = logging.getLogger("ui")

# Set in start_ui() after QApplication exists (required for QObject-based ProxyStats).
PROXY_STATS: proxy_stats.ProxyStats | None = None

COLOR_SUCCESS = QColor(0, 128, 0)
COLOR_ERROR = QColor(255, 0, 0)
COLOR_DARK_RED = QColor(128, 0, 0)
COLOR_WARNING = QColor(255, 130, 0)
COLOR_MUTED = QColor(128, 128, 128)
COLOR_VALUE_TEXT = QColor(44, 62, 80)
COLOR_ALT_ROW = QColor(240, 245, 250)
COLOR_ACTIVE_AMBER = QColor(255, 195, 120)
COLOR_ACTIVE_BLUE = QColor(130, 170, 255)

KEY_COLUMN_YES = "\u2713"
KEY_COLUMN_NO = "\u2717"

_KEY_COLUMNS = frozenset({3, 4, 5})
_KEY_SORT_ORDER = {KEY_COLUMN_YES: 0, KEY_COLUMN_NO: 1, "": 2}
_KEY_FILTER_TERMS = {"stkey": 3, "vpkey": 4, "sebkey": 5}
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


_CHARACTERS_TAB_CLASS_SHORT = {
    "Necromancer": "Necro",
    "ShadowKnight": "SK",
}


def _characters_tab_class_display(klass: str | None) -> str:
    if not klass:
        return ""
    return _CHARACTERS_TAB_CLASS_SHORT.get(klass, klass)


_LOG_LEVEL_COLORS = {
    logging.DEBUG: QColor(128, 128, 128),
    logging.INFO: QColor(0, 0, 0),
    logging.WARNING: QColor(200, 120, 0),
    logging.ERROR: QColor(220, 0, 0),
    logging.CRITICAL: QColor(160, 0, 0),
}

_LOG_LEVEL_NAMES = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

WM_POWERBROADCAST = 0x0218
PBT_APMRESUMEAUTOMATIC = 0x12


class _LogEmitBridge(QObject):
    """Marshals logging.Handler.emit from arbitrary threads to the GUI thread."""

    record_received = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)


class QtLogHandler(logging.Handler):
    """Logging handler with per-level ring buffers and colored QTextEdit output."""

    MAX_PER_LEVEL = 5_000
    MAX_DISPLAY_CHARS = 500_000
    _LEVELS = (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL)

    def __init__(
        self,
        text_edit: QTextEdit,
        auto_scroll_cb: QCheckBox,
        level_choice: QComboBox,
        bridge: _LogEmitBridge,
    ):
        super().__init__(level=logging.DEBUG)
        self._text_edit = text_edit
        self._auto_scroll_cb = auto_scroll_cb
        self._level_choice = level_choice
        self._bridge = bridge
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
        self._bridge.record_received.connect(self._on_record)

    @property
    def _display_level(self) -> int:
        name = self._level_choice.currentText()
        return getattr(logging, name, logging.INFO)

    def _bucket(self, levelno: int) -> int:
        for lvl in reversed(self._LEVELS):
            if levelno >= lvl:
                return lvl
        return self._LEVELS[0]

    def emit(self, record):
        try:
            msg = self.format(record)
            self._bridge.record_received.emit(msg, record.levelno)
        except Exception:
            self.handleError(record)

    @Slot(str, int)
    def _on_record(self, msg: str, levelno: int):
        self._seq += 1
        self._buffers[self._bucket(levelno)].append((self._seq, msg, levelno))
        if levelno >= self._display_level:
            self._write_line(msg, levelno)

    def _write_line(self, msg: str, levelno: int):
        ctrl = self._text_edit
        auto = self._auto_scroll_cb.isChecked()
        colour = _LOG_LEVEL_COLORS.get(levelno, QColor(0, 0, 0))

        cursor = ctrl.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(colour)
        cursor.setCharFormat(fmt)
        cursor.insertText(msg + "\n")

        if auto:
            sb = ctrl.verticalScrollBar()
            sb.setValue(sb.maximum())
        ctrl.ensureCursorVisible()

    def refilter(self):
        """Re-render the display by merging per-level buffers chronologically."""
        ctrl = self._text_edit
        display_level = self._display_level
        merged = _heapmerge(*(buf for lvl, buf in self._buffers.items() if lvl >= display_level))

        ctrl.clear()
        for _seq, msg, levelno in merged:
            colour = _LOG_LEVEL_COLORS.get(levelno, QColor(0, 0, 0))
            cursor = ctrl.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            fmt = QTextCharFormat()
            fmt.setForeground(colour)
            cursor.setCharFormat(fmt)
            cursor.insertText(msg + "\n")

        auto = self._auto_scroll_cb.isChecked()
        if auto:
            sb = ctrl.verticalScrollBar()
            sb.setValue(sb.maximum())
        else:
            ctrl.moveCursor(QTextCursor.MoveOperation.Start)

    def clear_buffer(self):
        for buf in self._buffers.values():
            buf.clear()
        self._seq = 0
        self._text_edit.clear()


def _activity_colour(last_login_iso: str | None, base_color: QColor = COLOR_ACTIVE_AMBER) -> QColor | None:
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
    pal = QApplication.palette()
    bg = pal.color(pal.ColorRole.Base)
    t = elapsed / config.ACTIVITY_FADE_SECONDS
    r = int(base_color.red() + (bg.red() - base_color.red()) * t)
    g = int(base_color.green() + (bg.green() - base_color.green()) * t)
    b = int(base_color.blue() + (bg.blue() - base_color.blue()) * t)
    return QColor(r, g, b)


def warning(message: str):
    QMessageBox.warning(None, "Warning", message)


def error(message: str):
    QMessageBox.critical(None, "Error", message)


class ProxyUI(QMainWindow):
    """Main UI window for the proxy application."""

    power_resume_requested = Signal()

    def __init__(self, parent=None, title: str | None = None):
        title = title or f"{config.APP_NAME} v{config.APP_VERSION}"
        size = (708, 550) if platform.system() == "Windows" else (760, 664)
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*size)
        self.setMinimumSize(708, 550)

        self.exit_event = threading.Event()
        self._list_filter_data: dict = {}
        self._ws_error_shown = False
        self.start_eq_func = None

        assert PROXY_STATS is not None
        PROXY_STATS.stats_updated.connect(self.on_stats_updated)
        PROXY_STATS.user_connected.connect(self.on_user_connected)
        PROXY_STATS.login_auth_rejected.connect(self.on_auth_error)

        self.init_ui()

        self._log_emit_bridge = _LogEmitBridge(self)
        self._log_handler = QtLogHandler(
            self.log_text,
            self.log_auto_scroll_cb,
            self.log_level_choice,
            self._log_emit_bridge,
        )
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(self._log_handler)

        self.tray_icon = taskbar_icon.create_tray_icon(self)

        self.uptime_timer = QTimer(self)
        self.uptime_timer.timeout.connect(self.update_stats)
        self.uptime_timer.start(1000)

        self.ws_status_timer = QTimer(self)
        self.ws_status_timer.timeout.connect(self._on_ws_status_tick)
        self.ws_status_timer.start(5000)

        self._ws_reconnect_timer = QTimer(self)
        self._ws_reconnect_timer.setSingleShot(True)
        self._ws_reconnect_timer.timeout.connect(lambda: ws_client.request_reconnect())

        self._char_fade_timer = QTimer(self)
        self._char_fade_timer.timeout.connect(self._on_char_fade_tick)
        self._char_fade_timer.start(10000)

        update_scheduler.start()

        self.set_icon()

        if config.PROXY_ENABLED and eq_config.find_eq_directory():
            eq_config.enable_proxy()

        eq_config.ensure_eqclient_log_enabled()

        QTimer.singleShot(0, self.update_eq_status)

        ws_sig = ws_client.get_ws_signals()
        if ws_sig:
            ws_sig.cache_updated.connect(self.update_account_cache_display)
            ws_sig.cache_updated.connect(self._on_ws_status_tick)
            ws_sig.rustle_ui_warning.connect(self._on_rustle_ui_warning)

    def nativeEvent(self, eventType, message):
        if platform.system() == "Windows" and eventType == b"windows_generic_MSG":
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_POWERBROADCAST and msg.wParam == PBT_APMRESUMEAUTOMATIC:
                    self.power_resume_requested.emit()
            except Exception:
                logger.debug("nativeEvent power parse failed", exc_info=True)
        return super().nativeEvent(eventType, message)

    @Slot(str)
    def _on_rustle_ui_warning(self, msg: str):
        QMessageBox.warning(self, "Rustle UI Detected", msg)

    def _add_label_value_row(self, parent, layout: QVBoxLayout, label_text: str, initial_value=""):
        row = QHBoxLayout()
        label = QLabel(label_text)
        f = label.font()
        f.setBold(True)
        label.setFont(f)
        value = QLabel(initial_value)
        value.setStyleSheet(f"color: {COLOR_VALUE_TEXT.name()};")
        row.addWidget(label)
        row.addWidget(value, 1)
        layout.addLayout(row)
        return value

    def _populate_list(self, table: QTableWidget, rows, row_color_fn=None):
        if table in self._list_filter_data:
            self._list_filter_data[table]["rows"] = rows
            self._list_filter_data[table]["row_color_fn"] = row_color_fn
            self._apply_filter(table)
        else:
            self._render_list(table, rows, row_color_fn)

    def _render_list(self, table: QTableWidget, rows, row_color_fn=None):
        first_visible = table.rowAt(0)
        table.setRowCount(0)
        num_cols = table.columnCount()
        for i, row in enumerate(rows):
            table.insertRow(i)
            for col in range(min(num_cols, len(row))):
                text = "" if row[col] is None else str(row[col])
                item = QTableWidgetItem(text)
                table.setItem(i, col, item)
            colour = row_color_fn(row) if row_color_fn else None
            if colour:
                for col in range(num_cols):
                    it = table.item(i, col)
                    if it:
                        it.setBackground(QBrush(colour))
            elif i % 2 == 1:
                for col in range(num_cols):
                    it = table.item(i, col)
                    if it:
                        it.setBackground(QBrush(COLOR_ALT_ROW))
        if rows and first_visible >= 0:
            target = min(first_visible, len(rows) - 1)
            table.scrollToItem(table.item(target, 0))

    def _apply_filter(self, table: QTableWidget):
        data = self._list_filter_data[table]
        num_cols = table.columnCount()
        row_color_fn = data.get("row_color_fn")
        term_match_fn = data.get("term_match_fn")
        skip_cols = data.get("filter_skip_columns") or frozenset()
        terms = data["search"].text().lower().split()
        if not terms:
            self._render_list(table, data["rows"], row_color_fn)
        else:

            def matches(row, t):
                if term_match_fn and t in _KEY_FILTER_TERMS:
                    return term_match_fn(row, t)
                if any(t in str(row[i]).lower() for i in range(num_cols) if i not in skip_cols and i < len(row)):
                    return True
                return term_match_fn(row, t) if term_match_fn else False

            filtered = [row for row in data["rows"] if all(matches(row, t) for t in terms)]
            self._render_list(table, filtered, row_color_fn)

    def _add_search_ctrl(self, parent, layout: QVBoxLayout, table: QTableWidget):
        search = QLineEdit(parent)
        search.setPlaceholderText("Type to filter...")
        search.setClearButtonEnabled(True)
        layout.addWidget(search)
        self._list_filter_data[table] = {"rows": [], "search": search}
        search.textChanged.connect(lambda _t: self._apply_filter(table))
        return search

    def _create_table(self, parent, columns: list[tuple[str, int]]) -> QTableWidget:
        table = QTableWidget(parent)
        table.setColumnCount(len(columns))
        for i, (name, width) in enumerate(columns):
            table.setHorizontalHeaderItem(i, QTableWidgetItem(name))
            table.setColumnWidth(i, width)
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(False)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        return table

    def _create_proxy_tab(self, notebook: QTabWidget):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        status_box = QGroupBox("Status")
        status_layout = QVBoxLayout(status_box)
        assert PROXY_STATS is not None
        self.address_value = self._add_label_value_row(
            tab, status_layout, "Listening on:", f"{PROXY_STATS.listening_address}:{PROXY_STATS.listening_port}"
        )
        self.proxy_status_text = self._add_label_value_row(tab, status_layout, "EQ Config:", "Checking...")
        self.last_username_label = self._add_label_value_row(tab, status_layout, "Last Username:", "")
        self.uptime_value = self._add_label_value_row(tab, status_layout, "Uptime:", PROXY_STATS.get_uptime())

        stats_box = QGroupBox("Statistics")
        stats_layout = QVBoxLayout(stats_box)
        self.total_value = self._add_label_value_row(
            tab, stats_layout, "Total Connections:", str(PROXY_STATS.total_connections)
        )
        self.active_value = self._add_label_value_row(
            tab, stats_layout, "Active Connections:", str(PROXY_STATS.active_connections)
        )
        self.completed_value = self._add_label_value_row(
            tab, stats_layout, "Completed Connections:", str(PROXY_STATS.completed_connections)
        )

        top_row = QHBoxLayout()
        top_row.addWidget(status_box, 1)
        top_row.addWidget(stats_box, 1)
        layout.addLayout(top_row)

        action_box = QGroupBox("Settings")
        action_layout = QVBoxLayout(action_box)

        controls_row = QHBoxLayout()
        mode_row = QHBoxLayout()
        mode_label = QLabel("Proxy Mode:")
        mode_label.setFont(QFont(mode_label.font().family(), weight=QFont.Weight.Bold))
        self.proxy_mode_choice = QComboBox()
        self.proxy_mode_choice.addItems(["Enabled (SSO)", "Enabled (Proxy Only)", "Disabled"])

        using_proxy, _ = eq_config.is_using_proxy()
        if not using_proxy:
            self.proxy_mode_choice.setCurrentIndex(2)
        elif config.PROXY_ONLY:
            self.proxy_mode_choice.setCurrentIndex(1)
        else:
            self.proxy_mode_choice.setCurrentIndex(0)

        self.proxy_mode_choice.currentIndexChanged.connect(self.on_proxy_mode_changed)
        self.proxy_mode_choice.setToolTip(
            "Enabled (SSO): Full proxy with SSO authentication\n"
            "Enabled (Proxy Only): Proxy active but no SSO interaction ('middlemand' mode)\n"
            "Disabled: Proxy inactive, direct connection to server"
        )
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.proxy_mode_choice)
        mode_row.addStretch()
        controls_row.addLayout(mode_row)

        self.always_on_top_cb = QCheckBox("Always On Top")
        self.always_on_top_cb.setChecked(config.ALWAYS_ON_TOP)
        if config.ALWAYS_ON_TOP:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.always_on_top_cb.toggled.connect(self.on_always_on_top)
        self.always_on_top_cb.setToolTip("Keep the application window on top of other windows")
        controls_row.addWidget(self.always_on_top_cb)
        action_layout.addLayout(controls_row)

        token_row = QHBoxLayout()
        token_label = QLabel("API Token:")
        token_label.setFont(QFont(token_label.font().family(), weight=QFont.Weight.Bold))
        self.api_token_field = QLineEdit()
        self.api_token_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_token_field.setText(config.USER_API_TOKEN)
        self.api_token_field.setToolTip(
            "API Token for auto-authentication. When this is set, the password entered in the EQ UI will be ignored."
        )
        token_row.addWidget(token_label)
        token_row.addWidget(self.api_token_field, 1)
        self.api_token_field.textChanged.connect(self.on_api_token_changed)
        action_layout.addLayout(token_row)

        sso_row = QHBoxLayout()
        sso_label = QLabel("SSO API:")
        sso_label.setFont(QFont(sso_label.font().family(), weight=QFont.Weight.Bold))
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

        self.sso_api_choice = QComboBox()
        self.sso_api_choice.addItems(choices)
        self.sso_api_choice.setCurrentIndex(selection)
        self.sso_api_choice.currentIndexChanged.connect(self.on_sso_api_changed)
        self.sso_api_choice.setToolTip("Select the SSO API server endpoint")
        sso_row.addWidget(sso_label)
        sso_row.addWidget(self.sso_api_choice, 1)
        action_layout.addLayout(sso_row)

        layout.addWidget(action_box)

        account_cache_box = QGroupBox("Account Data")
        account_cache_layout = QVBoxLayout(account_cache_box)
        cache_controls = QHBoxLayout()
        cache_info = QVBoxLayout()
        self.ws_status_text = self._add_label_value_row(tab, cache_info, "SSO Service:", "Connecting...")
        self.ws_status_text.setToolTip("WebSocket connection status for real-time account updates")

        self.accounts_cached_text = self._add_label_value_row(tab, cache_info, "Accounts:", "0")
        self.accounts_cached_text.setToolTip("Number of accounts, characters, and aliases/tags")

        cache_controls.addLayout(cache_info, 1)
        self.refresh_cache_btn = QPushButton("Force Reconnect")
        self.refresh_cache_btn.clicked.connect(self.on_refresh_account_cache)
        self.refresh_cache_btn.setToolTip("Disconnect and reconnect to the SSO server for fresh data")
        cache_controls.addWidget(self.refresh_cache_btn)
        account_cache_layout.addLayout(cache_controls)
        layout.addWidget(account_cache_box)

        notebook.addTab(tab, "Proxy")
        return tab

    def _create_sso_tab(self, notebook: QTabWidget):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        sso_notebook = QTabWidget()

        accounts_tab = QWidget()
        accounts_layout = QVBoxLayout(accounts_tab)
        self.accounts_list = self._create_table(accounts_tab, [("Account Name", 114), ("Aliases", 250), ("Tags", 250)])
        self._add_search_ctrl(accounts_tab, accounts_layout, self.accounts_list)
        accounts_layout.addWidget(self.accounts_list, 1)

        aliases_tab = QWidget()
        aliases_layout = QVBoxLayout(aliases_tab)
        self.aliases_list = self._create_table(aliases_tab, [("Alias", 100), ("Account Name", 114)])
        self._add_search_ctrl(aliases_tab, aliases_layout, self.aliases_list)
        aliases_layout.addWidget(self.aliases_list, 1)

        tags_tab = QWidget()
        tags_layout = QVBoxLayout(tags_tab)
        self.tags_list = self._create_table(tags_tab, [("Tag", 100), ("Account Names", 514)])
        self._add_search_ctrl(tags_tab, tags_layout, self.tags_list)
        tags_layout.addWidget(self.tags_list, 1)

        characters_tab = QWidget()
        characters_layout = QVBoxLayout(characters_tab)
        self.characters_list = self._create_table(
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
        self._characters_sort_col = 1
        self._characters_sort_asc = True
        self.characters_list.horizontalHeader().sectionClicked.connect(self.on_characters_list_col_click)

        search_row = QHBoxLayout()
        search_ctrl = QLineEdit(characters_tab)
        search_ctrl.setPlaceholderText("Type to filter...")
        search_ctrl.setClearButtonEnabled(True)
        self._list_filter_data[self.characters_list] = {"rows": [], "search": search_ctrl}
        search_ctrl.textChanged.connect(lambda _t: self._apply_filter(self.characters_list))
        search_row.addWidget(search_ctrl, 1)

        for colour, label in ((COLOR_ACTIVE_AMBER, "Logged In"), (COLOR_ACTIVE_BLUE, "Blocked")):
            sw = QFrame()
            sw.setFixedSize(12, 12)
            sw.setStyleSheet(f"background-color: {colour.name()};")
            search_row.addWidget(sw)
            search_row.addWidget(QLabel(label))

        characters_layout.addLayout(search_row)
        self._list_filter_data[self.characters_list]["term_match_fn"] = _characters_key_term_match
        self._list_filter_data[self.characters_list]["filter_skip_columns"] = _CHARACTERS_FILTER_SKIP_COLS

        characters_layout.addWidget(self.characters_list, 1)

        local_tab = QWidget()
        local_layout = QVBoxLayout(local_tab)
        self.local_accounts_list = self._create_table(local_tab, [("Account Name", 114), ("Aliases", 500)])
        self._add_search_ctrl(local_tab, local_layout, self.local_accounts_list)
        local_layout.addWidget(self.local_accounts_list, 1)

        btn_row = QHBoxLayout()
        self.add_local_account_btn = QPushButton("Add Account")
        self.add_local_account_btn.clicked.connect(self.on_add_local_account)
        self.edit_local_account_btn = QPushButton("Edit Account")
        self.edit_local_account_btn.clicked.connect(self.on_edit_local_account)
        self.delete_local_account_btn = QPushButton("Delete Account")
        self.delete_local_account_btn.clicked.connect(self.on_delete_local_account)
        btn_row.addWidget(self.add_local_account_btn)
        btn_row.addWidget(self.edit_local_account_btn)
        btn_row.addWidget(self.delete_local_account_btn)
        local_layout.addLayout(btn_row)

        sso_notebook.addTab(characters_tab, "Characters")
        sso_notebook.addTab(accounts_tab, "Accounts")
        sso_notebook.addTab(aliases_tab, "Aliases")
        sso_notebook.addTab(tags_tab, "Tags")
        sso_notebook.addTab(local_tab, "Local Accounts")

        layout.addWidget(sso_notebook, 1)
        self.refresh_accounts_btn = QPushButton("Force Reconnect")
        self.refresh_accounts_btn.clicked.connect(self.on_refresh_account_cache)
        self.refresh_accounts_btn.setToolTip("Disconnect and reconnect to the SSO server for fresh data")
        layout.addWidget(self.refresh_accounts_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        notebook.addTab(tab, "SSO")
        return tab

    def _create_eq_tab(self, notebook: QTabWidget):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        eq_box = QGroupBox("EverQuest Configuration")
        eq_layout = QVBoxLayout(eq_box)

        eq_dir_row = QHBoxLayout()
        eq_dir_label = QLabel("EverQuest Path:")
        eq_dir_label.setFont(QFont(eq_dir_label.font().family(), weight=QFont.Weight.Bold))
        self.eq_dir_text = QLabel("Checking...")
        self.eq_dir_text.setStyleSheet(f"color: {COLOR_VALUE_TEXT.name()};")
        self.browse_eq_btn = QPushButton("Browse\u2026")
        self.browse_eq_btn.setFixedWidth(70)
        self.browse_eq_btn.clicked.connect(self.on_browse_eq_directory)
        self.browse_eq_btn.setToolTip("Select the EverQuest installation directory")
        eq_dir_row.addWidget(eq_dir_label)
        eq_dir_row.addWidget(self.eq_dir_text, 1)
        eq_dir_row.addWidget(self.browse_eq_btn)
        eq_layout.addLayout(eq_dir_row)

        self.eqhost_text = self._add_label_value_row(tab, eq_layout, "eqhost.txt Path:", "Checking...")

        eq_layout.addWidget(QLabel("eqhost.txt Content:"))
        self.eqhost_contents = QTextEdit()
        self.eqhost_contents.setMinimumHeight(120)
        eq_layout.addWidget(self.eqhost_contents, 1)

        btn_row = QHBoxLayout()
        self.save_eqhost_btn = QPushButton("Save")
        self.save_eqhost_btn.clicked.connect(self.on_save_eqhost)
        self.reset_eqhost_btn = QPushButton("Reset")
        self.reset_eqhost_btn.clicked.connect(self.on_reset_eqhost)
        btn_row.addWidget(self.save_eqhost_btn)
        btn_row.addWidget(self.reset_eqhost_btn)
        eq_layout.addLayout(btn_row)

        layout.addWidget(eq_box, 1)
        notebook.addTab(tab, "Advanced")
        return tab

    def _create_changelog_tab(self, notebook: QTabWidget):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        box = QGroupBox("Version History")
        box_layout = QVBoxLayout(box)
        self.changelog_html = QTextBrowser()
        box_layout.addWidget(self.changelog_html, 1)
        layout.addWidget(box, 1)
        notebook.addTab(tab, "Changelog")
        return tab

    def _make_log_text_edit(self, parent, word_wrap: bool) -> QTextEdit:
        te = QTextEdit(parent)
        te.setReadOnly(True)
        te.setFont(QFont("Consolas", 9))
        if not word_wrap:
            te.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        else:
            te.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        return te

    def _create_log_tab(self, notebook: QTabWidget):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QHBoxLayout()
        self.log_auto_scroll_cb = QCheckBox("Auto-scroll")
        self.log_auto_scroll_cb.setChecked(True)
        controls.addWidget(self.log_auto_scroll_cb)

        self.log_word_wrap_cb = QCheckBox("Word wrap")
        self.log_word_wrap_cb.setChecked(False)
        self.log_word_wrap_cb.toggled.connect(self._on_log_word_wrap)
        controls.addWidget(self.log_word_wrap_cb)

        controls.addWidget(QLabel("Level:"))
        self.log_level_choice = QComboBox()
        self.log_level_choice.addItems(_LOG_LEVEL_NAMES)
        self.log_level_choice.setCurrentText("INFO")
        self.log_level_choice.currentIndexChanged.connect(self._on_log_level_changed)
        controls.addWidget(self.log_level_choice)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._on_log_clear)
        controls.addWidget(clear_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.log_text = self._make_log_text_edit(tab, word_wrap=False)
        layout.addWidget(self.log_text, 1)
        notebook.addTab(tab, "Log")
        return tab

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(line)

        notebook = QTabWidget()
        self._create_proxy_tab(notebook)
        self._create_sso_tab(notebook)
        self._create_eq_tab(notebook)
        self._create_log_tab(notebook)
        self._create_changelog_tab(notebook)

        main_layout.addWidget(notebook, 1)

        btn_row = QHBoxLayout()
        self.launch_eq_btn = QPushButton("Launch EverQuest")
        self.launch_eq_btn.clicked.connect(self.on_launch_eq)
        btn_row.addWidget(self.launch_eq_btn)
        btn_row.addSpacing(60)
        self.exit_btn = QPushButton("Exit")
        self.exit_btn.clicked.connect(self.on_exit_button)
        btn_row.addWidget(self.exit_btn)
        main_layout.addLayout(btn_row)

        self._center_window()

    def _center_window(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = self.frameGeometry()
            geo.moveCenter(screen.availableGeometry().center())
            self.move(geo.topLeft())

    @Slot()
    def on_stats_updated(self):
        self.update_stats()
        self._update_tray_tooltip()

    @Slot(str, str, str)
    def on_user_connected(self, alias: str, account: str, method: str):
        if alias != account:
            self.last_username_label.setText(f"{alias} \u2192 {account}")
        else:
            self.last_username_label.setText(account)
        self.show_user_connected_notification(alias, account, method)

    @Slot(str, str)
    def on_auth_error(self, username: str, detail: str):
        msg = detail or "Authentication rejected by server"
        QMessageBox.warning(self, "SSO Login Rejected", msg)

    def update_stats(self, event=None):
        assert PROXY_STATS is not None
        self.address_value.setText(f"{PROXY_STATS.listening_address}:{PROXY_STATS.listening_port}")
        self.uptime_value.setText(PROXY_STATS.get_uptime())
        self.total_value.setText(str(PROXY_STATS.total_connections))
        self.active_value.setText(str(PROXY_STATS.active_connections))
        self.completed_value.setText(str(PROXY_STATS.completed_connections))

    def _update_tray_tooltip(self):
        if not self.tray_icon:
            return
        assert PROXY_STATS is not None
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

    def closeEvent(self, event: QCloseEvent):
        if self.tray_icon:
            event.ignore()
            self.hide()
            self.tray_icon.ShowBalloon("Minimized to Tray", "Still running in the background.")
        else:
            self.close_application()

    def close_application(self):
        update_scheduler.shutdown()
        if hasattr(self, "_log_handler"):
            logging.getLogger().removeHandler(self._log_handler)
        if self.tray_icon:
            self.tray_icon.Destroy()
        using_proxy, _ = eq_config.is_using_proxy()
        if using_proxy:
            eq_config.disable_proxy()
        self.exit_event.set()
        self.close()

    def on_launch_eq(self):
        eq_dir = eq_config.find_eq_directory()
        if not eq_dir:
            QMessageBox.critical(self, "Error", "EverQuest directory not found.")
            return
        eqgame_path = os.path.join(eq_dir, "eqgame.exe")
        try:
            if os.path.exists(eqgame_path) and self.start_eq_func:
                self.start_eq_func(eq_dir)
            else:
                QMessageBox.critical(self, "Error", f"EverQuest executable not found in {eq_dir}")
        except Exception as e:
            logger.exception("Failed to launch EverQuest")
            QMessageBox.critical(self, "Error", f"Failed to launch EverQuest: {e!s}")

    def on_proxy_mode_changed(self, _index=None):
        selection = self.proxy_mode_choice.currentIndex()
        using_proxy, _ = eq_config.is_using_proxy()

        if selection == 0:
            if not using_proxy:
                success, err = eq_config.enable_proxy()
                if not success:
                    QMessageBox.critical(
                        self,
                        "Error",
                        err or "Failed to enable proxy. EverQuest directory or eqhost.txt not found.",
                    )
                    self.proxy_mode_choice.setCurrentIndex(2)
                    return
            if config.PROXY_ONLY:
                config.set_proxy_only(False)
            if not config.PROXY_ENABLED:
                config.set_proxy_enabled(True)

        elif selection == 1:
            if not using_proxy:
                success, err = eq_config.enable_proxy()
                if not success:
                    QMessageBox.critical(
                        self,
                        "Error",
                        err or "Failed to enable proxy. EverQuest directory or eqhost.txt not found.",
                    )
                    self.proxy_mode_choice.setCurrentIndex(2)
                    return
            if not config.PROXY_ONLY:
                config.set_proxy_only(True)
            if not config.PROXY_ENABLED:
                config.set_proxy_enabled(True)

        elif selection == 2:
            if using_proxy:
                success, err = eq_config.disable_proxy()
                if not success:
                    QMessageBox.critical(
                        self,
                        "Error",
                        err or "Failed to disable proxy. EverQuest directory or eqhost.txt not found.",
                    )
                    self.proxy_mode_choice.setCurrentIndex(0 if not config.PROXY_ONLY else 1)
                    return
            if config.PROXY_ONLY:
                config.set_proxy_only(False)
            if config.PROXY_ENABLED:
                config.set_proxy_enabled(False)

        self.update_eq_status()

    def on_updated_changelog(self):
        self.changelog_html.setHtml(config.CHANGELOG)
        self.changelog_html.setStyleSheet("background-color: #f9f9f9;")

    def on_sso_api_changed(self, _index=None):
        idx = self.sso_api_choice.currentIndex()
        name = self._sso_api_name_map[idx]
        url = self._sso_api_url_map[idx]
        if name != config.SSO_API_NAME:
            self._ws_error_shown = False
            new_token = config.set_sso_api(name, url)
            self.api_token_field.setText(new_token)
            if hasattr(self, "ws_status_text"):
                self.ws_status_text.setText("Connecting...")
                self.ws_status_text.setStyleSheet(f"color: {COLOR_WARNING.name()};")
            ws_client.request_reconnect()

    def on_browse_eq_directory(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select EverQuest Directory", config.EQ_DIRECTORY or "")
        if chosen:
            if not eq_config.is_valid_eq_directory(chosen):
                QMessageBox.warning(
                    self,
                    "Invalid Directory",
                    f"eqgame.exe was not found in:\n{chosen}\n\nPlease select a directory containing eqgame.exe.",
                )
            else:
                config.set_eq_directory(chosen)
                eq_config.clear_cache()
                self.update_eq_status()

    def on_save_eqhost(self):
        eq_dir = eq_config.find_eq_directory()
        if not eq_dir:
            logger.error("EverQuest directory not found when trying to save eqhost.txt")
            return
        eqhost_path = os.path.join(eq_dir, "eqhost.txt")
        content = self.eqhost_contents.toPlainText()
        try:
            with open(eqhost_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("Successfully wrote to eqhost.txt at %s", eqhost_path)
            self.update_eq_status()
        except OSError:
            logger.exception("Failed to save eqhost.txt")

    def on_reset_eqhost(self):
        self.update_eq_status()

    def on_always_on_top(self, checked: bool):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()
        config.set_always_on_top(checked)

    def on_api_token_changed(self, _text=None):
        token = self.api_token_field.text()
        config.set_api_token_for_backend(config.SSO_API_NAME, token)
        self._schedule_ws_reconnect()

    def on_refresh_account_cache(self):
        self._ws_error_shown = False
        config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNT_NAME_MAP = utils.load_local_accounts(config.LOCAL_ACCOUNTS_FILE)
        ws_client.request_reconnect()
        if hasattr(self, "ws_status_text"):
            self.ws_status_text.setText("Connecting...")
            self.ws_status_text.setStyleSheet(f"color: {COLOR_WARNING.name()};")
        self.update_account_cache_display()

    def on_exit_button(self):
        self.close_application()

    def set_icon(self):
        path = utils.find_resource_path("tray_icon.png")
        if path:
            try:
                from PySide6.QtGui import QIcon

                self.setWindowIcon(QIcon(path))
            except Exception:
                logger.warning("Failed to load icon from %s", path, exc_info=True)

    def _on_char_fade_tick(self):
        if hasattr(self, "characters_list") and self.characters_list in self._list_filter_data:
            self._refresh_characters_list()

    def _schedule_ws_reconnect(self, delay_ms=1500):
        self._ws_reconnect_timer.stop()
        self._ws_reconnect_timer.start(delay_ms)

    def _on_ws_status_tick(self):
        if not hasattr(self, "ws_status_text"):
            return
        if ws_client.is_connected():
            self._ws_error_shown = False
            self.ws_status_text.setText("Connected (Live)")
            self.ws_status_text.setStyleSheet(f"color: {COLOR_SUCCESS.name()};")
        elif ws_client.is_auth_failed():
            detail = ws_client.get_auth_failed_detail() or "Auth Failed"
            label = detail if len(detail) <= 60 else detail[:57] + "..."
            self.ws_status_text.setText(label)
            self.ws_status_text.setToolTip(detail)
            self.ws_status_text.setStyleSheet(f"color: {COLOR_ERROR.name()};")
            if not self._ws_error_shown:
                self._ws_error_shown = True
                QMessageBox.critical(self, "SSO Connection Error", detail)
        elif config.USER_API_TOKEN:
            self.ws_status_text.setText("Connecting...")
            self.ws_status_text.setStyleSheet(f"color: {COLOR_WARNING.name()};")
        else:
            self.ws_status_text.setText("No API Token")
            self.ws_status_text.setStyleSheet(f"color: {COLOR_MUTED.name()};")

    def _on_log_level_changed(self, _i=None):
        self._log_handler.refilter()

    def _on_log_clear(self):
        self._log_handler.clear_buffer()

    def _on_log_word_wrap(self, checked: bool):
        parent = self.log_text.parent()
        layout = parent.layout()
        idx = layout.indexOf(self.log_text)
        layout.removeWidget(self.log_text)
        self.log_text.deleteLater()
        self.log_text = self._make_log_text_edit(parent, word_wrap=checked)
        layout.insertWidget(idx, self.log_text, 1)
        self._log_handler._text_edit = self.log_text
        self._log_handler.refilter()

    def on_add_local_account(self):
        dialog = local_account_dialog.LocalAccountDialog(self, title="Add Local Account")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        account_name = dialog.account_name.text().strip()
        password = dialog.password.text().strip()
        aliases_text = dialog.aliases.text().strip()

        if not account_name:
            QMessageBox.critical(self, "Error", "Account name cannot be empty.")
            return
        if not password:
            QMessageBox.critical(self, "Error", "Password cannot be empty.")
            return
        if account_name in config.LOCAL_ACCOUNTS:
            QMessageBox.critical(self, "Error", f"Account '{account_name}' already exists.")
            return

        aliases = [alias.strip() for alias in aliases_text.split(",") if alias.strip()]
        config.LOCAL_ACCOUNTS[account_name] = {"password": password, "aliases": aliases}
        config.LOCAL_ACCOUNT_NAME_MAP[account_name] = account_name
        for alias in aliases:
            config.LOCAL_ACCOUNT_NAME_MAP[alias] = account_name

        if not utils.save_local_accounts(config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNTS_FILE):
            QMessageBox.critical(self, "Error", "Failed to save local accounts.")
        self.update_account_cache_display()

    def on_edit_local_account(self):
        selected_index = self.local_accounts_list.currentRow()
        if selected_index < 0:
            QMessageBox.critical(self, "Error", "Please select an account to edit.")
            return
        account_name = self.local_accounts_list.item(selected_index, 0).text()
        if account_name not in config.LOCAL_ACCOUNTS:
            QMessageBox.critical(self, "Error", f"Account '{account_name}' not found.")
            return

        account_data = config.LOCAL_ACCOUNTS[account_name]
        dialog = local_account_dialog.LocalAccountDialog(
            self,
            title="Edit Local Account",
            account_name=account_name,
            password=account_data.get("password", ""),
            aliases=", ".join(account_data.get("aliases", [])),
        )
        dialog.account_name.setEnabled(False)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        password = dialog.password.text().strip()
        aliases_text = dialog.aliases.text().strip()

        if not password:
            QMessageBox.critical(self, "Error", "Password cannot be empty.")
            return

        aliases = [alias.strip() for alias in aliases_text.split(",") if alias.strip()]

        for alias in account_data.get("aliases", []):
            if alias in config.LOCAL_ACCOUNT_NAME_MAP:
                del config.LOCAL_ACCOUNT_NAME_MAP[alias]

        config.LOCAL_ACCOUNTS[account_name] = {"password": password, "aliases": aliases}
        for alias in aliases:
            config.LOCAL_ACCOUNT_NAME_MAP[alias] = account_name

        if not utils.save_local_accounts(config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNTS_FILE):
            QMessageBox.critical(self, "Error", "Failed to save local accounts.")
        self.update_account_cache_display()

    def on_delete_local_account(self):
        selected_index = self.local_accounts_list.currentRow()
        if selected_index < 0:
            QMessageBox.critical(self, "Error", "Please select an account to delete.")
            return
        account_name = self.local_accounts_list.item(selected_index, 0).text()
        if account_name not in config.LOCAL_ACCOUNTS:
            QMessageBox.critical(self, "Error", f"Account '{account_name}' not found.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete the account '{account_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        account_data = config.LOCAL_ACCOUNTS[account_name]
        for alias in account_data.get("aliases", []):
            if alias in config.LOCAL_ACCOUNT_NAME_MAP:
                del config.LOCAL_ACCOUNT_NAME_MAP[alias]

        if account_name in config.LOCAL_ACCOUNT_NAME_MAP:
            del config.LOCAL_ACCOUNT_NAME_MAP[account_name]

        del config.LOCAL_ACCOUNTS[account_name]

        if not utils.save_local_accounts(config.LOCAL_ACCOUNTS, config.LOCAL_ACCOUNTS_FILE):
            QMessageBox.critical(self, "Error", "Failed to save local accounts.")
        self.update_account_cache_display()

    def on_characters_list_col_click(self, logical_index: int):
        if self._characters_sort_col == logical_index:
            self._characters_sort_asc = not self._characters_sort_asc
        else:
            self._characters_sort_col = logical_index
            self._characters_sort_asc = True
        self.update_account_cache_display()

    def update_account_cache_display(self):
        real_accounts = config.ACCOUNTS_CACHE_REAL_COUNT

        if real_accounts == 0:
            self.accounts_cached_text.setText("None")
            self.accounts_cached_text.setStyleSheet(f"color: {COLOR_MUTED.name()};")
        else:
            total_characters = sum(len(data.get("characters", {})) for data in config.ACCOUNTS_CACHED.values())
            total_aliases = sum(len(data.get("aliases", [])) for data in config.ACCOUNTS_CACHED.values())
            unique_tags = len({tag for data in config.ACCOUNTS_CACHED.values() for tag in data.get("tags", [])})
            self.accounts_cached_text.setText(
                f"{real_accounts} accounts, {total_characters} characters, {total_aliases + unique_tags} aliases/tags"
            )
            self.accounts_cached_text.setStyleSheet(f"color: {COLOR_SUCCESS.name()};")

        local_rows = []
        for account, data in sorted(config.LOCAL_ACCOUNTS.items()):
            aliases = data.get("aliases", [])
            local_rows.append((account, ", ".join(sorted(aliases)) if aliases else ""))
        self._populate_list(self.local_accounts_list, local_rows)

        account_rows = []
        for account, data in sorted(config.ACCOUNTS_CACHED.items()):
            aliases = ", ".join(sorted(data.get("aliases", [])))
            tags = ", ".join(sorted(data.get("tags", [])))
            account_rows.append((account, aliases, tags))
        self._populate_list(self.accounts_list, account_rows)

        all_aliases = []
        for account, data in config.ACCOUNTS_CACHED.items():
            for alias in sorted(data.get("aliases", [])):
                all_aliases.append((alias, account))
        all_aliases.sort()
        self._populate_list(self.aliases_list, all_aliases)

        tag_to_accounts = {}
        for account, data in config.ACCOUNTS_CACHED.items():
            for tag in sorted(data.get("tags", [])):
                tag_to_accounts.setdefault(tag, []).append(account)
        tag_rows = [(tag, ", ".join(sorted(accounts))) for tag, accounts in sorted(tag_to_accounts.items())]
        self._populate_list(self.tags_list, tag_rows)

        self._refresh_characters_list()
        self._update_tray_tooltip()

    def _refresh_characters_list(self):
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
                        last_login_by,
                        account,
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
            for char, klass, lvl, st, vp, sb, park, bind, login_by, acct, ll, is_li in all_characters
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
        status = eq_config.get_eq_status()

        self.update_account_cache_display()

        if status["eq_directory_found"]:
            self.eq_dir_text.setText(f"{status['eq_directory']}")
            self.eq_dir_text.setStyleSheet(f"color: {COLOR_SUCCESS.name()};")
            log_handler.set_log_watch_directory(status["eq_directory"], self)
        else:
            self.eq_dir_text.setText("Not Found")
            self.eq_dir_text.setStyleSheet(f"color: {COLOR_ERROR.name()};")

        if status["eqhost_found"]:
            self.eqhost_text.setText(f"{status['eqhost_path']}")
            self.eqhost_text.setStyleSheet(f"color: {COLOR_SUCCESS.name()};")
        else:
            self.eqhost_text.setText("Not Found")
            self.eqhost_text.setStyleSheet(f"color: {COLOR_ERROR.name()};")

        if status["using_proxy"]:
            self.proxy_status_text.setText("Enabled")
            self.proxy_status_text.setStyleSheet(f"color: {COLOR_SUCCESS.name()};")
        else:
            self.proxy_status_text.setText("Disabled")
            self.proxy_status_text.setStyleSheet(f"color: {COLOR_DARK_RED.name()};")

        self.eqhost_contents.clear()
        if status["eqhost_contents"]:
            self.eqhost_contents.setPlainText("\n".join(status["eqhost_contents"]))

        self.proxy_mode_choice.blockSignals(True)
        try:
            if not status["using_proxy"]:
                self.proxy_mode_choice.setCurrentIndex(2)
            elif config.PROXY_ONLY:
                self.proxy_mode_choice.setCurrentIndex(1)
            else:
                self.proxy_mode_choice.setCurrentIndex(0)
        finally:
            self.proxy_mode_choice.blockSignals(False)

        self._update_tray_tooltip()


def start_ui():
    """Initialize and start the UI."""
    global PROXY_STATS
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication must be created before start_ui()")
    PROXY_STATS = proxy_stats.ProxyStats(parent=app)

    main_window = ProxyUI()
    main_window.show()

    updater.connect_updater_signals()

    return main_window
