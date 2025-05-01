import io
import functools
import json
import os
import subprocess
import sys
import zipfile

import requests
import semver
import wx
import logging
from eqemu_sso_login_proxy.config import APP_VERSION

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"updater.log"),
        logging.StreamHandler()
    ]
)

LOG = logging.getLogger("updater")

GITHUB_API_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/rm-you/middlemand-python/releases/latest")
GITHUB_API_TAGGED_RELEASE_URL = (
    "https://api.github.com/repos/rm-you/middlemand-python/releases/tags/{tag}")

if os.path.exists("github_auth.json"):
    with open("github_auth.json") as gha:
        auth_data = json.load(gha)
    get = functools.partial(requests.get, auth=requests.auth.HTTPBasicAuth(
        auth_data['username'], auth_data['key']))
else:
    get = requests.get


def get_release_from_github(tag=None):
    if tag:
        tag_data = get(GITHUB_API_TAGGED_RELEASE_URL.format(tag=tag)).json()
    else:
        tag_data = get(GITHUB_API_LATEST_RELEASE_URL).json()
    version = semver.Version.parse(tag_data['tag_name'].lstrip('v'))
    return version, tag_data


def download_and_unpack(url: str):
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
    # pylint: disable=no-member
    current_version = APP_VERSION
    LOG.info("Checking for update. Current version: %s", current_version)
    newest_version, tag_data = get_release_from_github()
    if newest_version > current_version:
        LOG.info("Update available. New version: %s", newest_version)
        au_win = wx.MessageDialog(
            None,
            "A new update is available. Would you like to update?\n\n"
            f"Your version: {current_version}\n"
            f"New version: {newest_version}",
            "Update Available", wx.YES | wx.NO | wx.ICON_QUESTION)
        result = au_win.ShowModal()
        au_win.Destroy()
        if result == wx.ID_YES:
            newest_exe = download_and_unpack(tag_data['assets_url'])
            if newest_exe:
                LOG.info("Downloaded new version: %s", newest_exe)
                current_exe = os.path.basename(sys.executable).lower()
                if not current_exe.startswith("python"):
                    if current_exe.lower() == f"p99loginproxy-{current_version}.exe":
                        pass
                    else:
                        # if the new name already exists, remove it first
                        if os.path.exists(f"P99LoginProxy-{current_version}.exe"):
                            os.remove(f"P99LoginProxy-{current_version}.exe")
                        os.rename(current_exe,
                                  f"P99LoginProxy-{current_version}.exe")
                        os.rename(newest_exe, "P99LoginProxy.exe")
                        newest_exe = "P99LoginProxy.exe"
                with subprocess.Popen([newest_exe]):
                    os._exit(0)
            else:
                LOG.error("Failed to update. Continuing with existing version.")
                dlg = wx.MessageDialog(
                    None,
                    "Failed to update. Continuing with existing version.",
                    "Update Error", wx.OK | wx.ICON_ERROR)
                dlg.ShowModal()
                dlg.Destroy()
