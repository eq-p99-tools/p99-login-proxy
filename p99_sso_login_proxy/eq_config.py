"""
EverQuest Configuration Manager

This module handles finding the EverQuest installation directory and managing
the eqhost.txt file which controls which login server the game connects to.
"""

import configparser
import contextlib
import logging
import os
import platform
import re
import shutil
import stat
import string
import tempfile

from p99_sso_login_proxy import config

# Set up logging
logger = logging.getLogger("eq_config")

# Simple cache for paths and expensive computations
_cache = {
    "eq_directory": None,
    "eqhost_path": None,
    "eqclient_path": None,
    "rustle_present": None,
}

# Default EverQuest installation paths to check
DEFAULT_EQ_PATHS = [
    r"Program Files (x86)\EverQuest",
    r"Program Files\EverQuest",
    r"EverQuest",
    r"Games\EverQuest",
    r"Program Files (x86)\Sony\EverQuest",
    r"Program Files\Sony\EverQuest",
]

# Default login server address and proxy address
DEFAULT_LOGIN_SERVER = f"Host={config.EQEMU_LOGIN_HOST}:{config.EQEMU_PORT}"
DEFAULT_PROXY_ADDRESS = (
    f"Host={config.LISTEN_HOST if config.LISTEN_HOST != '0.0.0.0' else 'localhost'}:{config.LISTEN_PORT}"
)


def get_available_drives() -> list[str]:
    """
    Get a list of available drive letters on Windows.

    Returns:
        List[str]: List of drive letters (e.g. ['C:', 'D:'])
    """
    available_drives = []
    for drive in string.ascii_uppercase:
        drive_path = f"{drive}:\\"
        if os.path.exists(drive_path):
            available_drives.append(drive_path)
    return available_drives


def is_valid_eq_directory(path: str) -> bool:
    """
    Verify if a directory is a valid EverQuest installation.

    Args:
        path (str): Path to check

    Returns:
        bool: True if valid EverQuest directory, False otherwise
    """
    if not os.path.exists(path) or not os.path.isdir(path):
        return False

    # On case-sensitive filesystems (Linux), do a case-insensitive scan
    if platform.system() != "Windows":
        try:
            for entry in os.listdir(path):
                if entry.lower() == "eqgame.exe":
                    logger.info(f"Found {entry} in {path}")
                    return True
        except OSError:
            pass
        return False

    if os.path.exists(os.path.join(path, "eqgame.exe")):
        logger.info(f"Found eqgame.exe in {path}")
        return True

    return False


def _find_wine_eq_directories() -> list[str]:
    """Return candidate EQ directories inside Wine/Proton prefixes on Linux."""
    candidates = []
    home = os.path.expanduser("~")

    wine_prefixes = [
        os.path.join(home, ".wine"),
        os.environ.get("WINEPREFIX", ""),
    ]

    # Lutris Wine prefixes
    lutris_dir = os.path.join(home, "Games")
    if os.path.isdir(lutris_dir):
        try:
            for entry in os.scandir(lutris_dir):
                if entry.is_dir():
                    wine_prefixes.append(entry.path)
        except OSError:
            pass

    for prefix in wine_prefixes:
        if not prefix or not os.path.isdir(prefix):
            continue
        drive_c = os.path.join(prefix, "drive_c")
        if not os.path.isdir(drive_c):
            continue
        for eq_subpath in DEFAULT_EQ_PATHS:
            candidates.append(os.path.join(drive_c, eq_subpath))

    return candidates


def find_eq_directory() -> str | None:
    """
    Find the EverQuest installation directory using multiple methods.
    Checks the explicit config override first, then falls back to auto-detection.

    Returns:
        Optional[str]: Path to EverQuest directory if found, None otherwise
    """
    # Check cache first
    if _cache.get("eq_directory"):
        logger.debug(f"Using cached EverQuest directory: {_cache['eq_directory']}")
        return _cache["eq_directory"]

    # Check explicit config override
    if config.EQ_DIRECTORY and is_valid_eq_directory(config.EQ_DIRECTORY):
        logger.info(f"Using configured EverQuest directory: {config.EQ_DIRECTORY}")
        _cache["eq_directory"] = config.EQ_DIRECTORY
        return config.EQ_DIRECTORY

    # First check the current directory:
    current_dir = os.getcwd()
    if is_valid_eq_directory(current_dir):
        logger.info(f"Found EverQuest in the current directory: {current_dir}")
        _cache["eq_directory"] = current_dir
        return current_dir

    # Check common installation paths (Windows drive letters)
    for path in DEFAULT_EQ_PATHS:
        for drive in get_available_drives():
            check_dir = os.path.join(drive, path)
            if os.path.exists(check_dir) and is_valid_eq_directory(check_dir):
                logger.info(f"Found EverQuest directory in a default path: {check_dir}")
                _cache["eq_directory"] = check_dir
                return check_dir

    # Check Wine/Proton prefixes on Linux
    if platform.system() != "Windows":
        for check_dir in _find_wine_eq_directories():
            if os.path.exists(check_dir) and is_valid_eq_directory(check_dir):
                logger.info(f"Found EverQuest directory in Wine prefix: {check_dir}")
                _cache["eq_directory"] = check_dir
                return check_dir

    # Not found
    logger.warning("EverQuest directory not found")
    _cache["eq_directory"] = None
    return None


