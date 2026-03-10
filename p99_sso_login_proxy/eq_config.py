"""
EverQuest Configuration Manager

This module handles finding the EverQuest installation directory and managing
the eqhost.txt file which controls which login server the game connects to.
"""

import configparser
import logging
import os
import re
import shutil
import stat
import string
from dataclasses import dataclass

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

    # Check for eqgame.exe
    if os.path.exists(os.path.join(path, "eqgame.exe")):
        logger.info(f"Found eqgame.exe in {path}")
        return True

    return False


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

    # Check common installation paths
    for path in DEFAULT_EQ_PATHS:
        for drive in get_available_drives():
            check_dir = os.path.join(drive, path)
            if os.path.exists(check_dir) and is_valid_eq_directory(check_dir):
                logger.info(f"Found EverQuest directory in a default path: {check_dir}")
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
            logger.debug(f"Using cached eqhost.txt path: {_cache['eqhost_path']}")
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


def read_eqhost_file(eqhost_path: str | None = None) -> list[str]:
    """
    Read the contents of the eqhost.txt file.

    Args:
        eqhost_path (Optional[str]): Path to eqhost.txt. If None, will attempt to find it.

    Returns:
        List[str]: Lines from the eqhost.txt file, or empty list if file not found
    """
    if not eqhost_path:
        eqhost_path = get_eqhost_path()
        if not eqhost_path:
            return []

    try:
        if os.path.exists(eqhost_path):
            with open(eqhost_path) as f:
                return [line.strip() for line in f.readlines()]
        else:
            logger.warning(f"eqhost.txt not found at {eqhost_path}")
            return []
    except Exception:
        logger.exception("Error reading eqhost.txt")
        return []


def write_eqhost_file(lines: list[str], eqhost_path: str | None = None) -> tuple[bool, str | None]:
    """
    Write contents to the eqhost.txt file.

    Args:
        lines (List[str]): Lines to write to the file
        eqhost_path (Optional[str]): Path to eqhost.txt. If None, will attempt to find it.

    Returns:
        Tuple[bool, Optional[str]]: (success, error_message)
    """
    if not eqhost_path:
        eqhost_path = get_eqhost_path()
        if not eqhost_path:
            return False, None

    try:
        ### Check if the eqhost file is read-only
        ### (this requires running as admin and sometimes doesn't work, so disabled for now)
        # if not os.access(eqhost_path, os.W_OK):
        #     # Make it writeable
        #     os.chmod(eqhost_path, 0o777)

        with open(eqhost_path, "w") as f:
            for line in lines:
                f.write(f"{line}\n")
        logger.info(f"Successfully wrote to eqhost.txt at {eqhost_path}")
        return True, None
    except PermissionError as e:
        logger.exception("Error writing to eqhost.txt. Please turn off the read-only flag on this file: %s", e.filename)
        return False, (
            f"Failed to write to eqhost.txt. Please turn off the read-only flag on this file:\n\n{e.filename}"
        )
    except Exception as e:
        logger.exception("Error writing to eqhost.txt")
        return False, f"Failed to write to eqhost.txt:\n\n{e!s}"


@dataclass
class EqHostEntry:
    """Represents a single line in the eqhost.txt file."""

    raw: str  # The line content (stripped of leading #)
    is_host: bool  # Whether this is a Host= line
    commented: bool  # Whether the line is commented out
    is_proxy: bool  # Whether it matches the proxy address


def _parse_eqhost_lines(lines: list[str]) -> list[EqHostEntry]:
    """Parse raw eqhost.txt lines into structured entries."""
    entries = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            entries.append(EqHostEntry(raw="", is_host=False, commented=False, is_proxy=False))
            continue

        is_commented = stripped.startswith("#")
        uncommented = stripped.lstrip("#").strip()
        is_host_line = uncommented.startswith("Host=")
        is_proxy_line = DEFAULT_PROXY_ADDRESS in stripped

        entries.append(
            EqHostEntry(
                raw=uncommented,
                is_host=is_host_line,
                commented=is_commented,
                is_proxy=is_proxy_line,
            )
        )
    return entries


def _serialize_eqhost_entries(entries: list[EqHostEntry]) -> list[str]:
    """Serialize structured entries back into eqhost.txt lines."""
    result = []
    for entry in entries:
        if not entry.is_host:
            result.append(entry.raw)
        elif entry.commented:
            result.append(f"#{entry.raw}")
        else:
            result.append(entry.raw)
    return result


