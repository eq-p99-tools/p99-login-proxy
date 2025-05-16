import functools
import io
import json
import logging
import os
import subprocess
import sys
import zipfile

import markdown
import requests
import semver
import wx

from p99_sso_login_proxy import config

# Set up logging
try:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f"updater.log"),
            logging.StreamHandler()
        ]
    )
    LOG = logging.getLogger("updater")
except Exception as e:
    class PrintLogger:
        def info(self, msg, *args):
            print(msg % args)
        def error(self, msg, *args):
            print(msg % args)
        def warning(self, msg, *args):
            print(msg % args)
        def debug(self, msg, *args):
            print(msg % args)
    LOG = PrintLogger()
    LOG.warning("Failed to set up logging: %s", e)

GITHUB_API_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/eq-p99-tools/p99-login-proxy/releases/latest")
GITHUB_API_TAGGED_RELEASE_URL = (
    "https://api.github.com/repos/eq-p99-tools/p99-login-proxy/releases/tags/{tag}")
GITHUB_API_RELEASES_URL = (
    "https://api.github.com/repos/eq-p99-tools/p99-login-proxy/releases?per_page={max_releases}")

if os.path.exists("github_auth.json"):
    with open("github_auth.json") as gha:
        auth_data = json.load(gha)
    get = functools.partial(requests.get, auth=requests.auth.HTTPBasicAuth(
        auth_data['username'], auth_data['key']))
else:
    get = requests.get


def get_release_from_github(tag=None):
    """Get a specific release from GitHub"""
    if tag:
        tag_data = get(GITHUB_API_TAGGED_RELEASE_URL.format(tag=tag)).json()
    else:
        tag_data = get(GITHUB_API_LATEST_RELEASE_URL).json()
    version = semver.Version.parse(tag_data['tag_name'].lstrip('v'))
    return version, tag_data


def get_recent_releases(max_releases=10):
    """Fetch the most recent releases (up to max_releases)"""
    try:
        releases_data = get(GITHUB_API_RELEASES_URL.format(max_releases=max_releases)).json()
        releases = []
        
        for release in releases_data:
            version = semver.Version.parse(release['tag_name'].lstrip('v'))
            releases.append({
                'version': version,
                'tag_name': release['tag_name'],
                'name': release.get('name', release['tag_name']),
                'body': release.get('body', ''),
                'published_at': release.get('published_at', ''),
                'assets_url': release.get('assets_url', '')
            })
        
        # Sort by version (newest first)
        releases.sort(key=lambda x: x['version'], reverse=True)
        return releases
    except Exception as e:
        LOG.error(f"Failed to fetch recent releases: {e}")
        return []


def compile_changelog(releases):
    """Compile release notes into markdown format"""
    changelog = ""
    
    for release in releases:
        version_str = f"v{release['version']}"
        changelog += f"## {version_str}\n"
        
        # Process body text into bullet points if not already formatted
        body = release['body'].strip()
        if body:
            # Split by newlines and convert to bullet points if needed
            lines = body.split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('-') and not line.startswith('*'):
                    changelog += f"- {line}\n"
                elif line:
                    changelog += f"{line}\n"
        else:
            changelog += f"- Release {version_str}\n"
        
        changelog += "\n"
    
    return markdown.markdown(changelog)


def download_and_unpack(url: str):
    """Download and unpack the update zip file"""
    # pylint: disable=no-member
    asset_data = get(url).json()
    zip_url = None
    for asset in asset_data:
        if asset['content_type'] == 'application/x-zip-compressed':
            zip_url = asset['browser_download_url']
            break
    if zip_url:
        LOG.info("Downloading update from %s", zip_url)
        zip_data = get(zip_url, stream=True)
        size = int(zip_data.headers.get('content-length', 0))
        pd = wx.GenericProgressDialog(
            title="Downloading Update",
            message="Downloading update, please wait...",
            maximum=size,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_CAN_ABORT |
                  wx.PD_ELAPSED_TIME | wx.PD_REMAINING_TIME
        )
        with io.BytesIO() as bio:
            downloaded = 0
            cancelled = False
            for data in zip_data.iter_content(chunk_size=int(size/100)):
                bio.write(data)
                downloaded += len(data)
                pd.Update(downloaded)
                if pd.WasCancelled():
                    cancelled = True
                    break
            pd.Destroy()
            if cancelled:
                return None
            with zipfile.ZipFile(bio) as zip_file:
                exe_name = zip_file.namelist()[0]
                zip_file.extractall()
            return exe_name
    LOG.info("Failed to download update, no zip found.")
    return None


def check_update():
    """Check for updates and return True if update is available"""
    try:
        LOG.info(f"Checking for update. Current version: {config.APP_VERSION}")
        
        # Get recent releases and compile changelog
        releases = get_recent_releases(10)
        if releases:
            # Update the markdown changelog in config
            config.CHANGELOG = compile_changelog(releases)
            wx.GetApp().GetTopWindow().on_updated_changelog()
            
            # Check if an update is available
            latest_version = releases[0]['version']
            if latest_version > config.APP_VERSION:
                LOG.info(f"Update available: {latest_version}")
                au_win = wx.MessageDialog(
                    None,
                    "A new update is available. Would you like to update?\n\n"
                    f"Your version: {config.APP_VERSION}\n"
                    f"New version: {latest_version}",
                    "Update Available", wx.YES | wx.NO | wx.ICON_QUESTION)
                result = au_win.ShowModal()
                au_win.Destroy()
                if result == wx.ID_YES:
                    assets_url = next((r.get('assets_url') for r in releases if r['version'] == latest_version), None)
                    if assets_url:
                        newest_exe = download_and_unpack(assets_url)
                        if newest_exe:
                            LOG.info("Downloaded new version: %s", newest_exe)
                            current_exe = os.path.basename(sys.executable).lower()
                            if not current_exe.startswith("python"):
                                if current_exe.lower() == f"p99loginproxy-{config.APP_VERSION}.exe":
                                    pass
                                else:
                                    # if the new name already exists, remove it first
                                    if os.path.exists(f"P99LoginProxy-{config.APP_VERSION}.exe"):
                                        os.remove(f"P99LoginProxy-{config.APP_VERSION}.exe")
                                    os.rename(current_exe,
                                              f"P99LoginProxy-{config.APP_VERSION}.exe")
                                    os.rename(newest_exe, "P99LoginProxy.exe")
                                    newest_exe = "P99LoginProxy.exe"
                            with subprocess.Popen([newest_exe]):
                                os._exit(0)
                        else:
                            LOG.error("Failed to download update. Continuing with existing version.")
                            dlg = wx.MessageDialog(
                                None,
                                "Failed to download update. Continuing with existing version.",
                                "Update Error", wx.OK | wx.ICON_ERROR)
                            dlg.ShowModal()
                            dlg.Destroy()
                return True
            else:
                LOG.info("No update available.")
                return False
        else:
            LOG.info("No releases found.")
            return False
    except Exception as e:
        LOG.error(f"Failed to check for update: {e}")
        return False
