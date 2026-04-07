import contextlib
import functools
import io
import json
import logging
import os
import subprocess
import sys
import threading
import zipfile

import markdown
import requests
import semver
import wx

from p99_sso_login_proxy import config

# Set up logging: updater.log is only for the `updater` logger (not the root logger).
_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_LOG_FORMATTER = logging.Formatter(_LOG_FORMAT)

try:
    _root = logging.getLogger()
    if not _root.handlers:
        _stream = logging.StreamHandler()
        _stream.setFormatter(_LOG_FORMATTER)
        _root.setLevel(logging.INFO)
        _root.addHandler(_stream)

    LOG = logging.getLogger("updater")
    _updater_log_file = logging.FileHandler("updater.log")
    _updater_log_file.setLevel(logging.INFO)
    _updater_log_file.setFormatter(_LOG_FORMATTER)
    LOG.addHandler(_updater_log_file)
    LOG.setLevel(logging.DEBUG)
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

GITHUB_API_LATEST_RELEASE_URL = "https://api.github.com/repos/eq-p99-tools/p99-login-proxy/releases/latest"
GITHUB_API_TAGGED_RELEASE_URL = "https://api.github.com/repos/eq-p99-tools/p99-login-proxy/releases/tags/{tag}"
GITHUB_API_RELEASES_URL = "https://api.github.com/repos/eq-p99-tools/p99-login-proxy/releases?per_page={max_releases}"

REQUEST_TIMEOUT = (5, 15)  # (connect, read) in seconds

_auth = None
if os.path.exists("github_auth.json"):
    try:
        with open("github_auth.json") as gha:
            auth_data = json.load(gha)
        _auth = requests.auth.HTTPBasicAuth(auth_data["username"], auth_data["key"])
    except (json.JSONDecodeError, KeyError, OSError) as e:
        LOG.warning("Failed to load github_auth.json, using unauthenticated requests: %s", e)

get = functools.partial(requests.get, auth=_auth, timeout=REQUEST_TIMEOUT)


def get_release_from_github(tag=None):
    """Get a specific release from GitHub"""
    resp = get(GITHUB_API_TAGGED_RELEASE_URL.format(tag=tag)) if tag else get(GITHUB_API_LATEST_RELEASE_URL)
    resp.raise_for_status()
    tag_data = resp.json()
    version = semver.Version.parse(tag_data["tag_name"].lstrip("v"))
    return version, tag_data


def get_recent_releases(max_releases=10):
    """Fetch the most recent releases (up to max_releases)"""
    try:
        resp = get(GITHUB_API_RELEASES_URL.format(max_releases=max_releases))
        resp.raise_for_status()
        releases_data = resp.json()
        releases = []

        for release in releases_data:
            version = semver.Version.parse(release["tag_name"].lstrip("v"))
            releases.append(
                {
                    "version": version,
                    "tag_name": release["tag_name"],
                    "name": release.get("name", release["tag_name"]),
                    "body": release.get("body", ""),
                    "published_at": release.get("published_at", ""),
                    "assets_url": release.get("assets_url", ""),
                    "prerelease": release.get("prerelease", False),
                }
            )

        # Sort by version (newest first)
        releases.sort(key=lambda x: x["version"], reverse=True)
        return releases
    except Exception:
        LOG.exception("Failed to fetch recent releases")
        return []


