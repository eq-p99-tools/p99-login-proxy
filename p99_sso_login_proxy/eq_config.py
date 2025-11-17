"""
EverQuest Configuration Manager

This module handles finding the EverQuest installation directory and managing
the eqhost.txt file which controls which login server the game connects to.
"""

import os
import logging
import string
from typing import Optional, Tuple, List

import wx

from p99_sso_login_proxy import config

# Set up logging
logger = logging.getLogger("eq_config")

# Simple cache for paths
_cache = {
    "eq_directory": None,
    "eqhost_path": None
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
DEFAULT_PROXY_ADDRESS = f"Host={config.LISTEN_HOST if config.LISTEN_HOST != '0.0.0.0' else 'localhost'}:{config.LISTEN_PORT}"


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
    
    Returns:
        Optional[str]: Path to EverQuest directory if found, None otherwise
    """
    # Check cache first
    if _cache.get("eq_directory"):
        logger.debug(f"Using cached EverQuest directory: {_cache['eq_directory']}")
        return _cache["eq_directory"]
    
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
    # Update cache with None result
    _cache["eq_directory"] = None
    return None


def get_eqhost_path(eq_dir: Optional[str] = None) -> Optional[str]:
    """
    Get the path to the eqhost.txt file.
    
    Args:
        eq_dir (Optional[str]): EverQuest directory path. If None, will attempt to find it.
        
    Returns:
        Optional[str]: Path to eqhost.txt if found, None otherwise
    """
    # Check cache first
    if _cache.get("eqhost_path"):
        logger.debug(f"Using cached eqhost.txt path: {_cache['eqhost_path']}")
        return _cache["eqhost_path"]
    
    if not eq_dir:
        eq_dir = find_eq_directory()
        if not eq_dir:
            # Update cache with None result
            _cache["eqhost_path"] = None
            return None
    
    # Check for eqhost.txt in the EQ directory
    eqhost_path = os.path.join(eq_dir, "eqhost.txt")
    if os.path.exists(eqhost_path):
        logger.info(f"Found eqhost.txt at {eqhost_path}")
        # Update cache
        _cache["eqhost_path"] = eqhost_path
        return eqhost_path
    
    # Not found
    # Update cache with None result
    _cache["eqhost_path"] = None
    return None


def get_eqclient_path(eq_dir: Optional[str] = None) -> Optional[str]:
    """
    Get the path to the eqclient.ini file.

    Args:
        eq_dir (Optional[str]): EverQuest directory path. If None, will attempt to find it.

    Returns:
        Optional[str]: Path to eqclient.ini if found, None otherwise
    """
    if not eq_dir:
        eq_dir = find_eq_directory()
        if not eq_dir:
            return None
    eqclient_path = os.path.join(eq_dir, "eqclient.ini")
    if os.path.exists(eqclient_path):
        return eqclient_path
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
            with open(eqhost_path, 'r') as f:
                return [line.strip() for line in f.readlines()]
        else:
            logger.warning(f"eqhost.txt not found at {eqhost_path}")
            return []
    except Exception as e:
        logger.error(f"Error reading eqhost.txt: {e}")
        return []


def write_eqhost_file(lines: List[str], eqhost_path: Optional[str] = None) -> bool:
    """
    Write contents to the eqhost.txt file.
    
    Args:
        lines (List[str]): Lines to write to the file
        eqhost_path (Optional[str]): Path to eqhost.txt. If None, will attempt to find it.
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not eqhost_path:
        eqhost_path = get_eqhost_path()
        if not eqhost_path:
            return False

    try:
        # Check if the eqhost file is read-only
        if not os.access(eqhost_path, os.W_OK):
            # Make it writeable
            os.chmod(eqhost_path, 0o777)

        with open(eqhost_path, 'w') as f:
            for line in lines:
                f.write(f"{line}\n")
        logger.info(f"Successfully wrote to eqhost.txt at {eqhost_path}")
        return True
    except Exception as e:
        logger.error(f"Error writing to eqhost.txt: {e}")
        wx.MessageBox("Failed to write to eqhost.txt (this is likely a permissions issue):\n\n"
                      f"{str(e)}", "Error", wx.OK | wx.ICON_ERROR)
        return False


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
    return any(DEFAULT_PROXY_ADDRESS in line and not line.startswith('#') for line in lines), eqhost_path


def enable_proxy() -> bool:
    """
    Configure EverQuest to use the proxy in a non-destructive way.
    - Adds proxy line to the end if not present
    - Comments out other uncommented Host lines
    - Uncomments proxy line if it's commented
    
    Returns:
        bool: True if successful, False otherwise
    """
    eqhost_path = get_eqhost_path()
    if not eqhost_path:
        return False
    
    lines = read_eqhost_file(eqhost_path)
    
    # If file doesn't exist or is empty, create it with proxy address
    if not lines:
        return write_eqhost_file([DEFAULT_PROXY_ADDRESS], eqhost_path)
    
    # Process the file line by line
    new_lines = []
    host_lines = []
    proxy_line = None
    commented_proxy_line = None
    
    for line in lines:
        stripped = line.strip()
        # Skip empty lines but preserve them
        if not stripped:
            new_lines.append(line)
            continue
            
        # Check if this is our proxy line (commented or not)
        if DEFAULT_PROXY_ADDRESS in stripped:
            if stripped.startswith('#'):
                commented_proxy_line = line
            else:
                # Already have an uncommented proxy line
                proxy_line = line
                new_lines.append(line)  # Keep it where it is for now
        # Check if this is a Host line
        elif stripped.startswith('Host=') and not stripped.startswith('#'):
            # This is an uncommented Host line, save it to comment out later
            host_lines.append(line)
        else:
            # Keep all other lines as they are
            new_lines.append(line)
    
    # If we found uncommented Host lines, comment them and add to the end
    for host_line in host_lines:
        if host_line not in new_lines:  # Avoid duplicates
            new_lines.append(f'#{host_line.strip()}')
    
    # If we have a commented proxy line but no uncommented one, uncomment it
    if commented_proxy_line and not proxy_line:
        proxy_line = commented_proxy_line.lstrip('#').strip()
        # Remove the commented version if it's in our new lines
        if commented_proxy_line in new_lines:
            new_lines.remove(commented_proxy_line)
        new_lines.append(proxy_line)
    
    # If we don't have an uncommented proxy line yet, add it to the end
    if not proxy_line:
        new_lines.append(f'{DEFAULT_PROXY_ADDRESS}')
    
    return write_eqhost_file(new_lines, eqhost_path)


def disable_proxy() -> bool:
    """
    Configure EverQuest to use the official login server instead of the proxy in a non-destructive way.
    - Comments out the proxy line if present
    - Uncomments the last non-proxy Host line
    
    Returns:
        bool: True if successful, False otherwise
    """
    eqhost_path = get_eqhost_path()
    if not eqhost_path:
        return False
    
    lines = read_eqhost_file(eqhost_path)
    if not lines:
        # If file doesn't exist, create it with default login server
        return write_eqhost_file([DEFAULT_LOGIN_SERVER], eqhost_path)
    
    # Process the file line by line
    new_lines = []
    commented_host_lines = []
    proxy_line_index = None
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip empty lines but preserve them
        if not stripped:
            new_lines.append(line)
            continue
            
        # Check if this is our proxy line
        if DEFAULT_PROXY_ADDRESS in stripped:
            if not stripped.startswith('#'):
                # Comment out the proxy line
                new_lines.append(f'#{stripped}')
                proxy_line_index = i
            else:
                # Already commented, keep as is
                new_lines.append(line)
        # Check if this is a commented Host line (not proxy)
        elif stripped.startswith('#') and stripped.lstrip('#').strip().startswith('Host=') and DEFAULT_PROXY_ADDRESS not in stripped:
            commented_host_lines.append((i, line))
            new_lines.append(line)  # Keep it for now
        else:
            # Keep all other lines as they are
            new_lines.append(line)
    
    # If we commented out the proxy line and have commented host lines, uncomment the last one
    if proxy_line_index is not None and commented_host_lines:
        # Find the last commented host line
        last_index, last_line = commented_host_lines[-1]
        # Remove it from where it was
        new_lines.pop(last_index)
        # Add the uncommented version
        uncommented = last_line.lstrip('#').strip()
        # Add it back at the end
        new_lines.append(f'{uncommented}')
    
    # If we have no Host lines at all, add the default login server
    if not any(line.strip().startswith('Host=') and not line.strip().startswith('#') for line in new_lines):
        new_lines.append(f'{DEFAULT_LOGIN_SERVER}')
    
    return write_eqhost_file(new_lines, eqhost_path)


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
        "eqhost_contents": read_eqhost_file(eqhost_path) if eqhost_path else []
    }
    
    return status


if __name__ == "__main__":
    # Set up console logging for testing
    logging.basicConfig(level=logging.INFO)
    
    # Test the functions
    status = get_eq_status()
    print("EverQuest Status:")
    for key, value in status.items():
        print(f"  {key}: {value}")