def clear_cache():
    """Clear the cached directory and file paths so they are re-detected."""
    _cache["eq_directory"] = None
    _cache["eqhost_path"] = None
    _cache["eqclient_path"] = None
    _cache["rustle_present"] = None


def get_eqhost_path(eq_dir: str | None = None) -> str | None:
    """
    Get the path to the eqhost.txt file.

    Args:
        eq_dir (Optional[str]): EverQuest directory path. If None, will attempt to find it
                                and use the cache.

    Returns:
        Optional[str]: Path to eqhost.txt if found, None otherwise
    """
    # Only use cache when no explicit eq_dir is provided
    if not eq_dir:
        if _cache.get("eqhost_path"):
            # logger.debug(f"Using cached eqhost.txt path: {_cache['eqhost_path']}")
            return _cache["eqhost_path"]
        eq_dir = find_eq_directory()
        if not eq_dir:
            _cache["eqhost_path"] = None
            return None

    # Check for eqhost.txt in the EQ directory
    eqhost_path = os.path.join(eq_dir, "eqhost.txt")
    if os.path.exists(eqhost_path):
        logger.info(f"Found eqhost.txt at {eqhost_path}")
        _cache["eqhost_path"] = eqhost_path
        return eqhost_path

    # Not found
    _cache["eqhost_path"] = None
    return None


def get_eqclient_path(eq_dir: str | None = None) -> str | None:
    """
    Get the path to the eqclient.ini file.

    Args:
        eq_dir (Optional[str]): EverQuest directory path. If None, will attempt to find it
                                and use the cache.

    Returns:
        Optional[str]: Path to eqclient.ini if found, None otherwise
    """
    # Only use cache when no explicit eq_dir is provided
    if not eq_dir:
        if _cache.get("eqclient_path"):
            logger.debug(f"Using cached eqclient.ini path: {_cache['eqclient_path']}")
            return _cache["eqclient_path"]
        eq_dir = find_eq_directory()
        if not eq_dir:
            _cache["eqclient_path"] = None
            return None

    eqclient_path = os.path.join(eq_dir, "eqclient.ini")
    if os.path.exists(eqclient_path):
        _cache["eqclient_path"] = eqclient_path
        return eqclient_path

    _cache["eqclient_path"] = None
    return None


BACKUP_SUFFIX = ".bak"


def get_eqhost_backup_path(eqhost_path: str | None = None) -> str | None:
    """Return the path of the eqhost.txt backup file, or None if eqhost.txt is not found."""
    if not eqhost_path:
        eqhost_path = get_eqhost_path()
    if not eqhost_path:
        return None
    return eqhost_path + BACKUP_SUFFIX


def read_eqhost_file(eqhost_path: str | None = None) -> list[str]:
    """Read eqhost.txt and return its lines (stripped of trailing whitespace and BOM)."""
    if not eqhost_path:
        eqhost_path = get_eqhost_path()
        if not eqhost_path:
            return []
    if not os.path.exists(eqhost_path):
        return []
    try:
        with open(eqhost_path, encoding="utf-8-sig", errors="replace") as f:
            return [line.rstrip("\r\n").rstrip() for line in f]
    except OSError:
        logger.exception("Error reading eqhost.txt")
        return []


def read_eqhost_backup_file(eqhost_path: str | None = None) -> list[str]:
    """Read the eqhost.txt backup, or return [] if it does not exist."""
    backup_path = get_eqhost_backup_path(eqhost_path)
    if not backup_path or not os.path.exists(backup_path):
        return []
    try:
        with open(backup_path, encoding="utf-8-sig", errors="replace") as f:
            return [line.rstrip("\r\n").rstrip() for line in f]
    except OSError:
        logger.exception("Error reading eqhost.txt backup")
        return []


