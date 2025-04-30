import os
import sys
import shutil
import subprocess
import logging
import requests
import wx
import semver

from eqemu_sso_login_proxy import config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("updater.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("updater")

# GitHub repository information
GITHUB_REPO = "rm-you/middlemand-python"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
GITHUB_LATEST_RELEASE_URL = f"{GITHUB_API_URL}/latest"
GITHUB_TAGGED_RELEASES_URL = f"{GITHUB_API_URL}/tags/{tag}"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO}"


if os.path.exists("github_auth.json"):
    with open("github_auth.json") as gha:
        auth_data = json.load(gha)
    get = functools.partial(requests.get, auth=requests.auth.HTTPBasicAuth(
        auth_data['username'], auth_data['key']))
else:
    get = requests.get


def get_release_from_github(tag=None):
    if tag:
        tag_data = get(GITHUB_TAGGED_RELEASES_URL.format(tag=tag)).json()
    else:
        tag_data = get(GITHUB_LATEST_RELEASE_URL).json()
    version = semver.Version.parse(tag_data['tag_name'])
    return version, tag_data


class Updater:
    """Class to handle application updates"""
    def __init__(self):
        # Initialize callback functions
        self.update_available_callback = None  # Current version, new version
        self.update_progress_callback = None  # Status message, progress percentage
        self.update_complete_callback = None  # Success, message
        logger.info(f"Current application version: {config.APP_VERSION}")
    
    def _normalize_version(self, version_str):
        """Normalize version string to semver format (x.y.z)"""
        # Remove 'v' prefix if present
        version_str = version_str.lstrip('v')
            
        # Split version into components
        parts = version_str.split('.')
        
        # Ensure we have at least 3 components (major.minor.patch)
        while len(parts) < 3:
            parts.append('0')
            
        # Join back with only the first 3 components
        normalized = '.'.join(parts[:3])
        
        # Validate that it's a proper semver
        try:
            normalized_semver = semver.Version.parse(normalized)
            return normalized_semver
        except ValueError:
            # If invalid, return a default valid semver
            logger.warning(f"Invalid semver: {version_str}, using 0.0.0 instead")
            return semver.Version(0, 0, 0)
    
    def download_and_unpack(self, url: str):
        # pylint: disable=no-member
        asset_data = get(url).json()
        zip_url = None
        for asset in asset_data:
            if asset['content_type'] == 'application/x-zip-compressed':
                zip_url = asset['browser_download_url']
                break
        if zip_url:
            zip_data = get(zip_url, stream=True)
            size = int(zip_data.headers.get('content-length', 0))
            if self.update_progress_callback:
                self.update_progress_callback(f"Downloading update...", 0)
            with io.BytesIO() as bio:
                downloaded = 0
                for data in zip_data.iter_content(chunk_size=int(size/100)):
                    bio.write(data)
                    downloaded += len(data)
                    if self.update_progress_callback:
                        self.update_progress_callback(f"Downloading update...", int(downloaded / size * 98))
                self.update_progress_callback(f"Extracting...", 99)
                with zipfile.ZipFile(bio) as zip_file:
                    exe_name = zip_file.namelist()[0]
                    zip_file.extractall()
                if self.update_progress_callback:
                    self.update_progress_callback(f"Update complete.", 100)
                return exe_name
        if self.update_progress_callback:
            self.update_progress_callback(f"Update failed.", 100)
        return None

    def check_for_updates(self):
        """Check if updates are available"""
        logger.info("Checking for updates...")
        if self.update_progress_callback:
            self.update_progress_callback("Checking for updates...", 0)
        
        try:
            latest_version, tag_data = get_release_from_github()
            logger.info(f"Latest version: {latest_version}, Current version: {config.APP_VERSION}")
            # Compare versions using semver
            if latest_version > config.APP_VERSION:
                logger.info(f"Update available: {latest_version} (current: {config.APP_VERSION})")
                if self.update_available_callback:
                    self.update_available_callback(config.APP_VERSION, latest_version, tag_data)
                return True
            else:
                logger.info(f"No updates available (current: {config.APP_VERSION}, latest: {latest_version})")
                if self.update_progress_callback:
                    self.update_progress_callback("No updates available", 100)
                return False
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            if self.update_progress_callback:
                self.update_progress_callback(f"Error checking for updates: {str(e)}", 0)
            return False
    

    def install_update(self, extracted_dir, version):
        """Install the update by replacing files"""
        logger.info(f"Installing update from {extracted_dir}...")
        if self.update_progress_callback:
            self.update_progress_callback("Installing update...", 60)
        
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        try:
            # Copy files from extracted directory to app directory
            # Skip certain directories and files
            skip_dirs = ['.git', '.idea', '__pycache__', '.venv', '.venv-3.11']
            skip_files = ['proxyconfig.ini', 'updater.log']
            
            # Get list of files to copy
            files_to_copy = []
            for root, dirs, files in os.walk(extracted_dir):
                # Remove directories to skip
                for skip_dir in skip_dirs:
                    if skip_dir in dirs:
                        dirs.remove(skip_dir)
                
                for file in files:
                    if file in skip_files:
                        continue
                    
                    src_path = os.path.join(root, file)
                    rel_path = os.path.relpath(src_path, extracted_dir)
                    dest_path = os.path.join(app_dir, rel_path)
                    
                    files_to_copy.append((src_path, dest_path))
            
            # Copy files
            total_files = len(files_to_copy)
            for i, (src_path, dest_path) in enumerate(files_to_copy):
                # Create destination directory if it doesn't exist
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                
                # Copy the file
                shutil.copy2(src_path, dest_path)
                
                # Update progress
                progress = min(90, int(i / total_files * 30) + 60)
                if self.update_progress_callback:
                    self.update_progress_callback(f"Installing update... ({i+1}/{total_files})", progress)
            
            logger.info("Update installed successfully")
            if self.update_progress_callback:
                self.update_progress_callback("Update installed successfully", 100)
            if self.update_complete_callback:
                self.update_complete_callback(True, f"Updated to version {version}")
            return True
            
        except Exception as e:
            logger.error(f"Error installing update: {e}")
            if self.update_progress_callback:
                self.update_progress_callback(f"Error installing update: {str(e)}", 0)
            if self.update_complete_callback:
                self.update_complete_callback(False, f"Error installing update: {str(e)}")
            return False
    
    def perform_update(self, version):
        """Perform the complete update process"""
        # Download the update
        logger.info(f"Downloading update version {version}...")
        exe_path = self.download_and_unpack(tag_data['assets_url'])
        if not exe_path:
            return False
        
        # Install the update
        if exe_path:
            logger.info(f"Installing update version {version}...")
            current_exe = os.path.basename(sys.executable).lower()
            if not current_exe.startswith("python"):
                if current_exe == f"P99LoginProxy-{config.APP_VERSION}.exe":
                    pass
                else:
                    os.rename(current_exe,
                                f"P99LoginProxy-{config.APP_VERSION}.exe")
                    os.rename(exe_path, "P99LoginProxy.exe")
                    newest_exe = "P99LoginProxy.exe"
            if self.update_complete_callback:
                self.update_complete_callback(True, f"Updated to version {version}")
            with subprocess.Popen([newest_exe]):
                sys.exit()
        elif self.update_complete_callback:
            self.update_complete_callback(False, f"Error installing update.")
        return False


