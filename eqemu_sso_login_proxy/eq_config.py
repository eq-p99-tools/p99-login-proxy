"""
EverQuest Configuration Manager

This module handles finding the EverQuest installation directory and managing
the eqhost.txt file which controls which login server the game connects to.
"""

import os
import logging
import winreg
import string
import glob
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List, Set

# Set up logging
logger = logging.getLogger("eq_config")

# Simple cache for paths
_cache = {
    "eq_directory": None,
    "eqhost_path": None
}

# Default EverQuest installation paths to check
DEFAULT_EQ_PATHS = [
    r"C:\Program Files (x86)\Project1999",
    r"C:\Program Files\Project1999",
    r"D:\Program Files (x86)\Project1999",
    r"D:\Program Files\Project1999",
    r"C:\Project1999",
    r"D:\Project1999",
    r"C:\Games\Project1999",
    r"D:\Games\Project1999",
    r"C:\Program Files (x86)\EverQuest",
    r"C:\Program Files\EverQuest",
    r"D:\Program Files (x86)\EverQuest",
    r"D:\Program Files\EverQuest",
    r"C:\EverQuest",
    r"D:\EverQuest",
    r"C:\Games\EverQuest",
    r"D:\Games\EverQuest",
    r"C:\Program Files (x86)\Sony\EverQuest",
    r"C:\Program Files\Sony\EverQuest",
    r"D:\Program Files (x86)\Sony\EverQuest",
    r"D:\Program Files\Sony\EverQuest",
]

# Default login server address and proxy address
DEFAULT_LOGIN_SERVER = "Host=login.eqemulator.net:5998"
DEFAULT_PROXY_ADDRESS = "Host=localhost:5998"


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
            available_drives.append(f"{drive}:")
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


def find_eq_in_program_files() -> Set[str]:
    """
    Search for EverQuest in Program Files directories.
    
    Returns:
        Set[str]: Set of potential EverQuest installation paths
    """
    potential_paths = set()
    drives = get_available_drives()
    
    # Common directory patterns to search in
    program_dirs = [
        "Program Files",
        "Program Files (x86)",
        "Games",
        "",  # Root of drive
    ]
    
    # Common subdirectory names
    eq_dirs = [
        "EverQuest",
        "Project1999",
        "Sony\\EverQuest",
        "Sony Online Entertainment\\EverQuest",
    ]
    
    for drive in drives:
        for prog_dir in program_dirs:
            base_path = os.path.join(drive, prog_dir)
            if not os.path.exists(base_path):
                continue
                
            # Check specific EQ directory names
            for eq_dir in eq_dirs:
                full_path = os.path.join(base_path, eq_dir)
                if os.path.exists(full_path) and is_valid_eq_directory(full_path):
                    logger.info(f"Found EverQuest directory in Program Files via Common Name: {full_path}")
                    potential_paths.add(full_path)
            
            # Also check for any directory containing "everquest" or "eq" in the name
            try:
                for item in os.listdir(base_path):
                    item_path = os.path.join(base_path, item)
                    if os.path.isdir(item_path) and (
                        "everquest" in item.lower() or 
                        "eq" in item.lower() or 
                        "project" in item.lower()
                    ):
                        if is_valid_eq_directory(item_path):
                            logger.info(f"Found EverQuest directory in Program Files via Name: {item_path}")
                            potential_paths.add(item_path)
            except (PermissionError, FileNotFoundError):
                pass
    
    return potential_paths


def find_eq_from_shortcuts() -> Set[str]:
    """
    Find EverQuest installation by checking shortcuts in the Start Menu.
    
    Returns:
        Set[str]: Set of potential EverQuest installation paths
    """
    potential_paths = set()
    
    # Common Start Menu locations
    start_menu_paths = [
        os.path.join(os.environ["PROGRAMDATA"], "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")
    ]
    
    # Find all .lnk files in Start Menu
    for start_menu in start_menu_paths:
        if not os.path.exists(start_menu):
            continue
            
        for root, dirs, files in os.walk(start_menu):
            for file in files:
                if file.lower().endswith(".lnk") and (
                    "everquest" in file.lower() or 
                    "eq" in file.lower() or 
                    "project" in file.lower()
                ):
                    shortcut_path = os.path.join(root, file)
                    try:
                        # Use PowerShell to resolve the shortcut target
                        cmd = f'powershell -command "(New-Object -ComObject WScript.Shell).CreateShortcut(\"{shortcut_path}\").TargetPath"'
                        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                        target_path = result.stdout.strip()
                        
                        if target_path and os.path.exists(target_path):
                            # Get the directory containing the target executable
                            if os.path.isfile(target_path):
                                target_dir = os.path.dirname(target_path)
                            else:
                                target_dir = target_path
                                
                            if is_valid_eq_directory(target_dir):
                                potential_paths.add(target_dir)
                            elif os.path.basename(target_path).lower() == "eqgame.exe":
                                potential_paths.add(os.path.dirname(target_path))
                    except Exception as e:
                        logger.warning(f"Error resolving shortcut {shortcut_path}: {e}")
    
    return potential_paths


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
    
    potential_paths = set()
    
    # Method 1: Check common installation paths
    for path in DEFAULT_EQ_PATHS:
        if os.path.exists(path) and is_valid_eq_directory(path):
            logger.info(f"Found EverQuest directory in a default path: {path}")
            return path
    
    # Method 2: Search Program Files directories
    potential_paths.update(find_eq_in_program_files())
    
    # Method 3: Search Start Menu shortcuts
    potential_paths.update(find_eq_from_shortcuts())
    
    # If we found any potential paths, return the first one
    if potential_paths:
        eq_dir = next(iter(potential_paths))
        logger.info(f"Found EverQuest directory: {eq_dir}")
        # Update cache
        _cache["eq_directory"] = eq_dir
        return eq_dir
    
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
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(eqhost_path), exist_ok=True)
        
        with open(eqhost_path, 'w') as f:
            for line in lines:
                f.write(f"{line}\n")
        logger.info(f"Successfully wrote to eqhost.txt at {eqhost_path}")
        return True
    except Exception as e:
        logger.error(f"Error writing to eqhost.txt: {e}")
        return False


def is_using_proxy() -> Tuple[bool, Optional[str]]:
    """
    Check if EverQuest is configured to use the proxy.
    
    Returns:
        Tuple[bool, Optional[str]]: 
            - bool: True if using proxy, False otherwise
            - Optional[str]: Path to eqhost.txt if found, None otherwise
    """
    eqhost_path = get_eqhost_path()
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
    using_proxy, eqhost_path = is_using_proxy()
    
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