def _atomic_write_text(path: str, content: str) -> None:
    """Atomically write text to `path` via a temp file in the same directory.

    Uses os.replace, which is atomic on Windows for same-volume rename — so a
    crash mid-write either leaves the original file untouched or installs the
    new content fully. Always writes UTF-8 with LF line endings.
    """
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".eqhost-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            with contextlib.suppress(OSError):
                os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise


def _has_active_non_proxy_host(lines: list[str]) -> bool:
    """True if any line is an uncommented `Host=...` that is NOT the proxy address."""
    proxy = DEFAULT_PROXY_ADDRESS.lower()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lower = stripped.lower()
        if lower.startswith("host=") and lower != proxy:
            return True
    return False


def is_using_proxy(eq_dir: str | None = None) -> tuple[bool, str | None]:
    """True iff the only active `Host=` line in eqhost.txt is the proxy address."""
    eqhost_path = get_eqhost_path(eq_dir)
    if not eqhost_path:
        return False, None

    proxy = DEFAULT_PROXY_ADDRESS.lower()
    active_hosts: list[str] = []
    for line in read_eqhost_file(eqhost_path):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("host="):
            active_hosts.append(stripped.lower())

    using = len(active_hosts) == 1 and active_hosts[0] == proxy
    return using, eqhost_path


def _prepare_eqhost_for_write(eqhost_path: str) -> None:
    """Best-effort clear read-only flags on the EQ directory and eqhost.txt."""
    _try_clear_readonly(os.path.dirname(eqhost_path))
    if os.path.exists(eqhost_path):
        _try_clear_readonly(eqhost_path)


def enable_proxy() -> tuple[bool, str | None]:
    """Snapshot the current eqhost.txt to .bak (if no backup yet) and write a clean
    single-line proxy file. Idempotent — re-enabling does not corrupt the backup.
    """
    eqhost_path = get_eqhost_path()
    if not eqhost_path:
        return False, None

    backup_path = get_eqhost_backup_path(eqhost_path)
    assert backup_path is not None  # backup_path is None only when eqhost_path is None

    try:
        _prepare_eqhost_for_write(eqhost_path)

        if not os.path.exists(backup_path):
            current_lines = read_eqhost_file(eqhost_path) if os.path.exists(eqhost_path) else []
            if _has_active_non_proxy_host(current_lines):
                # Snapshot the user's content verbatim (re-emitted with UTF-8/LF).
                backup_content = "\n".join(current_lines) + ("\n" if current_lines else "")
            else:
                # File is empty / all-comments / already proxy-only — write a
                # synthetic default so disable_proxy has a clean restore target.
                backup_content = DEFAULT_LOGIN_SERVER + "\n"
            _atomic_write_text(backup_path, backup_content)
            logger.info("Backed up eqhost.txt to %s", backup_path)

        _atomic_write_text(eqhost_path, DEFAULT_PROXY_ADDRESS + "\n")
        logger.info("Wrote proxy eqhost.txt at %s", eqhost_path)
        return True, None
    except PermissionError as e:
        logger.exception("Permission denied writing eqhost.txt")
        return False, f"Failed to write eqhost.txt. Please turn off the read-only flag on:\n\n{e.filename or eqhost_path}"
    except OSError as e:
        logger.exception("Error writing eqhost.txt")
        return False, f"Failed to write eqhost.txt:\n\n{e!s}"


def disable_proxy() -> tuple[bool, str | None]:
    """Restore eqhost.txt from .bak if present, else write the eqemu default."""
    eqhost_path = get_eqhost_path()
    if not eqhost_path:
        return False, None

    backup_path = get_eqhost_backup_path(eqhost_path)
    assert backup_path is not None

    try:
        _prepare_eqhost_for_write(eqhost_path)

        if os.path.exists(backup_path):
            os.replace(backup_path, eqhost_path)
            logger.info("Restored eqhost.txt from %s", backup_path)
        else:
            _atomic_write_text(eqhost_path, DEFAULT_LOGIN_SERVER + "\n")
            logger.info("No backup found; wrote default login server to %s", eqhost_path)
        return True, None
    except PermissionError as e:
        logger.exception("Permission denied restoring eqhost.txt")
        return False, f"Failed to restore eqhost.txt. Please turn off the read-only flag on:\n\n{e.filename or eqhost_path}"
    except OSError as e:
        logger.exception("Error restoring eqhost.txt")
        return False, f"Failed to restore eqhost.txt:\n\n{e!s}"


