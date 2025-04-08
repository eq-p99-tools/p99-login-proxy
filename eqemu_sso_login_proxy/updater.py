import os
import sys
import tempfile
import shutil
import subprocess
import json
import time
import logging
from pathlib import Path
import requests
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

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
REPO_OWNER = "rm-you"
REPO_NAME = "middlemand-python"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
GITHUB_RELEASES_URL = f"{GITHUB_API_URL}/releases/latest"
GITHUB_REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"

# Local version file
VERSION_FILE = "version.json"


class Updater(QObject):
    """Class to handle application updates"""
    update_available = pyqtSignal(str, str)  # Current version, new version
    update_progress = pyqtSignal(str, int)  # Status message, progress percentage
    update_complete = pyqtSignal(bool, str)  # Success, message
    
    def __init__(self):
        super().__init__()
        self.current_version = self._get_current_version()
        logger.info(f"Current application version: {self.current_version}")
    
    def _get_current_version(self):
        """Get the current version from the version file or git"""
        # Try to get version from version file
        if os.path.exists(VERSION_FILE):
            try:
                with open(VERSION_FILE, 'r') as f:
                    version_data = json.load(f)
                    return version_data.get('version', '0.0.0')
            except Exception as e:
                logger.error(f"Error reading version file: {e}")
        
        # If version file doesn't exist or is invalid, try to get from git
        try:
            import git
            repo = git.Repo(search_parent_directories=True)
            return repo.git.describe('--tags', '--always')
        except Exception as e:
            logger.error(f"Error getting version from git: {e}")
            return "0.0.0"  # Default version if all else fails
    
    def _update_version_file(self, version):
        """Update the version file with the new version"""
        try:
            with open(VERSION_FILE, 'w') as f:
                json.dump({'version': version, 'updated_at': time.time()}, f)
            logger.info(f"Updated version file to {version}")
            return True
        except Exception as e:
            logger.error(f"Error updating version file: {e}")
            return False
    
    def check_for_updates(self):
        """Check if updates are available"""
        logger.info("Checking for updates...")
        self.update_progress.emit("Checking for updates...", 0)
        
        try:
            response = requests.get(GITHUB_RELEASES_URL, timeout=10)
            if response.status_code != 200:
                logger.error(f"Failed to check for updates: {response.status_code}")
                self.update_progress.emit("Failed to check for updates", 0)
                return False
            
            release_data = response.json()
            latest_version = release_data.get('tag_name', '').lstrip('v')
            
            if not latest_version:
                logger.error("No version tag found in release data")
                self.update_progress.emit("Failed to determine latest version", 0)
                return False
            
            logger.info(f"Latest version: {latest_version}, Current version: {self.current_version}")
            
            # Compare versions (simple string comparison for now)
            if latest_version != self.current_version:
                logger.info(f"Update available: {latest_version}")
                self.update_available.emit(self.current_version, latest_version)
                return True
            else:
                logger.info("Application is up to date")
                self.update_progress.emit("Application is up to date", 100)
                return False
                
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            self.update_progress.emit(f"Error checking for updates: {str(e)}", 0)
            return False
    
    def download_update(self, version):
        """Download the update from GitHub"""
        logger.info(f"Downloading update version {version}...")
        self.update_progress.emit(f"Downloading update version {version}...", 10)
        
        download_url = f"{GITHUB_REPO_URL}/archive/refs/tags/v{version}.zip"
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, "update.zip")
        
        try:
            # Download the update
            response = requests.get(download_url, stream=True, timeout=60)
            if response.status_code != 200:
                logger.error(f"Failed to download update: {response.status_code}")
                self.update_progress.emit("Failed to download update", 0)
                return None
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress = min(30, int(downloaded / total_size * 20) + 10) if total_size > 0 else 20
                        self.update_progress.emit(f"Downloading update... {downloaded}/{total_size} bytes", progress)
            
            logger.info(f"Update downloaded to {zip_path}")
            self.update_progress.emit("Download complete, extracting...", 30)
            return zip_path
            
        except Exception as e:
            logger.error(f"Error downloading update: {e}")
            self.update_progress.emit(f"Error downloading update: {str(e)}", 0)
            return None
    
    def extract_update(self, zip_path):
        """Extract the downloaded update"""
        import zipfile
        
        logger.info(f"Extracting update from {zip_path}...")
        self.update_progress.emit("Extracting update...", 40)
        
        extract_dir = os.path.dirname(zip_path)
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            # Find the extracted directory (should be the only directory)
            extracted_dirs = [d for d in os.listdir(extract_dir) 
                             if os.path.isdir(os.path.join(extract_dir, d)) and d != '__MACOSX']
            
            if not extracted_dirs:
                logger.error("No directories found after extraction")
                self.update_progress.emit("Failed to extract update", 0)
                return None
            
            extracted_dir = os.path.join(extract_dir, extracted_dirs[0])
            logger.info(f"Update extracted to {extracted_dir}")
            self.update_progress.emit("Update extracted, preparing to install...", 50)
            return extracted_dir
            
        except Exception as e:
            logger.error(f"Error extracting update: {e}")
            self.update_progress.emit(f"Error extracting update: {str(e)}", 0)
            return None
    
    def install_update(self, extracted_dir, version):
        """Install the update by replacing files"""
        logger.info(f"Installing update from {extracted_dir}...")
        self.update_progress.emit("Installing update...", 60)
        
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
                self.update_progress.emit(f"Installing update... ({i+1}/{total_files})", progress)
            
            # Update version file
            self._update_version_file(version)
            
            logger.info("Update installed successfully")
            self.update_progress.emit("Update installed successfully", 100)
            self.update_complete.emit(True, f"Updated to version {version}")
            return True
            
        except Exception as e:
            logger.error(f"Error installing update: {e}")
            self.update_progress.emit(f"Error installing update: {str(e)}", 0)
            self.update_complete.emit(False, f"Error installing update: {str(e)}")
            return False
    
    def perform_update(self, version):
        """Perform the complete update process"""
        # Download the update
        zip_path = self.download_update(version)
        if not zip_path:
            return False
        
        # Extract the update
        extracted_dir = self.extract_update(zip_path)
        if not extracted_dir:
            return False
        
        # Install the update
        return self.install_update(extracted_dir, version)
    
    def restart_application(self):
        """Restart the application after update"""
        logger.info("Restarting application...")
        
        try:
            # Get the path to the Python executable and script
            python = sys.executable
            script = os.path.abspath(sys.argv[0])
            
            # Start a new process
            subprocess.Popen([python, script])
            
            # Exit the current process
            sys.exit(0)
            
        except Exception as e:
            logger.error(f"Error restarting application: {e}")
            return False


def check_for_updates_on_startup(parent=None):
    """Check for updates on startup and prompt user to update if available"""
    updater = Updater()
    
    if updater.check_for_updates():
        current_version = updater.current_version
        latest_version = updater.update_available.emit
        
        # Prompt user to update
        if parent:
            response = QMessageBox.question(
                parent,
                "Update Available",
                f"A new version is available: {latest_version}\n"
                f"Current version: {current_version}\n\n"
                "Would you like to update now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if response == QMessageBox.StandardButton.Yes:
                # Perform update
                updater.perform_update(latest_version)
                
                # Prompt to restart
                restart_response = QMessageBox.question(
                    parent,
                    "Update Complete",
                    "Update has been installed. Restart application now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                
                if restart_response == QMessageBox.StandardButton.Yes:
                    updater.restart_application()
    
    return updater
