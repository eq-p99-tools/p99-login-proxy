"""
EverQuest Configuration Manager

This module handles finding the EverQuest installation directory and managing
the eqhost.txt file which controls which login server the game connects to.
"""

import logging
import os
import string
from dataclasses import dataclass
from typing import List, Optional, Tuple

from p99_sso_login_proxy import config

# Set up logging
logger = logging.getLogger("eq_config")

# Simple cache for paths
_cache = {
    "eq_directory": None,
    "eqhost_path": None,
    "eqclient_path": None,
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


def get_available_drives() -> List[str]:
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


def find_eq_directory() -> Optional[str]:
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


def get_eqhost_path(eq_dir: Optional[str] = None) -> Optional[str]:
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


def get_eqclient_path(eq_dir: Optional[str] = None) -> Optional[str]:
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


def read_eqhost_file(eqhost_path: Optional[str] = None) -> List[str]:
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


def write_eqhost_file(lines: List[str], eqhost_path: Optional[str] = None) -> Tuple[bool, Optional[str]]:
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


def _parse_eqhost_lines(lines: List[str]) -> List[EqHostEntry]:
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


def _serialize_eqhost_entries(entries: List[EqHostEntry]) -> List[str]:
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


def is_using_proxy(eq_dir: Optional[str] = None) -> Tuple[bool, Optional[str]]:
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


def enable_proxy() -> Tuple[bool, Optional[str]]:
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


def disable_proxy() -> Tuple[bool, Optional[str]]:
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


if __name__ == "__main__":
    # Set up console logging for testing
    logging.basicConfig(level=logging.INFO)

    # Test the functions
    status = get_eq_status()
    logger.info("EverQuest Status:")
    for key, value in status.items():
        logger.info("  %s: %s", key, value)