def restore_backup() -> tuple[bool, str | None]:
    """Restore eqhost.txt from the .bak file. Errors when no backup exists."""
    eqhost_path = get_eqhost_path()
    if not eqhost_path:
        return False, "EverQuest directory not found."

    backup_path = get_eqhost_backup_path(eqhost_path)
    assert backup_path is not None
    if not os.path.exists(backup_path):
        return False, "No backup file found. The proxy has not been enabled yet."

    try:
        _prepare_eqhost_for_write(eqhost_path)
        os.replace(backup_path, eqhost_path)
        logger.info("Restored eqhost.txt from %s", backup_path)
        return True, None
    except PermissionError as e:
        logger.exception("Permission denied restoring eqhost.txt")
        return False, f"Failed to restore eqhost.txt. Please turn off the read-only flag on:\n\n{e.filename or eqhost_path}"
    except OSError as e:
        logger.exception("Error restoring eqhost.txt")
        return False, f"Failed to restore eqhost.txt:\n\n{e!s}"


def get_eq_status() -> dict:
    """
    Get the status of EverQuest configuration.

    Returns:
        dict: Dictionary with status information
    """
    # Use cached values for efficiency
    eq_dir = find_eq_directory()
    using_proxy, eqhost_path = is_using_proxy(eq_dir)

    status = {
        "eq_directory_found": eq_dir is not None,
        "eq_directory": eq_dir,
        "eqhost_found": eqhost_path is not None and os.path.exists(eqhost_path),
        "eqhost_path": eqhost_path,
        "using_proxy": using_proxy,
        "eqhost_contents": read_eqhost_file(eqhost_path) if eqhost_path else [],
    }

    return status


def read_eqclient_log_enabled() -> bool | None:
    """
    Read the Log= setting from eqclient.ini.

    Returns:
        True if Log=TRUE (case-insensitive), False if present but not true,
        None if the file or key cannot be found.
    """
    eqclient_path = get_eqclient_path()
    if not eqclient_path:
        return None
    try:
        parser = configparser.ConfigParser()
        parser.optionxform = str.lower
        parser.read(eqclient_path)
        # Section names are case-sensitive in configparser, so find [Defaults]
        # regardless of casing.
        section = next((s for s in parser.sections() if s.lower() == "defaults"), None)
        if section and parser.has_option(section, "log"):
            return parser.get(section, "log").strip().lower() == "true"
        return None
    except Exception:
        logger.exception("Error reading Log setting from eqclient.ini")
        return None


_RUSTLE_FINGERPRINTS = {
    "EQUI_Inventory.xml": [
        "iw_bag1_slot9",
        "iw_bag1_slot10",
        "iw_bag2_slot9",
        "iw_bag2_slot10",
        "iw_bag3_slot9",
        "iw_bag3_slot10",
        "iw_bag4_slot9",
        "iw_bag4_slot10",
        "iw_bag5_slot9",
        "iw_bag5_slot10",
        "iw_bag6_slot9",
        "iw_bag6_slot10",
        "iw_bag7_slot9",
        "iw_bag7_slot10",
        "iw_bag8_slot9",
        "iw_bag8_slot10",
    ],
}


def _check_dir_for_rustle(dir_path: str) -> bool:
    """Return True if any file in *dir_path* contains a Rustle fingerprint."""
    for filename, markers in _RUSTLE_FINGERPRINTS.items():
        filepath = os.path.join(dir_path, filename)
        if not os.path.isfile(filepath):
            continue
        try:
            with open(filepath, encoding="utf-8", errors="replace") as f:
                content = f.read().lower()
            if any(m in content for m in markers):
                return True
        except OSError:
            logger.debug("Could not read %s for Rustle detection", filepath)
    return False


def _deduped_eq_install_roots() -> list[str]:
    """Primary EQ dir plus optional ``eq_secondary_directory``, deduped by real path."""
    roots: list[str] = []
    seen: set[str] = set()

    def add(path: str | None) -> None:
        if not path or not os.path.isdir(path):
            return
        root_key = os.path.normcase(os.path.realpath(path))
        if root_key in seen:
            return
        seen.add(root_key)
        roots.append(path)

    add(find_eq_directory())
    if config.EQ_SECONDARY_DIRECTORY:
        add(config.EQ_SECONDARY_DIRECTORY)
    return roots


