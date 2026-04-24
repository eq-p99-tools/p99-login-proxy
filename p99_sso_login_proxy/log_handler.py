import asyncio
import glob
import logging
import os
import threading
import time

from PySide6.QtWidgets import QWidget
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from p99_sso_login_proxy import (
    class_translate,
    config,
    inventory_parser,
    local_characters,
    ws_client,
    zone_translate,
)

logger = logging.getLogger("log_handler")

LOG_WATCH_DIRECTORY = None
LOG_HANDLER = None
LOG_OBSERVER = None
LOG_OBSERVER_THREAD = None

INVENTORY_OBSERVER = None
INVENTORY_OBSERVER_THREAD = None

_current_zone: dict[str, str] = {}  # character_name.lower() -> zonekey

# Set from cmd.QtAsyncApp to schedule coroutines from watchdog threads.
ASYNCIO_LOOP = None


def set_asyncio_loop(loop):
    """Bind the daemon asyncio loop used by _run_async (call after QApplication exists)."""
    global ASYNCIO_LOOP
    ASYNCIO_LOOP = loop


def _run_async(coro):
    """Schedule a coroutine on the app's asyncio event loop (thread-safe)."""
    loop = ASYNCIO_LOOP
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, loop)
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


def _any_character_tracked() -> bool:
    """Are log/inventory watchers useful at all (SSO token OR any local character)?"""
    return bool(config.USER_API_TOKEN) or bool(config.LOCAL_CHARACTER_NAMES)


def _classify_character(character_name: str) -> tuple[bool, bool]:
    """Return ``(is_sso_tracked, is_local_tracked)`` for the given log filename character."""
    key = character_name.lower()
    in_sso = bool(config.USER_API_TOKEN) and key in config.CHARACTERS_CACHED
    in_local = key in config.LOCAL_CHARACTER_NAMES
    return in_sso, in_local


