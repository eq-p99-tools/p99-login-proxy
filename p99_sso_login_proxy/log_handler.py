import asyncio
import glob
import logging
import os
import threading
import time

import wx
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from p99_sso_login_proxy import config, inventory_parser, ws_client, zone_translate

logger = logging.getLogger("log_handler")

LOG_WATCH_DIRECTORY = None
LOG_HANDLER = None
LOG_OBSERVER = None
LOG_OBSERVER_THREAD = None

INVENTORY_OBSERVER = None
INVENTORY_OBSERVER_THREAD = None

_current_zone: dict[str, str] = {}  # character_name.lower() -> zonekey


def _run_async(coro):
    """Schedule a coroutine on the app's asyncio event loop (thread-safe)."""
    app = wx.GetApp()
    if app and hasattr(app, "loop") and app.loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, app.loop)
    else:
        coro.close()
        logger.warning("Async loop not available, coroutine was dropped")


def _character_from_log_path(path: str) -> str:
    """Extract the character name from an EQ log file path.

    Log filenames follow the pattern ``eqlog_CharName_server.txt``.
    We use only the basename so that underscores in parent directories
    (e.g. Wine's ``drive_c``) don't corrupt the result.
    """
    return os.path.basename(path).split("_")[1]


class LogFileHandler(FileSystemEventHandler):
    def __init__(self, get_latest_log_file, wx_app):
        super().__init__()
        self._wx_app = wx_app
        self.get_latest_log_file = get_latest_log_file
        self._position = 0
        self._first_event_logged = False
        self.latest_log_file = self.get_latest_log_file()
        if self.latest_log_file and config.USER_API_TOKEN:
            logger.info(
                "Tracking log file: %s (character: %s)",
                self.latest_log_file,
                _character_from_log_path(self.latest_log_file),
            )
            self._seek_to_latest_position()
            self.send_heartbeat()  # Send an initial heartbeat if we've got a logfile
        elif not self.latest_log_file:
            logger.warning("No eqlog_*.txt files found in watch directory")

        self._idle_skip_count = 0

        self.heartbeat_timer = wx.Timer(self._wx_app)
        self._wx_app.Bind(wx.EVT_TIMER, self.send_heartbeat, self.heartbeat_timer)
        self.heartbeat_timer.Start(20000)  # Heartbeat every 20 seconds

    def _seek_to_latest_position(self):
        """Seek to the end of the current log file, backing up to the last login marker."""
        try:
            with open(self.latest_log_file, "rb") as f:
                f.seek(0, os.SEEK_END)
                self._position = f.tell()
                # Try to handle login text
                f.seek(max(self._position - 1000, 0), os.SEEK_SET)
                for line in f:
                    if line.rstrip().endswith(b"] Welcome to EverQuest!"):
                        break
                self._position = min(f.tell(), self._position)
        except Exception:
            self._position = 0

    def send_heartbeat(self, event=None):
        if self.latest_log_file and config.USER_API_TOKEN:
            character_name = _character_from_log_path(self.latest_log_file)
            if character_name.lower() not in config.CHARACTERS_CACHED:
                return
            # Check the modified time of the logfile
            modified_time = os.path.getmtime(self.latest_log_file)
            # If not modified within the last 30s, don't send a heartbeat
            if time.time() - modified_time > 30:
                self._idle_skip_count += 1
                if self._idle_skip_count <= 5:
                    logger.debug("Not modified within the last 30s, not sending heartbeat for `%s`", character_name)
                    if self._idle_skip_count == 5:
                        logger.debug("Suppressing further idle heartbeat messages until next heartbeat")
                return
            self._idle_skip_count = 0
            _run_async(ws_client.send_heartbeat(character_name))

    def on_modified(self, event):
        if not config.USER_API_TOKEN:
            return
        if not self._first_event_logged:
            self._first_event_logged = True
            logger.info("First watchdog event received: %s (is_directory=%s)", event.src_path, event.is_directory)
        latest = self.get_latest_log_file()
        if latest != self.latest_log_file:
            logger.info(
                "Switched to log file: %s (character: %s)", latest, _character_from_log_path(latest) if latest else "?"
            )
            self.latest_log_file = latest
            self._seek_to_latest_position()
            self.send_heartbeat()
        if event.src_path == self.latest_log_file:
            with open(self.latest_log_file, errors="ignore") as f:
                f.seek(self._position)
                for line in f:
                    self.handle_log_line(line.rstrip())
                self._position = f.tell()

    def handle_log_line(self, line):
        character_name = _character_from_log_path(self.latest_log_file)
        if character_name.lower() not in config.CHARACTERS_CACHED:
            return
        if m := config.MATCH_ENTERED_ZONE.match(line):
            zone = m.group("zone")
            zonekey = zone_translate.zone_to_zonekey(zone)
            _current_zone[character_name.lower()] = zonekey
            logger.info("`%s` entered zone: %s (%s)", character_name, zone, zonekey)
            _run_async(ws_client.send_update_location(character_name, park_location=zonekey))
        elif config.MATCH_BIND_CONFIRM.match(line):
            zonekey = _current_zone.get(character_name.lower())
            if zonekey:
                logger.info("`%s` bound in zone: %s", character_name, zonekey)
                _run_async(ws_client.send_update_location(character_name, bind_location=zonekey))
            else:
                logger.warning("`%s` bind detected but current zone is unknown", character_name)
        elif m := config.MATCH_CHARINFO.match(line):
            zone = m.group("zone")
            zonekey = zone_translate.zone_to_zonekey(zone)
            logger.info("`%s` is bound in zone: %s (%s)", character_name, zone, zonekey)
            _run_async(ws_client.send_update_location(character_name, bind_location=zonekey))
        elif m := config.MATCH_WHO_ZONE.match(line):
            zone = m.group("zone")
            if zone != "EverQuest":
                zonekey = zone_translate.zone_to_zonekey(zone)
                _current_zone[character_name.lower()] = zonekey
                logger.info("`%s` zone from /who: %s (%s)", character_name, zone, zonekey)
                _run_async(ws_client.send_update_location(character_name, park_location=zonekey))
        elif m := config.MATCH_WHO_SELF.match(line):
            if m.group("name").lower() == character_name.lower():
                level = int(m.group("level"))
                logger.info("`%s` detected level %d from /who", character_name, level)
                _run_async(ws_client.send_update_location(character_name, level=level))
        elif m := config.MATCH_LEVEL_UP.match(line):
            level = int(m.group("level"))
            logger.info("`%s` leveled up to %d", character_name, level)
            _run_async(ws_client.send_update_location(character_name, level=level))