def compile_changelog(releases):
    """Compile release notes into markdown format"""
    changelog = ""

    for release in releases:
        version_str = f"v{release['version']}"
        changelog += f"## {version_str}\n"

        # Process body text into bullet points if not already formatted
        body = release["body"].strip()
        if body:
            # Split by newlines and convert to bullet points if needed
            lines = body.split("\n")
            for line in lines:
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("-") and not line.startswith("*"):
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
    resp = get(url)
    resp.raise_for_status()
    asset_data = resp.json()
    ZIP_CONTENT_TYPES = {"application/x-zip-compressed", "application/zip", "application/octet-stream"}
    zip_url = None
    for asset in asset_data:
        if asset["content_type"] in ZIP_CONTENT_TYPES or asset.get("name", "").endswith(".zip"):
            zip_url = asset["browser_download_url"]
            break
    if zip_url:
        LOG.info("Downloading update from %s", zip_url)
        zip_data = get(zip_url, stream=True)
        zip_data.raise_for_status()
        size = int(zip_data.headers.get("content-length", 0))
        chunk_size = max(size // 100, 8192)
        progress_max = max(size, 1)
        pd = wx.GenericProgressDialog(
            title="Downloading Update",
            message="Downloading update, please wait...",
            maximum=progress_max,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_CAN_ABORT | wx.PD_ELAPSED_TIME | wx.PD_REMAINING_TIME,
        )
        with io.BytesIO() as bio:
            downloaded = 0
            cancelled = False
            for data in zip_data.iter_content(chunk_size=chunk_size):
                bio.write(data)
                downloaded += len(data)
                pd.Update(min(downloaded, progress_max))
                if pd.WasCancelled():
                    cancelled = True
                    break
            pd.Destroy()
            if cancelled:
                return None
            with zipfile.ZipFile(bio) as zip_file:
                for member in zip_file.namelist():
                    if os.path.isabs(member) or ".." in member.split("/"):
                        LOG.error("Zip contains unsafe path: %s", member)
                        return None
                exe_name = zip_file.namelist()[0]
                zip_file.extractall()
            return exe_name
    LOG.info("Failed to download update, no zip found.")
    return None


STABLE_EXE_NAME = "P99LoginProxy.exe"


def _prompt_and_apply_update(releases, latest_version):
    """Show the update prompt and apply the update if accepted. Must run on the main (UI) thread."""
    au_win = wx.MessageDialog(
        None,
        "A new update is available. Would you like to update?\n\n"
        f"Your version: {config.APP_VERSION}\n"
        f"New version: {latest_version}",
        "Update Available",
        wx.YES | wx.NO | wx.ICON_QUESTION,
    )
    result = au_win.ShowModal()
    au_win.Destroy()
    if result != wx.ID_YES:
        return

    assets_url = next((r.get("assets_url") for r in releases if r["version"] == latest_version), None)
    if not assets_url:
        return

    current_exe = os.path.basename(sys.executable)
    is_packaged = not current_exe.lower().startswith("python")
    backed_up = False
    backup_name = f"P99LoginProxy-{config.APP_VERSION}.exe"

    # Rename current exe to versioned backup BEFORE extraction so the zip can
    # extract P99LoginProxy.exe without hitting a Windows file lock.
    if is_packaged and current_exe.lower() == STABLE_EXE_NAME.lower():
        try:
            if os.path.exists(backup_name):
                os.remove(backup_name)
            os.rename(current_exe, backup_name)
            backed_up = True
        except OSError as e:
            LOG.exception("Failed to backup current exe before update")
            _show_update_error(f"Failed to prepare for update: {e}")
            return

    newest_exe = download_and_unpack(assets_url)
    if not newest_exe:
        LOG.error("Failed to download update. Continuing with existing version.")
        if backed_up:
            with contextlib.suppress(OSError):
                os.rename(backup_name, STABLE_EXE_NAME)
        _show_update_error("Failed to download update. Continuing with existing version.")
        return

    LOG.info("Downloaded new version: %s", newest_exe)

    # Ensure the new exe ends up with the stable name
    if is_packaged and newest_exe.lower() != STABLE_EXE_NAME.lower():
        try:
            if os.path.exists(STABLE_EXE_NAME):
                os.remove(STABLE_EXE_NAME)
            os.rename(newest_exe, STABLE_EXE_NAME)
        except OSError as rename_err:
            LOG.error("Failed to rename new exe to stable name: %s", rename_err)
            _show_update_error(
                f"Failed to rename update files: {rename_err}\n\n"
                f"The new version was downloaded as '{newest_exe}'. "
                "You can rename it manually and restart."
            )
            return

    launch_exe = STABLE_EXE_NAME if is_packaged else newest_exe

    app = wx.GetApp()
    if hasattr(app, "transport") and app.transport:
        app.transport.close()
    logging.shutdown()
    with subprocess.Popen([launch_exe]):
        os._exit(0)  # os._exit to bypass atexit/finally handlers that could conflict with the new process


def _on_releases_fetched(releases, notify_no_update):
    """Handle fetched releases on the main (UI) thread."""
    if not releases:
        LOG.info("No releases found.")
        if notify_no_update:
            dlg = wx.MessageDialog(
                None,
                f"Version: {config.APP_VERSION}\n\nCould not retrieve release information.",
                "Update Check",
                wx.OK | wx.ICON_INFORMATION,
            )
            dlg.ShowModal()
            dlg.Destroy()
        return

    prerelease_ok = config.APP_VERSION.prerelease or config.OPT_INTO_PRERELEASES
    visible_releases = releases if prerelease_ok else [r for r in releases if not r["prerelease"]]

    config.CHANGELOG = compile_changelog(visible_releases)
    top_window = wx.GetApp().GetTopWindow()
    if top_window:
        top_window.on_updated_changelog()

    update_candidates = visible_releases

    if not update_candidates:
        LOG.info("No update candidates found.")
        if notify_no_update:
            dlg = wx.MessageDialog(
                None,
                f"Version: {config.APP_VERSION}\n\nThere is no update available, you are running the latest version.",
                "No Update Available",
                wx.OK | wx.ICON_INFORMATION,
            )
            dlg.ShowModal()
            dlg.Destroy()
        return

    latest_version = update_candidates[0]["version"]
    if latest_version > config.APP_VERSION:
        LOG.info("Update available: %s", latest_version)
        _prompt_and_apply_update(releases, latest_version)
    else:
        LOG.info("No update available.")
        if notify_no_update:
            dlg = wx.MessageDialog(
                None,
                f"Version: {config.APP_VERSION}\n\nThere is no update available, you are running the latest version.",
                "No Update Available",
                wx.OK | wx.ICON_INFORMATION,
            )
            dlg.ShowModal()
            dlg.Destroy()


def check_update(notify_no_update=False):
    """Check for updates in a background thread.

    Network I/O runs off the main thread so the UI stays responsive.
    All dialogs and UI updates are marshaled back via wx.CallAfter.

    Args:
        notify_no_update: If True, show a dialog when no update is found
                          (used for manual "Check for Updates" from the menu).
    """

    def _background():
        try:
            LOG.info("Checking for update. Current version: %s", config.APP_VERSION)
            releases = get_recent_releases(10)
            wx.CallAfter(_on_releases_fetched, releases, notify_no_update)
        except Exception as e:
            LOG.exception("Failed to check for update")
            if notify_no_update:
                wx.CallAfter(_show_update_error, str(e))

    thread = threading.Thread(target=_background, daemon=True)
    thread.start()


def _show_update_error(message):
    """Show an update error dialog on the main thread."""
    dlg = wx.MessageDialog(None, f"Failed to check for updates:\n\n{message}", "Update Error", wx.OK | wx.ICON_ERROR)
    dlg.ShowModal()
    dlg.Destroy()