class LogFileHandler(FileSystemEventHandler):
    def __init__(self, get_latest_log_file, timer_parent: QWidget):
        super().__init__()
        from PySide6.QtCore import QTimer

        self._heartbeat_timer = QTimer(timer_parent)
        self._heartbeat_timer.setInterval(20000)
        self._heartbeat_timer.timeout.connect(self.send_heartbeat)
        self.get_latest_log_file = get_latest_log_file
        self._position = 0
        self._first_event_logged = False
        self.latest_log_file = self.get_latest_log_file()
        if self.latest_log_file and _any_character_tracked():
            logger.info(
                "Tracking log file: %s (character: %s)",
                self.latest_log_file,
                _character_from_log_path(self.latest_log_file),
            )
            self._seek_to_latest_position()
            # send_heartbeat is a no-op without a USER_API_TOKEN, so calling it
            # unconditionally is safe even when only local characters are tracked.
            self.send_heartbeat()
        elif not self.latest_log_file:
            logger.warning("No eqlog_*.txt files found in watch directory")

        self._idle_skip_count = 0

        self._heartbeat_timer.start()

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
        if not _any_character_tracked():
            return
        if not self._first_event_logged:
            self._first_event_logged = True
            logger.info("First watchdog event received: %s (is_directory=%s)", event.src_path, event.is_directory)
        latest = self.get_latest_log_file()
        if latest != self.latest_log_file:
            character_name = _character_from_log_path(latest) if latest else "?"
            logger.info("Switched to log file: %s (character: %s)", latest, character_name)
            self.latest_log_file = latest
            self._seek_to_latest_position()
            self.send_heartbeat()
            if latest:
                local_characters.try_auto_create(character_name)
        if event.src_path == self.latest_log_file:
            with open(self.latest_log_file, errors="ignore") as f:
                f.seek(self._position)
                for line in f:
                    self.handle_log_line(line.rstrip())
                self._position = f.tell()

    def handle_log_line(self, line):
        character_name = _character_from_log_path(self.latest_log_file)
        in_sso, in_local = _classify_character(character_name)
        if not (in_sso or in_local):
            return

        def _broadcast_location(
            park_location: str | None = None,
            bind_location: str | None = None,
            level: int | None = None,
            items: dict | None = None,
        ) -> None:
            if in_sso:
                _run_async(
                    ws_client.send_update_location(
                        character_name,
                        park_location=park_location,
                        bind_location=bind_location,
                        level=level,
                        items=items,
                    )
                )
            if in_local:
                local_characters.apply_update(
                    character_name,
                    park=park_location,
                    bind=bind_location,
                    level=level,
                    items=items,
                )

        if m := config.MATCH_ENTERED_ZONE.match(line):
            zone = m.group("zone")
            zonekey = zone_translate.zone_to_zonekey(zone)
            _current_zone[character_name.lower()] = zonekey
            logger.info("`%s` entered zone: %s (%s)", character_name, zone, zonekey)
            _broadcast_location(park_location=zonekey)
        elif config.MATCH_BIND_CONFIRM.match(line):
            zonekey = _current_zone.get(character_name.lower())
            if zonekey:
                logger.info("`%s` bound in zone: %s", character_name, zonekey)
                _broadcast_location(bind_location=zonekey)
            else:
                logger.warning("`%s` bind detected but current zone is unknown", character_name)
        elif m := config.MATCH_CHARINFO.match(line):
            zone = m.group("zone")
            zonekey = zone_translate.zone_to_zonekey(zone)
            logger.info("`%s` is bound in zone: %s (%s)", character_name, zone, zonekey)
            _broadcast_location(bind_location=zonekey)
        elif m := config.MATCH_WHO_ZONE.match(line):
            zone = m.group("zone")
            if zone != "EverQuest":
                zonekey = zone_translate.zone_to_zonekey(zone)
                _current_zone[character_name.lower()] = zonekey
                logger.info("`%s` zone from /who: %s (%s)", character_name, zone, zonekey)
                _broadcast_location(park_location=zonekey)
        elif m := config.MATCH_WHO_SELF.match(line):
            if m.group("name").lower() == character_name.lower():
                level = int(m.group("level"))
                raw_klass = m.group("klass")
                resolved_klass = class_translate.resolve_class(raw_klass)
                if resolved_klass:
                    logger.info(
                        "`%s` detected level %d (%s -> %s) from /who",
                        character_name,
                        level,
                        raw_klass,
                        resolved_klass,
                    )
                else:
                    logger.info(
                        "`%s` detected level %d from /who (unrecognized class/title %r)",
                        character_name,
                        level,
                        raw_klass,
                    )
                _broadcast_location(level=level)
                # Class is only persisted for local characters; SSO class is
                # authoritative on the server side and we must not overwrite it.
                if in_local and resolved_klass:
                    local_characters.apply_update(character_name, klass=resolved_klass)
        elif m := config.MATCH_LEVEL_UP.match(line):
            level = int(m.group("level"))
            logger.info("`%s` leveled up to %d", character_name, level)
            _broadcast_location(level=level)
        elif config.MATCH_VELIUM_VAPORS_GLOW.match(line):
            logger.info("`%s` Vial of Velium Vapors used (log line)", character_name)
            _broadcast_location(items={"thurg": False})
        elif in_sso and (m := config.MATCH_FTE.match(line)):
            mob = m.group("mob")
            player = m.group("player")
            logger.info("FTE detected: `%s` engages `%s` (seen by `%s`)", mob, player, character_name)
            _run_async(ws_client.send_fte(mob, player, character_name, m.group("time")))
        elif in_sso and (m := config.MATCH_YOU_SLAIN.match(line)):
            mob = m.group("mob")
            if mob.lower() in config.RAID_TARGETS:
                logger.info("Raid target slain: `%s` (by `%s`)", mob, character_name)
                _run_async(ws_client.send_mob_death(mob, m.group("time"), character_name))
        elif in_sso and (m := config.MATCH_MOB_SLAIN.match(line)):
            mob = m.group("mob")
            if mob.lower() in config.RAID_TARGETS:
                logger.info(
                    "Raid target slain: `%s` by `%s` (seen by `%s`)",
                    mob,
                    m.group("slayer"),
                    character_name,
                )
                _run_async(ws_client.send_mob_death(mob, m.group("time"), character_name))


def _is_inventory_file_path(path: str) -> bool:
    return os.path.basename(path).lower().endswith("-inventory.txt")


