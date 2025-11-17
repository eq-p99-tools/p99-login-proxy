import asyncio
import glob
import os
import threading
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
import wx

from p99_sso_login_proxy import config
from p99_sso_login_proxy import sso_api

LOG_WATCH_DIRECTORY = None
LOG_HANDLER = None
LOG_OBSERVER = None
LOG_OBSERVER_THREAD = None


class LogFileHandler(FileSystemEventHandler):
    def __init__(self, get_latest_log_file, wx_app):
        super().__init__()
        self._wx_app = wx_app
        self.get_latest_log_file = get_latest_log_file
        self._position = 0
        self.latest_log_file = self.get_latest_log_file()
        if self.latest_log_file:
            print(f"[LOG HANDLER] New log file: {self.latest_log_file}")
            try:
                with open(self.latest_log_file, 'rb') as f:
                    f.seek(0, os.SEEK_END)
                    self._position = f.tell()
            except Exception:
                self._position = 0

        self.heartbeat_timer = wx.Timer(self._wx_app)
        self._wx_app.Bind(wx.EVT_TIMER, self.send_heartbeat, self.heartbeat_timer)
        self.heartbeat_timer.Start(20000)  # Heartbeat every 20 seconds
        self.send_heartbeat()  # Send an initial heartbeat if we've got a logfile

    def send_heartbeat(self, event=None):
        if not config.USER_API_TOKEN:
            return
        if self.latest_log_file:
            character_name = self.latest_log_file.split("_")[1]
            if character_name.lower() not in config.CHARACTERS_CACHED:
                return
            # Check the modified time of the logfile
            modified_time = os.path.getmtime(self.latest_log_file)
            # If not modified within the last 30s, don't send a heartbeat
            if time.time() - modified_time > 30:
                print(f"[LOG HANDLER] Not modified within the last 30s, not sending heartbeat for `{character_name}`")
                return
            asyncio.run(sso_api.heartbeat(character_name))

    def on_modified(self, event):
        if not config.USER_API_TOKEN:
            return
        latest = self.get_latest_log_file()
        if latest != self.latest_log_file:
            print(f"[LOG HANDLER] New log file: {latest}")
            self.latest_log_file = latest
            try:
                with open(self.latest_log_file, 'rb') as f:
                    f.seek(0, os.SEEK_END)
                    self._position = f.tell()
            except Exception:
                self._position = 0
        if event.src_path == self.latest_log_file:
            with open(self.latest_log_file, 'r', errors='ignore') as f:
                f.seek(self._position)
                for line in f:
                    self.handle_log_line(line.rstrip())
                self._position = f.tell()

    def handle_log_line(self, line):
        character_name = self.latest_log_file.split("_")[1]
        if config.MATCH_ENTERED_ZONE.match(line):
            zone = config.MATCH_ENTERED_ZONE.match(line).group("zone")
            print(f"[LOG HANDLER] `{character_name}` entered zone: {zone}")
            asyncio.run(sso_api.update_location(character_name, bind_location=zone))
        elif config.MATCH_CHARINFO.match(line):
            zone = config.MATCH_CHARINFO.match(line).group("zone")
            print(f"[LOG HANDLER] `{character_name}` is in zone: {zone}")
            asyncio.run(sso_api.update_location(character_name, park_location=zone))


def set_log_watch_directory(eq_directory, wx_app):
    global LOG_WATCH_DIRECTORY, LOG_HANDLER, LOG_OBSERVER, LOG_OBSERVER_THREAD
    def find_logs_subdir(directory):
        for entry in os.listdir(directory):
            if entry.lower() == "logs" and os.path.isdir(os.path.join(directory, entry)):
                return os.path.join(directory, entry)
        return None
    log_directory = find_logs_subdir(eq_directory)
    if not log_directory:
        print("[LOG HANDLER] No log directory found in: " + eq_directory)
        return
    print("[LOG HANDLER] Setting log watch directory to: " + log_directory)
    LOG_WATCH_DIRECTORY = log_directory
    def get_latest_log_file():
        files = glob.glob(os.path.join(LOG_WATCH_DIRECTORY, 'eqlog_*.txt'))
        return max(files, key=os.path.getmtime) if files else None
    if not LOG_OBSERVER:
        LOG_HANDLER = LogFileHandler(get_latest_log_file, wx_app)
        LOG_OBSERVER = Observer()
        LOG_OBSERVER.schedule(LOG_HANDLER, LOG_WATCH_DIRECTORY, recursive=False)
        LOG_OBSERVER_THREAD = threading.Thread(target=LOG_OBSERVER.start, daemon=True)
        LOG_OBSERVER_THREAD.start()