def is_using_proxy(eq_dir: str | None = None) -> tuple[bool, str | None]:
    """
    Check if EverQuest is configured to use the proxy.

    Returns:
        Tuple[bool, Optional[str]]:
            - bool: True if using proxy, False otherwise
            - Optional[str]: Path to eqhost.txt if found, None otherwise
    """
    eqhost_path = get_eqhost_path(eq_dir)
    if not eqhost_path:
        return False, None

    lines = read_eqhost_file(eqhost_path)
    if not lines:
        return False, eqhost_path

    # Check if any line contains the proxy address
    return any(DEFAULT_PROXY_ADDRESS in line and not line.startswith("#") for line in lines), eqhost_path


def enable_proxy() -> tuple[bool, str | None]:
    """
    Configure EverQuest to use the proxy in a non-destructive way.
    - Adds proxy line to the end if not present
    - Comments out other uncommented Host lines
    - Uncomments proxy line if it's commented

    Returns:
        Tuple[bool, Optional[str]]: (success, error_message)
    """
    eqhost_path = get_eqhost_path()
    if not eqhost_path:
        return False, None

    lines = read_eqhost_file(eqhost_path)

    # If file doesn't exist or is empty, create it with proxy address
    if not lines:
        return write_eqhost_file([DEFAULT_PROXY_ADDRESS], eqhost_path)

    entries = _parse_eqhost_lines(lines)
    has_proxy = False

    for entry in entries:
        if entry.is_proxy:
            # Uncomment the proxy line
            entry.commented = False
            has_proxy = True
        elif entry.is_host and not entry.commented:
            # Comment out other active Host lines
            entry.commented = True

    # If proxy line wasn't in the file at all, add it
    if not has_proxy:
        entries.append(EqHostEntry(raw=DEFAULT_PROXY_ADDRESS, is_host=True, commented=False, is_proxy=True))

    return write_eqhost_file(_serialize_eqhost_entries(entries), eqhost_path)


def disable_proxy() -> tuple[bool, str | None]:
    """
    Configure EverQuest to use the official login server instead of the proxy in a non-destructive way.
    - Comments out the proxy line if present
    - Uncomments the last non-proxy Host line

    Returns:
        Tuple[bool, Optional[str]]: (success, error_message)
    """
    eqhost_path = get_eqhost_path()
    if not eqhost_path:
        return False, None

    lines = read_eqhost_file(eqhost_path)
    if not lines:
        # If file doesn't exist, create it with default login server
        return write_eqhost_file([DEFAULT_LOGIN_SERVER], eqhost_path)

    entries = _parse_eqhost_lines(lines)
    had_active_proxy = False

    # Comment out the proxy line
    for entry in entries:
        if entry.is_proxy and not entry.commented:
            entry.commented = True
            had_active_proxy = True

    # If we disabled the proxy, uncomment the last non-proxy Host line
    if had_active_proxy:
        for entry in reversed(entries):
            if entry.is_host and not entry.is_proxy and entry.commented:
                entry.commented = False
                break

    # If there are no active Host lines at all, add the default login server
    if not any(e.is_host and not e.commented for e in entries):
        entries.append(EqHostEntry(raw=DEFAULT_LOGIN_SERVER, is_host=True, commented=False, is_proxy=False))

    return write_eqhost_file(_serialize_eqhost_entries(entries), eqhost_path)


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
    "EQUI_Animations.xml": [
        "a_rustle",
        "rustlin",
    ],
    "EQUI_ActionsWindow.xml": [
        "rustle-logo",
        "rise of the apes",
    ],
}


def _check_dir_for_rustle(dir_path: str) -> bool:
    """Return True if any file in *dir_path* contains a Rustle fingerprint."""
    for filename, markers in _RUSTLE_FINGERPRINTS.items():
        filepath = os.path.join(dir_path, filename)
        if not os.path.isfile(filepath):
            continue
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read().lower()
            if any(m in content for m in markers):
                return True
        except OSError:
            logger.debug("Could not read %s for Rustle detection", filepath)
    return False


def detect_rustle_ui() -> bool:
    """Scan every subdirectory under ``<eq_dir>/uifiles/`` for Rustle UI
    fingerprints.  The result is cached in ``_cache["rustle_present"]`` so
    subsequent calls (and ``get_client_settings()``) are free.

    Returns True if Rustle markers are found in *any* subdirectory.
    """
    eq_dir = find_eq_directory()
    if not eq_dir:
        _cache["rustle_present"] = False
        return False

    uifiles_dir = os.path.join(eq_dir, "uifiles")
    if not os.path.isdir(uifiles_dir):
        _cache["rustle_present"] = False
        return False

    try:
        for entry in os.scandir(uifiles_dir):
            if not entry.is_dir():
                continue
            if _check_dir_for_rustle(entry.path):
                logger.warning("Rustle UI detected in %s", entry.path)
                _cache["rustle_present"] = True
                return True
    except OSError:
        logger.exception("Error scanning uifiles directory")

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
        with open(eqclient_path, "r", encoding="utf-8", errors="replace") as f:
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