class InventoryFileHandler(FileSystemEventHandler):
    """Watch EQ root for ``*-Inventory.txt`` writes and report ``items`` flags to the SSO API."""

    def on_created(self, event):
        self._handle_event(event)

    def on_modified(self, event):
        self._handle_event(event)

    def _handle_event(self, event):
        if event.is_directory or not _is_inventory_file_path(event.src_path):
            return
        if not _any_character_tracked():
            return
        character_name = inventory_parser.character_name_from_inventory_path(event.src_path)
        if not character_name:
            return
        in_sso, in_local = _classify_character(character_name)
        if not (in_sso or in_local):
            return
        try:
            flags = inventory_parser.parse_inventory_file(event.src_path)
        except Exception:
            logger.exception("Failed to parse inventory file: %s", event.src_path)
            return
        items = {k: flags[k] for k in inventory_parser.ALL_INVENTORY_WIRE_KEYS}
        logger.info(
            "Inventory update for `%s`: %s",
            character_name,
            " ".join(f"{k}={items[k]}" for k in inventory_parser.ALL_INVENTORY_WIRE_KEYS),
        )
        if in_sso:
            _run_async(ws_client.send_update_location(character_name, items=items))
        if in_local:
            local_characters.apply_update(character_name, items=items)


def _deduped_eq_roots(primary: str) -> list[tuple[str, str]]:
    """Return ``(path, label)`` for primary and optional secondary EQ install roots (``label`` is primary/secondary)."""
    roots: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(path: str, label: str) -> None:
        if not path or not os.path.isdir(path):
            return
        root_key = os.path.normcase(os.path.realpath(path))
        if root_key in seen:
            return
        seen.add(root_key)
        roots.append((path, label))

    add(primary, "primary")
    if config.EQ_SECONDARY_DIRECTORY:
        add(config.EQ_SECONDARY_DIRECTORY, "secondary")
    return roots


def _make_get_latest_log_file(log_dir: str):
    def get_latest_log_file():
        files = glob.glob(os.path.join(log_dir, "eqlog_*.txt"))
        return max(files, key=os.path.getmtime) if files else None

    return get_latest_log_file


def set_log_watch_directory(eq_directory, timer_parent: QWidget):
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

    eq_roots = _deduped_eq_roots(eq_directory)

    log_dirs: list[tuple[str, str]] = []
    seen_log_realpaths: set[str] = set()
    for root_path, root_label in eq_roots:
        log_directory = find_logs_subdir(root_path)
        if not log_directory:
            logger.warning("No Logs subdirectory found in: %s (%s)", root_path, root_label)
            continue
        log_key = os.path.normcase(os.path.realpath(log_directory))
        if log_key in seen_log_realpaths:
            continue
        seen_log_realpaths.add(log_key)
        log_dirs.append((log_directory, root_label))

    if not LOG_OBSERVER and log_dirs:
        LOG_OBSERVER = Observer()
        for i, (log_directory, root_label) in enumerate(log_dirs):
            get_latest_log_file = _make_get_latest_log_file(log_directory)
            log_files = glob.glob(os.path.join(log_directory, "eqlog_*.txt"))
            logger.info(
                "Starting log watcher on: %s (%s EQ root, %d log files found)",
                log_directory,
                root_label,
                len(log_files),
            )
            handler = LogFileHandler(get_latest_log_file, timer_parent)
            if i == 0:
                LOG_WATCH_DIRECTORY = log_directory
                LOG_HANDLER = handler
            LOG_OBSERVER.schedule(handler, log_directory, recursive=False)
        LOG_OBSERVER_THREAD = threading.Thread(target=LOG_OBSERVER.start, daemon=True)
        LOG_OBSERVER_THREAD.start()
        logger.info("Watchdog observer started (backend: %s)", type(LOG_OBSERVER).__name__)

    if not INVENTORY_OBSERVER:
        inv_handler = InventoryFileHandler()
        INVENTORY_OBSERVER = Observer()
        for root_path, root_label in eq_roots:
            INVENTORY_OBSERVER.schedule(inv_handler, root_path, recursive=False)
            logger.info("Inventory file watcher scheduled on: %s (%s EQ root)", root_path, root_label)
        INVENTORY_OBSERVER_THREAD = threading.Thread(target=INVENTORY_OBSERVER.start, daemon=True)
        INVENTORY_OBSERVER_THREAD.start()
        logger.info("Inventory file watcher started (backend: %s)", type(INVENTORY_OBSERVER).__name__)
