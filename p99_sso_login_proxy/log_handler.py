import asyncio
import glob
import logging
import os
import threading
import time

import wx
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from p99_sso_login_proxy import config, ws_client, zone_translate

logger = logging.getLogger("log_handler")

LOG_WATCH_DIRECTORY = None
LOG_HANDLER = None
LOG_OBSERVER = None
LOG_OBSERVER_THREAD = None

_current_zone: dict[str, str] = {}  # character_name.lower() -> zonekey


def _run_async(coro):
    """Schedule a coroutine on the app's asyncio event loop (thread-safe)."""
    app = wx.GetApp()
    if app and hasattr(app, "loop") and app.loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, app.loop)
    else:
        coro.close()
        logger.warning("Async loop not available, coroutine was dropped")


class LogFileHandler(FileSystemEventHandler):
    def __init__(self, get_latest_log_file, wx_app):
        super().__init__()
        self._wx_app = wx_app
        self.get_latest_log_file = get_latest_log_file
        self._position = 0
        self.latest_log_file = self.get_latest_log_file()
        if self.latest_log_file and config.USER_API_TOKEN:
            logger.info("New log file: %s", self.latest_log_file)
            self._seek_to_latest_position()
            self.send_heartbeat()  # Send an initial heartbeat if we've got a logfile

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
            character_name = self.latest_log_file.split("_")[1]
            if character_name.lower() not in config.CHARACTERS_CACHED:
                return
            # Check the modified time of the logfile
            modified_time = os.path.getmtime(self.latest_log_file)
            # If not modified within the last 30s, don't send a heartbeat
            if time.time() - modified_time > 30:
                logger.debug("Not modified within the last 30s, not sending heartbeat for `%s`", character_name)
                return
            _run_async(ws_client.send_heartbeat(character_name))

    def on_modified(self, event):
        if not config.USER_API_TOKEN:
            return
        latest = self.get_latest_log_file()
        if latest != self.latest_log_file:
            logger.info("New log file: %s", latest)
            self.latest_log_file = latest
            self._seek_to_latest_position()
        if event.src_path == self.latest_log_file:
            with open(self.latest_log_file, errors="ignore") as f:
                f.seek(self._position)
                for line in f:
                    self.handle_log_line(line.rstrip())
                self._position = f.tell()

    def handle_log_line(self, line):
        character_name = self.latest_log_file.split("_")[1]
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


def set_log_watch_directory(eq_directory, wx_app):
    global LOG_WATCH_DIRECTORY, LOG_HANDLER, LOG_OBSERVER, LOG_OBSERVER_THREAD

    def find_logs_subdir(directory):
        for entry in os.listdir(directory):
            if entry.lower() == "logs" and os.path.isdir(os.path.join(directory, entry)):
                return os.path.join(directory, entry)
        return None

    log_directory = find_logs_subdir(eq_directory)
    if not log_directory:
        logger.warning("No log directory found in: %s", eq_directory)
        return
    logger.info("Setting log watch directory to: %s", log_directory)
    LOG_WATCH_DIRECTORY = log_directory

    def get_latest_log_file():
        files = glob.glob(os.path.join(LOG_WATCH_DIRECTORY, "eqlog_*.txt"))
        return max(files, key=os.path.getmtime) if files else None

    if not LOG_OBSERVER:
        LOG_HANDLER = LogFileHandler(get_latest_log_file, wx_app)
        LOG_OBSERVER = Observer()
        LOG_OBSERVER.schedule(LOG_HANDLER, LOG_WATCH_DIRECTORY, recursive=False)
        LOG_OBSERVER_THREAD = threading.Thread(target=LOG_OBSERVER.start, daemon=True)
        LOG_OBSERVER_THREAD.start()