def check_for_updates_on_startup(parent=None):
    """Check for updates on startup and prompt user to update if available"""
    updater = Updater()
    if parent:
        parent.has_update = False
        parent.new_version = None
        parent.updater = updater
    
    # Define callback functions
    def on_update_available(current_version, new_version, tag_data):
        # Prompt user to update
        print("on_update_available callback triggered")
        if parent:
            parent.has_update = True
            parent.new_version = new_version
            message = f"A new version is available: {new_version}\n"
            message += f"Current version: {current_version}\n\n"
            message += "Would you like to update now?"
            response = wx.MessageBox(
                message,
                "Update Available",
                wx.YES_NO | wx.ICON_QUESTION,
                parent
            )
            
            if response == wx.YES:
                # Create progress dialog
                progress_dialog = wx.ProgressDialog(
                    "Updating",
                    "Preparing to update...",
                    maximum=100,
                    parent=parent,
                    style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_CAN_ABORT
                )
                
                # Define progress callback
                def on_update_progress(message, progress):
                    if progress_dialog:
                        result, _ = progress_dialog.Update(progress, message)
                        if not result:  # User clicked Cancel
                            progress_dialog.Destroy()
                
                # Define completion callback
                def on_update_complete(success, message):
                    if progress_dialog:
                        progress_dialog.Destroy()
                    
                    if success:
                        restart_response = wx.MessageBox(
                            f"{message}\n\nRestart application now?",
                            "Update Complete",
                            wx.YES_NO | wx.ICON_QUESTION,
                            parent
                        )
                        
                        if restart_response == wx.YES:
                            updater.restart_application()
                    else:
                        wx.MessageBox(
                            message,
                            "Update Failed",
                            wx.OK | wx.ICON_ERROR,
                            parent
                        )
                
                # Set callbacks
                updater.update_progress_callback = on_update_progress
                updater.update_complete_callback = on_update_complete
                
                # Start update
                updater.perform_update(new_version, tag_data)
    
    # Set callback
    updater.update_available_callback = on_update_available
    
    # Check for updates
    updater.check_for_updates()
    
    return updater