def _is_inventory_file_path(path: str) -> bool:
    return os.path.basename(path).lower().endswith("-inventory.txt")


class InventoryFileHandler(FileSystemEventHandler):
    """Watch EQ root for ``*-Inventory.txt`` writes and report zone keys to the SSO API."""

    def on_created(self, event):
        self._handle_event(event)

    def on_modified(self, event):
        self._handle_event(event)

    def _handle_event(self, event):
        if event.is_directory or not _is_inventory_file_path(event.src_path):
            return
        if not config.USER_API_TOKEN:
            return
        character_name = inventory_parser.character_name_from_inventory_path(event.src_path)
        if not character_name or character_name.lower() not in config.CHARACTERS_CACHED:
            return
        try:
            flags = inventory_parser.parse_inventory_file(event.src_path)
        except Exception:
            logger.exception("Failed to parse inventory file: %s", event.src_path)
            return
        keys = {
            "seb": flags["key_seb"],
            "vp": flags["key_vp"],
            "st": flags["key_st"],
        }
        logger.info(
            "Inventory update for `%s`: seb=%s vp=%s st=%s",
            character_name,
            keys["seb"],
            keys["vp"],
            keys["st"],
        )
        _run_async(ws_client.send_update_location(character_name, keys=keys))


def set_log_watch_directory(eq_directory, wx_app):
    global LOG_WATCH_DIRECTORY, LOG_HANDLER, LOG_OBSERVER, LOG_OBSERVER_THREAD
    global INVENTORY_OBSERVER, INVENTORY_OBSERVER_THREAD

    def find_logs_subdir(directory):
        try:
            entries = os.listdir(directory)
        except OSError:
            logger.warning("Cannot list EQ directory: %s", directory)
            return None
        for entry in entries:
            if entry.lower() == "logs" and os.path.isdir(os.path.join(directory, entry)):
                return os.path.join(directory, entry)
        return None

    log_directory = find_logs_subdir(eq_directory)
    if log_directory:
        LOG_WATCH_DIRECTORY = log_directory

        def get_latest_log_file():
            files = glob.glob(os.path.join(LOG_WATCH_DIRECTORY, "eqlog_*.txt"))
            return max(files, key=os.path.getmtime) if files else None

        if not LOG_OBSERVER:
            log_files = glob.glob(os.path.join(LOG_WATCH_DIRECTORY, "eqlog_*.txt"))
            logger.info("Starting log watcher on: %s (%d log files found)", LOG_WATCH_DIRECTORY, len(log_files))
            LOG_HANDLER = LogFileHandler(get_latest_log_file, wx_app)
            LOG_OBSERVER = Observer()
            LOG_OBSERVER.schedule(LOG_HANDLER, LOG_WATCH_DIRECTORY, recursive=False)
            LOG_OBSERVER_THREAD = threading.Thread(target=LOG_OBSERVER.start, daemon=True)
            LOG_OBSERVER_THREAD.start()
            logger.info("Watchdog observer started (backend: %s)", type(LOG_OBSERVER).__name__)
    else:
        logger.warning("No Logs subdirectory found in: %s", eq_directory)

    if not INVENTORY_OBSERVER:
        inv_handler = InventoryFileHandler()
        INVENTORY_OBSERVER = Observer()
        INVENTORY_OBSERVER.schedule(inv_handler, eq_directory, recursive=False)
        INVENTORY_OBSERVER_THREAD = threading.Thread(target=INVENTORY_OBSERVER.start, daemon=True)
        INVENTORY_OBSERVER_THREAD.start()
        logger.info("Inventory file watcher started on: %s", eq_directory)