def detect_rustle_ui() -> bool:
    """Scan every subdirectory under ``<eq_root>/uifiles/`` for Rustle UI fingerprints.

    Checks the resolved primary EverQuest directory and, if set, ``eq_secondary_directory``
    in ``proxyconfig.ini`` (deduped). Works even when only the secondary path is valid.

    The result is cached in ``_cache["rustle_present"]`` so subsequent calls (and
    ``get_client_settings()``) are free.

    Returns True if Rustle markers are found in *any* subdirectory under any root.
    """
    roots = _deduped_eq_install_roots()
    if not roots:
        _cache["rustle_present"] = False
        return False

    for eq_root in roots:
        uifiles_dir = os.path.join(eq_root, "uifiles")
        if not os.path.isdir(uifiles_dir):
            continue
        try:
            for entry in os.scandir(uifiles_dir):
                if not entry.is_dir():
                    continue
                if _check_dir_for_rustle(entry.path):
                    logger.warning("Rustle UI detected in %s", entry.path)
                    _cache["rustle_present"] = True
                    return True
        except OSError:
            logger.exception("Error scanning uifiles directory under %s", eq_root)

    _cache["rustle_present"] = False
    return False


def get_client_settings() -> dict:
    """
    Return a dict of client settings to send to the SSO server.
    Returns an empty dict if the EQ directory is not found (no eqclient.ini).
    A missing Log= line is treated as False (logging not enabled).
    ``rustle_present`` is only included after ``detect_rustle_ui()`` has been
    called at least once (i.e. after the first WebSocket connection).
    """
    eqclient_path = get_eqclient_path()
    if not eqclient_path:
        return {}
    log_enabled = read_eqclient_log_enabled()
    settings: dict = {"log_enabled": bool(log_enabled)}
    if _cache["rustle_present"] is not None:
        settings["rustle_present"] = _cache["rustle_present"]
    return settings


def _try_clear_readonly(path: str) -> None:
    """Best-effort attempt to remove the read-only flag from a file or directory."""
    try:
        current = os.stat(path).st_mode
        if not current & stat.S_IWRITE:
            os.chmod(path, current | stat.S_IWRITE)
            logger.info(f"Cleared read-only flag from {path}")
    except OSError:
        logger.exception(f"Error clearing read-only flag from {path}")
        pass


def ensure_eqclient_log_enabled() -> bool:
    """
    Attempt to ensure Log=TRUE is set in eqclient.ini.

    Steps:
    1. Read the file contents and compute what the new content should be.
    2. If the content is already correct, return True without touching anything.
    3. Try to clear read-only on the EQ directory and the ini file itself
       (useful when running as admin).
    4. Back up the file to eqclient.ini.bak (also acts as a write-permission
       check — if the directory is still read-only this will fail and we bail out).
    5. Write the updated content.
    6. Silently swallow any IO/permission errors and return False on failure.

    Returns:
        True if logging is enabled after this call, False otherwise.
    """
    eqclient_path = get_eqclient_path()
    if not eqclient_path:
        return False

    try:
        with open(eqclient_path, encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Replace any existing Log= line (case-insensitive key, any value)
        new_content, count = re.subn(
            r"(?im)^(log\s*=\s*).*$",
            r"Log=TRUE",
            content,
        )

        if count == 0:
            # Key not present at all — insert after [Defaults] header if found,
            # otherwise just append at end of file.
            new_content, inserted = re.subn(
                r"(?im)^(\[defaults\][^\S\n]*)(\r?\n)",
                r"\1\2Log=TRUE\2",
                content,
                count=1,
            )
            if not inserted:
                new_content = content.rstrip("\n") + "\nLog=TRUE\n"

        if new_content == content:
            # Already correct — no changes needed, no backup required.
            return True

        _try_clear_readonly(os.path.dirname(eqclient_path))
        _try_clear_readonly(eqclient_path)

        backup_path = eqclient_path + ".bak"
        shutil.copyfile(eqclient_path, backup_path)
        logger.info("Backed up eqclient.ini to %s", backup_path)

        with open(eqclient_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        logger.info("Set Log=TRUE in eqclient.ini")
        return True
    except Exception:
        logger.debug("Could not set Log=TRUE in eqclient.ini (file may be read-only)")
        return False


if __name__ == "__main__":
    # Set up console logging for testing
    logging.basicConfig(level=logging.INFO)

    # Test the functions
    status = get_eq_status()
    logger.info("EverQuest Status:")
    for key, value in status.items():
        logger.info("  %s: %s", key, value)
