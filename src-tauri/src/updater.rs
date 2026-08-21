use std::collections::HashMap;
use std::fmt::Write as _;
use std::fs::{File, OpenOptions};
use std::io::ErrorKind;
#[cfg(any(windows, test))]
use std::io::{Cursor, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;

use chrono::{Local, NaiveTime, TimeZone};
use futures_util::StreamExt;
use proxy_core::{
    expected_linux_appimage_asset_name, expected_windows_zip_asset_name, load_config, version,
    version_string,
};
use pulldown_cmark::{html, Options, Parser};
use semver::Version;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter};
use tracing::{info, warn};

const GITHUB_RELEASES_URL: &str =
    "https://api.github.com/repos/eq-p99-tools/p99-login-proxy/releases?per_page=10";
const CHECKSUM_ASSET_NAME: &str = "SHA256SUMS";
const WAIT_FOR_UPDATE_LOCK_ARG: &str = "--wait-for-update-lock";
const UPDATE_PARENT_WAIT_TIMEOUT: Duration = Duration::from_secs(60);

static CHANGELOG_HTML: Mutex<Option<String>> = Mutex::new(None);

fn update_lock_path_from_args(
    args: impl IntoIterator<Item = std::ffi::OsString>,
) -> Result<Option<PathBuf>, String> {
    let mut args = args.into_iter();
    while let Some(arg) = args.next() {
        if arg == WAIT_FOR_UPDATE_LOCK_ARG {
            return args
                .next()
                .map(PathBuf::from)
                .map(Some)
                .ok_or_else(|| format!("{WAIT_FOR_UPDATE_LOCK_ARG} requires a path"));
        }
    }
    Ok(None)
}

pub fn wait_for_update_parent_if_requested() -> Result<(), String> {
    let Some(path) = update_lock_path_from_args(std::env::args_os())? else {
        return Ok(());
    };
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .map_err(|error| format!("Could not open update relaunch lock: {error}"))?;
    let started = std::time::Instant::now();
    loop {
        match fs2::FileExt::try_lock_exclusive(&file) {
            Ok(()) => break,
            Err(error) if is_update_lock_contention(&error) => {
                if started.elapsed() >= UPDATE_PARENT_WAIT_TIMEOUT {
                    return Err("Timed out waiting for the previous version to exit".into());
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            Err(error) => {
                return Err(format!("Could not wait for the previous version: {error}"));
            }
        }
    }
    fs2::FileExt::unlock(&file).map_err(|error| error.to_string())?;
    drop(file);
    let _ = std::fs::remove_file(path);
    Ok(())
}

fn is_update_lock_contention(error: &std::io::Error) -> bool {
    error.kind() == ErrorKind::WouldBlock
        || (cfg!(windows) && matches!(error.raw_os_error(), Some(32 | 33)))
}

pub fn spawn_update_relaunch(executable: &Path) -> Result<File, String> {
    let lock_path = std::env::temp_dir().join(format!(
        "p99-login-proxy-update-{}.lock",
        std::process::id()
    ));
    let _ = std::fs::remove_file(&lock_path);
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&lock_path)
        .map_err(|error| format!("Could not create update relaunch lock: {error}"))?;
    fs2::FileExt::lock_exclusive(&file)
        .map_err(|error| format!("Could not lock update relaunch marker: {error}"))?;
    if let Err(error) = std::process::Command::new(executable)
        .arg(WAIT_FOR_UPDATE_LOCK_ARG)
        .arg(&lock_path)
        .spawn()
    {
        let _ = fs2::FileExt::unlock(&file);
        drop(file);
        let _ = std::fs::remove_file(lock_path);
        return Err(format!("Update installed, but relaunch failed: {error}"));
    }
    Ok(file)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpdateCheckResult {
    pub available: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    pub title: String,
    pub message: String,
}

fn update_check_title(available: bool, message: &str) -> String {
    if available {
        "Update Available".into()
    } else if message.contains("Could not retrieve") {
        "Update Check".into()
    } else {
        "No Update Available".into()
    }
}

fn update_check_result(
    available: bool,
    version: Option<String>,
    message: impl Into<String>,
) -> UpdateCheckResult {
    let message = message.into();
    UpdateCheckResult {
        available,
        version,
        title: update_check_title(available, &message),
        message,
    }
}

#[derive(Debug, Deserialize)]
struct GitHubRelease {
    tag_name: String,
    body: Option<String>,
    prerelease: bool,
    #[serde(default)]
    assets: Vec<GitHubAsset>,
}

#[derive(Debug, Clone, Deserialize)]
struct GitHubAsset {
    name: String,
    browser_download_url: String,
}

#[derive(Debug, Deserialize)]
struct GitHubAuth {
    username: String,
    key: String,
}

pub fn cached_changelog_html() -> String {
    CHANGELOG_HTML
        .lock()
        .ok()
        .and_then(|g| g.clone())
        .unwrap_or_else(fallback_changelog_html)
}

pub async fn fetch_github_changelog() -> Result<String, String> {
    let prerelease_ok = allows_prereleases();
    let releases = fetch_releases().await?;
    let visible: Vec<_> = releases
        .into_iter()
        .filter(|r| prerelease_ok || !r.prerelease)
        .collect();
    let html = compile_changelog_html(&visible);
    if let Ok(mut cache) = CHANGELOG_HTML.lock() {
        *cache = Some(html.clone());
    }
    Ok(html)
}

pub async fn check_for_updates(notify_no_update: bool) -> UpdateCheckResult {
    info!(
        version = %version(),
        notify_no_update, "checking for updates"
    );
    let Ok(releases) = fetch_releases().await else {
        return update_check_result(
            false,
            None,
            if notify_no_update {
                format!(
                    "Version: {}\n\nCould not retrieve release information.",
                    version_string()
                )
            } else {
                "Could not retrieve release information.".into()
            },
        );
    };
    cache_changelog(&releases);

    let prerelease_ok = allows_prereleases();
    let current = version().clone();

    let visible: Vec<_> = releases
        .into_iter()
        .filter(|r| prerelease_ok || !r.prerelease)
        .filter(|r| r.version.major == current.major)
        .collect();

    let Some(latest) = visible.first() else {
        return update_check_result(
            false,
            None,
            if notify_no_update {
                format!(
                    "Version: {}\n\nCould not retrieve release information.",
                    version_string()
                )
            } else {
                "No releases found.".into()
            },
        );
    };

    if latest.version > current {
        info!(latest = %latest.version, "update available");
        update_check_result(
            true,
            Some(latest.version.to_string()),
            format!(
                "A new update is available.\n\nYour version: {}\nNew version: {}",
                version_string(),
                latest.version
            ),
        )
    } else {
        update_check_result(
            false,
            None,
            if notify_no_update {
                format!(
                    "Version: {}\n\nThere is no update available, you are running the latest version.",
                    version_string()
                )
            } else {
                "You are on the latest version.".into()
            },
        )
    }
}

fn cache_changelog(releases: &[ParsedRelease]) {
    let prerelease_ok = allows_prereleases();
    let visible: Vec<_> = releases
        .iter()
        .filter(|release| prerelease_ok || !release.prerelease)
        .collect();
    let html = compile_changelog_html(visible);
    if let Ok(mut cache) = CHANGELOG_HTML.lock() {
        *cache = Some(html);
    }
}

struct ParsedRelease {
    version: Version,
    body: String,
    prerelease: bool,
    assets: Vec<GitHubAsset>,
}

async fn fetch_releases() -> Result<Vec<ParsedRelease>, String> {
    let client = github_client()?;
    let mut request = client
        .get(GITHUB_RELEASES_URL)
        .header("Accept", "application/vnd.github+json");
    if let Some(auth) = github_auth() {
        request = request.basic_auth(auth.username, Some(auth.key));
    }
    let resp = request
        .send()
        .await
        .map_err(|e| format!("GitHub request failed: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("GitHub API returned {}", resp.status()));
    }
    let raw: Vec<GitHubRelease> = resp.json().await.map_err(|e| e.to_string())?;
    let mut releases = Vec::new();
    for release in raw {
        let version = parse_version(release.tag_name.trim_start_matches('v'))?;
        releases.push(ParsedRelease {
            version,
            body: release.body.unwrap_or_default(),
            prerelease: release.prerelease,
            assets: release.assets,
        });
    }
    releases.sort_by(|a, b| b.version.cmp(&a.version));
    Ok(releases)
}

fn github_client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .user_agent("p99-login-proxy-native")
        .build()
        .map_err(|e| e.to_string())
}

fn github_auth() -> Option<GitHubAuth> {
    let dir = proxy_core::config_file_path()?.parent()?.to_path_buf();
    let raw = std::fs::read_to_string(dir.join("github_auth.json")).ok()?;
    match serde_json::from_str(&raw) {
        Ok(auth) => Some(auth),
        Err(error) => {
            warn!(%error, "invalid github_auth.json; using unauthenticated GitHub requests");
            None
        }
    }
}

fn allows_prereleases() -> bool {
    load_config()
        .map(|file| file.prerelease_updates)
        .unwrap_or(false)
        || !version().pre.is_empty()
}

fn parse_version(raw: &str) -> Result<Version, String> {
    Version::parse(raw).map_err(|e| format!("invalid semver '{raw}': {e}"))
}

fn validate_update_target(
    target: &Version,
    current: &Version,
    target_is_prerelease: bool,
    prereleases_allowed: bool,
) -> Result<(), String> {
    if target.major != current.major {
        return Err(format!(
            "Automatic update from major version {} to {} is not supported",
            current.major, target.major
        ));
    }
    if target <= current {
        return Err(format!(
            "Update target v{target} must be newer than v{current}"
        ));
    }
    if target_is_prerelease && !prereleases_allowed {
        return Err(format!("Prerelease update v{target} is not enabled"));
    }
    Ok(())
}

fn compile_changelog_html<'a>(releases: impl IntoIterator<Item = &'a ParsedRelease>) -> String {
    let mut markdown = String::new();
    for release in releases {
        markdown.push_str(&format!("## v{}\n", release.version));
        let body = release.body.trim();
        if body.is_empty() {
            markdown.push_str(&format!("- Release v{}\n\n", release.version));
            continue;
        }
        for line in body.lines() {
            let line = line.trim();
            if line.is_empty() {
                markdown.push('\n');
                continue;
            }
            if line.starts_with('#') || line.starts_with('-') || line.starts_with('*') {
                markdown.push_str(line);
                markdown.push('\n');
            } else {
                markdown.push_str("- ");
                markdown.push_str(line);
                markdown.push('\n');
            }
        }
        markdown.push('\n');
    }
    markdown_to_html(&markdown)
}

fn markdown_to_html(markdown: &str) -> String {
    let mut options = Options::empty();
    options.insert(Options::ENABLE_STRIKETHROUGH);
    let parser = Parser::new_ext(markdown, options);
    let mut html_out = String::new();
    html::push_html(&mut html_out, parser);
    html_out
}

/// Run the daily local-noon update check. The frontend performs the startup
/// check after registering its listeners so the initial prompt cannot be lost.
pub async fn run_scheduled_checks(app: AppHandle) {
    loop {
        let wait = duration_until_next_noon();
        tokio::time::sleep(wait).await;
        let result = check_for_updates(false).await;
        emit_if_available(&app, &result);
    }
}

pub(crate) fn emit_if_available(app: &AppHandle, result: &UpdateCheckResult) {
    if !result.available {
        return;
    }
    let _ = app.emit(
        "update-available",
        serde_json::json!({
            "version": result.version,
            "message": result.message,
        }),
    );
}

/// In-app modal for manual update checks when no update is available (themed; works with always-on-top).
pub(crate) fn emit_update_check_info(app: &AppHandle, result: &UpdateCheckResult) {
    if result.available {
        return;
    }
    let _ = app.emit(
        "update-check-info",
        serde_json::json!({
            "title": result.title,
            "message": result.message,
        }),
    );
}

#[cfg_attr(not(windows), allow(dead_code))]
const STABLE_EXE_NAME: &str = "P99LoginProxy.exe";

fn expected_update_asset_name(version: &Version) -> String {
    if cfg!(windows) {
        expected_windows_zip_asset_name(version)
    } else if cfg!(target_os = "linux") {
        expected_linux_appimage_asset_name(version)
    } else {
        String::new()
    }
}

#[cfg(test)]
fn select_update_asset(release: &ParsedRelease) -> Option<&GitHubAsset> {
    let expected = expected_update_asset_name(&release.version);
    if expected.is_empty() {
        return None;
    }
    release.assets.iter().find(|asset| asset.name == expected)
}

fn unique_asset<'a>(
    release: &'a ParsedRelease,
    asset_name: &str,
) -> Result<&'a GitHubAsset, String> {
    let mut matches = release
        .assets
        .iter()
        .filter(|asset| asset.name == asset_name);
    let asset = matches.next().ok_or_else(|| {
        format!(
            "Release v{} is missing asset '{asset_name}'",
            release.version
        )
    })?;
    if matches.next().is_some() {
        return Err(format!(
            "Release v{} contains duplicate assets named '{asset_name}'",
            release.version
        ));
    }
    Ok(asset)
}

async fn download_release_asset(
    app: Option<&AppHandle>,
    asset: &GitHubAsset,
) -> Result<Vec<u8>, String> {
    let client = github_client()?;
    let mut request = client.get(&asset.browser_download_url);
    if let Some(auth) = github_auth() {
        request = request.basic_auth(auth.username, Some(auth.key));
    }
    let response = request
        .send()
        .await
        .map_err(|error| format!("Update download failed: {error}"))?;
    if !response.status().is_success() {
        return Err(format!("Update download returned {}", response.status()));
    }
    let total = response.content_length();
    let mut stream = response.bytes_stream();
    let mut bytes = Vec::with_capacity(total.unwrap_or(0) as usize);
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|error| format!("Update download failed: {error}"))?;
        bytes.extend_from_slice(&chunk);
        if let Some(app) = app {
            let _ = app.emit(
                "update-progress",
                serde_json::json!({"downloaded": bytes.len(), "total": total}),
            );
        }
    }
    Ok(bytes)
}

fn verify_sha256(manifest: &str, asset_name: &str, bytes: &[u8]) -> Result<(), String> {
    let mut entries = HashMap::new();
    for line in manifest.lines() {
        if line.trim().is_empty() {
            continue;
        }
        let mut fields = line.split_whitespace();
        let hash = fields
            .next()
            .ok_or_else(|| format!("{CHECKSUM_ASSET_NAME} contains a malformed line"))?;
        let name = fields
            .next()
            .map(|name| name.trim_start_matches('*'))
            .ok_or_else(|| format!("{CHECKSUM_ASSET_NAME} contains a malformed line"))?;
        if fields.next().is_some()
            || name.is_empty()
            || name == "."
            || name == ".."
            || name.contains('/')
            || name.contains('\\')
        {
            return Err(format!(
                "{CHECKSUM_ASSET_NAME} contains an unsafe asset name"
            ));
        }
        if hash.len() != 64 || !hash.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(format!(
                "{CHECKSUM_ASSET_NAME} contains an invalid SHA-256 for '{name}'"
            ));
        }
        if entries.insert(name, hash).is_some() {
            return Err(format!(
                "{CHECKSUM_ASSET_NAME} contains duplicate entries for '{name}'"
            ));
        }
    }
    let expected = entries
        .get(asset_name)
        .ok_or_else(|| format!("{CHECKSUM_ASSET_NAME} is missing '{asset_name}'"))?;
    let actual = sha256_hex(bytes);
    if !actual.eq_ignore_ascii_case(expected) {
        return Err(format!("SHA-256 verification failed for '{asset_name}'"));
    }
    Ok(())
}

fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .fold(String::with_capacity(64), |mut output, byte| {
            let _ = write!(output, "{byte:02x}");
            output
        })
}

/// Download the selected release and replace the portable executable.
///
/// Returns the path to launch after the caller has shut down the proxy.
pub async fn install_update(app: &AppHandle, target_version_raw: &str) -> Result<PathBuf, String> {
    let target = parse_version(target_version_raw)?;
    let current = version();
    let releases = fetch_releases().await?;
    let release = releases
        .iter()
        .find(|release| release.version == target)
        .ok_or_else(|| format!("GitHub release v{target} was not found"))?;
    validate_update_target(&target, current, release.prerelease, allows_prereleases())?;
    let expected = expected_update_asset_name(&target);
    let asset = unique_asset(release, &expected)?;
    let checksum_asset = unique_asset(release, CHECKSUM_ASSET_NAME)?;

    let bytes = download_release_asset(Some(app), asset).await?;
    let checksum_bytes = download_release_asset(None, checksum_asset).await?;
    let checksum_manifest = std::str::from_utf8(&checksum_bytes)
        .map_err(|_| format!("{CHECKSUM_ASSET_NAME} is not valid UTF-8"))?;
    verify_sha256(checksum_manifest, &asset.name, &bytes)?;

    #[cfg(windows)]
    {
        replace_portable_executable(&bytes, &target)
    }
    #[cfg(target_os = "linux")]
    {
        replace_appimage(&bytes)
    }
    #[cfg(not(any(windows, target_os = "linux")))]
    {
        let _ = bytes;
        Err("Automatic updates are not supported on this platform.".into())
    }
}

#[cfg(windows)]
fn replace_portable_executable(
    zip_bytes: &[u8],
    target_version: &Version,
) -> Result<PathBuf, String> {
    let current_exe = std::env::current_exe().map_err(|error| error.to_string())?;
    let current_name = current_exe
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default();
    let current = version();
    let is_stable_name = current_name.eq_ignore_ascii_case(STABLE_EXE_NAME);
    if !is_stable_name && !is_versioned_portable_name(current_name, current) {
        return Err("Automatic update requires the portable P99LoginProxy.exe build.".to_string());
    }
    let expected_member = format!("P99LoginProxy-{target_version}.exe");
    let executable_bytes = validated_zip_executable(zip_bytes, &expected_member)?;
    let exe_dir = current_exe
        .parent()
        .ok_or_else(|| "Current executable has no parent directory".to_string())?;
    let partial = exe_dir.join(".P99LoginProxy-update.partial.exe");
    if partial.exists() {
        std::fs::remove_file(&partial).map_err(|error| error.to_string())?;
    }
    write_update_executable(&partial, &executable_bytes)?;

    if !is_stable_name {
        let stable_exe = exe_dir.join(STABLE_EXE_NAME);
        let displaced = exe_dir.join(".P99LoginProxy-existing.exe.bak");
        if displaced.exists() {
            std::fs::remove_file(&displaced).map_err(|error| error.to_string())?;
        }
        if stable_exe.exists() {
            std::fs::rename(&stable_exe, &displaced).map_err(|error| {
                format!("Failed to back up existing P99LoginProxy.exe: {error}")
            })?;
        }
        if let Err(error) = std::fs::rename(&partial, &stable_exe) {
            if displaced.exists() {
                let _ = std::fs::rename(&displaced, &stable_exe);
            }
            let _ = std::fs::remove_file(&partial);
            return Err(format!("Could not install update executable: {error}"));
        }
        return Ok(stable_exe);
    }

    let backup = exe_dir.join(format!("P99LoginProxy-{}.exe", version_string()));
    if backup.exists() {
        std::fs::remove_file(&backup).map_err(|error| error.to_string())?;
    }
    std::fs::rename(&current_exe, &backup)
        .map_err(|error| format!("Failed to back up current executable: {error}"))?;

    if let Err(error) = std::fs::rename(&partial, &current_exe) {
        let _ = std::fs::rename(&backup, &current_exe);
        let _ = std::fs::remove_file(&partial);
        return Err(format!("Could not install update executable: {error}"));
    }
    Ok(current_exe)
}

#[cfg(any(windows, test))]
fn is_versioned_portable_name(name: &str, current_version: &Version) -> bool {
    name.eq_ignore_ascii_case(&format!("P99LoginProxy-{current_version}.exe"))
}

#[cfg(any(windows, test))]
fn write_update_executable(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut file = File::create(path)
        .map_err(|error| format!("Could not write update executable: {error}"))?;
    file.write_all(bytes)
        .map_err(|error| format!("Could not write update executable: {error}"))?;
    file.sync_all()
        .map_err(|error| format!("Could not flush update executable: {error}"))
}

#[cfg(target_os = "linux")]
fn replace_appimage(bytes: &[u8]) -> Result<PathBuf, String> {
    let appimage_path = std::env::var("APPIMAGE").map_err(|_| {
        "Automatic updates require launching the AppImage. Download the latest AppImage from GitHub instead.".to_string()
    })?;
    let target = PathBuf::from(&appimage_path);
    let parent = target
        .parent()
        .ok_or_else(|| "AppImage path has no parent directory".to_string())?;
    if !is_directory_writable(parent)? {
        return Err(format!(
            "Cannot update AppImage in {} because the directory is not writable.",
            parent.display()
        ));
    }

    let partial = parent.join(format!(
        ".P99LoginProxy-{}-x86_64.AppImage.partial",
        version_string()
    ));
    let backup = parent.join(format!(
        "P99LoginProxy-{}-x86_64.AppImage.bak",
        version_string()
    ));
    if partial.exists() {
        std::fs::remove_file(&partial).map_err(|error| error.to_string())?;
    }
    std::fs::write(&partial, bytes)
        .map_err(|error| format!("Could not write downloaded AppImage: {error}"))?;
    set_executable(&partial)?;

    if backup.exists() {
        std::fs::remove_file(&backup).map_err(|error| error.to_string())?;
    }
    if target.exists() {
        std::fs::rename(&target, &backup)
            .map_err(|error| format!("Failed to back up current AppImage: {error}"))?;
    }

    if let Err(error) = std::fs::rename(&partial, &target) {
        if backup.exists() && !target.exists() {
            let _ = std::fs::rename(&backup, &target);
        }
        return Err(format!("Could not install downloaded AppImage: {error}"));
    }
    Ok(target)
}

#[cfg(target_os = "linux")]
fn set_executable(path: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;

    let mut perms = std::fs::metadata(path)
        .map_err(|error| error.to_string())?
        .permissions();
    perms.set_mode(0o755);
    std::fs::set_permissions(path, perms).map_err(|error| error.to_string())
}

#[cfg(target_os = "linux")]
fn is_directory_writable(path: &Path) -> Result<bool, String> {
    let probe = path.join(format!(".p99-write-test-{}", std::process::id()));
    match std::fs::File::create(&probe) {
        Ok(_) => {
            let _ = std::fs::remove_file(probe);
            Ok(true)
        }
        Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => Ok(false),
        Err(error) => Err(format!(
            "Could not verify write access to {}: {error}",
            path.display()
        )),
    }
}

#[cfg(any(windows, test))]
fn validated_zip_executable(zip_bytes: &[u8], expected_member: &str) -> Result<Vec<u8>, String> {
    let mut archive = zip::ZipArchive::new(Cursor::new(zip_bytes))
        .map_err(|error| format!("Invalid update zip: {error}"))?;
    if archive.len() != 1 {
        return Err(format!(
            "Update zip must contain exactly one file; found {} entries",
            archive.len()
        ));
    }
    let mut member = archive
        .by_index(0)
        .map_err(|error| format!("Update zip is empty: {error}"))?;
    let enclosed = member
        .enclosed_name()
        .ok_or_else(|| "Update zip contains an unsafe path".to_string())?;
    if member.is_dir() {
        return Err("The update zip member is not an executable".to_string());
    }
    if enclosed.components().count() != 1
        || enclosed.file_name().and_then(|name| name.to_str()) != Some(expected_member)
    {
        return Err(format!(
            "Update zip must contain only the top-level file '{expected_member}'"
        ));
    }
    let mut bytes = Vec::new();
    member
        .read_to_end(&mut bytes)
        .map_err(|error| format!("Could not read update zip: {error}"))?;
    if bytes.is_empty() {
        return Err("Update executable is empty".to_string());
    }
    Ok(bytes)
}

fn duration_until_next_noon() -> Duration {
    let now = Local::now();
    let noon = NaiveTime::from_hms_opt(12, 0, 0).expect("valid noon time");
    let today_noon = Local
        .from_local_datetime(&now.date_naive().and_time(noon))
        .single();
    let target = match today_noon {
        Some(t) if t > now => t,
        _ => Local
            .from_local_datetime(&(now.date_naive() + chrono::Duration::days(1)).and_time(noon))
            .single()
            .unwrap_or_else(|| now + chrono::Duration::days(1)),
    };
    (target - now)
        .to_std()
        .unwrap_or_else(|_| Duration::from_secs(24 * 60 * 60))
}

fn fallback_changelog_html() -> String {
    "<p>Changelog unavailable. Release notes are published on GitHub.</p>".to_string()
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use super::*;

    #[test]
    #[cfg(windows)]
    fn selects_exact_windows_zip_asset() {
        let release = ParsedRelease {
            version: Version::parse("2.0.1").unwrap(),
            body: String::new(),
            prerelease: false,
            assets: vec![
                GitHubAsset {
                    name: "P99LoginProxy-2.0.1-x86_64.AppImage".to_string(),
                    browser_download_url: "appimage".to_string(),
                },
                GitHubAsset {
                    name: "P99LoginProxy-2.0.1.zip".to_string(),
                    browser_download_url: "zip".to_string(),
                },
            ],
        };
        assert_eq!(
            select_update_asset(&release).map(|asset| asset.browser_download_url.as_str()),
            Some("zip")
        );
    }

    #[test]
    #[cfg(target_os = "linux")]
    fn selects_exact_linux_appimage_asset() {
        let release = ParsedRelease {
            version: Version::parse("2.0.1").unwrap(),
            body: String::new(),
            prerelease: false,
            assets: vec![
                GitHubAsset {
                    name: "P99LoginProxy-2.0.1.zip".to_string(),
                    browser_download_url: "zip".to_string(),
                },
                GitHubAsset {
                    name: "P99LoginProxy-2.0.1-x86_64.AppImage".to_string(),
                    browser_download_url: "appimage".to_string(),
                },
            ],
        };
        assert_eq!(
            select_update_asset(&release).map(|asset| asset.browser_download_url.as_str()),
            Some("appimage")
        );
    }

    #[test]
    fn ignores_misleading_zip_like_assets_without_exact_name() {
        let release = ParsedRelease {
            version: Version::parse("2.0.1").unwrap(),
            body: String::new(),
            prerelease: false,
            assets: vec![GitHubAsset {
                name: "other.zip".to_string(),
                browser_download_url: "wrong".to_string(),
            }],
        };
        assert!(select_update_asset(&release).is_none());
    }

    #[test]
    fn extracts_exact_member_to_stable_name() {
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        zip.start_file(
            "P99LoginProxy-2.0.1.exe",
            zip::write::SimpleFileOptions::default(),
        )
        .unwrap();
        zip.write_all(b"portable exe").unwrap();
        let archive = zip.finish().unwrap().into_inner();
        let bytes = validated_zip_executable(&archive, "P99LoginProxy-2.0.1.exe").unwrap();
        assert_eq!(bytes, b"portable exe");
    }

    #[test]
    fn accepts_only_the_current_versioned_portable_name() {
        let current = Version::parse("2.0.0-rc7").unwrap();
        assert!(is_versioned_portable_name(
            "P99LoginProxy-2.0.0-rc7.exe",
            &current
        ));
        assert!(!is_versioned_portable_name("P99LoginProxy.exe", &current));
        assert!(!is_versioned_portable_name(
            "P99LoginProxy-2.0.0-rc6.exe",
            &current
        ));
    }

    #[test]
    fn writes_and_flushes_update_with_writable_handle() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join(".P99LoginProxy-update.partial.exe");

        write_update_executable(&path, b"replacement").unwrap();

        assert_eq!(std::fs::read(path).unwrap(), b"replacement");
    }

    #[test]
    fn rejects_unsafe_first_member() {
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        zip.start_file("../escape.exe", zip::write::SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"bad").unwrap();
        let archive = zip.finish().unwrap().into_inner();
        assert!(validated_zip_executable(&archive, "P99LoginProxy-2.0.1.exe").is_err());
    }

    #[test]
    fn rejects_update_zip_with_extra_members() {
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        let options = zip::write::SimpleFileOptions::default();
        zip.start_file("P99LoginProxy-2.0.1.exe", options).unwrap();
        zip.write_all(b"portable exe").unwrap();
        zip.start_file("unexpected.txt", options).unwrap();
        zip.write_all(b"extra").unwrap();
        let archive = zip.finish().unwrap().into_inner();
        assert!(validated_zip_executable(&archive, "P99LoginProxy-2.0.1.exe").is_err());
    }

    #[test]
    fn verifies_named_sha256_entry() {
        let bytes = b"release artifact";
        let hash = sha256_hex(bytes);
        let manifest = format!("{hash}  P99LoginProxy-2.0.1.zip\n");
        assert!(verify_sha256(&manifest, "P99LoginProxy-2.0.1.zip", bytes).is_ok());
        assert!(verify_sha256(&manifest, "P99LoginProxy-2.0.1.zip", b"tampered").is_err());
        assert!(verify_sha256(&manifest, "other.zip", bytes).is_err());
    }

    #[test]
    fn rejects_unsafe_or_duplicate_checksum_entries() {
        let hash = sha256_hex(b"release artifact");
        assert!(verify_sha256(
            &format!("{hash}  ../P99LoginProxy.zip\n"),
            "P99LoginProxy.zip",
            b"release artifact"
        )
        .is_err());
        assert!(verify_sha256(
            &format!("{hash}  other.zip\n{hash}  other.zip\n"),
            "other.zip",
            b"release artifact"
        )
        .is_err());
        assert!(verify_sha256(
            &format!("{hash}  other.zip unexpected\n"),
            "other.zip",
            b"release artifact"
        )
        .is_err());
    }

    #[test]
    fn update_target_must_be_newer_same_major_and_allowed() {
        let current = Version::parse("2.0.0").unwrap();
        assert!(
            validate_update_target(&Version::parse("2.0.1").unwrap(), &current, false, false)
                .is_ok()
        );
        assert!(
            validate_update_target(&Version::parse("3.0.0").unwrap(), &current, false, true)
                .is_err()
        );
        assert!(
            validate_update_target(&Version::parse("2.0.0").unwrap(), &current, false, true)
                .is_err()
        );
        assert!(validate_update_target(
            &Version::parse("2.1.0-rc1").unwrap(),
            &current,
            true,
            false
        )
        .is_err());
    }

    #[test]
    fn parses_update_wait_lock_argument() {
        let args = [
            std::ffi::OsString::from("P99LoginProxy.exe"),
            std::ffi::OsString::from(WAIT_FOR_UPDATE_LOCK_ARG),
            std::ffi::OsString::from("C:\\Temp\\update.lock"),
        ];
        assert_eq!(
            update_lock_path_from_args(args).unwrap(),
            Some(PathBuf::from("C:\\Temp\\update.lock"))
        );
        assert!(update_lock_path_from_args([
            std::ffi::OsString::from("P99LoginProxy.exe"),
            std::ffi::OsString::from(WAIT_FOR_UPDATE_LOCK_ARG),
        ])
        .is_err());
    }

    #[test]
    fn would_block_is_update_lock_contention() {
        let error = std::io::Error::from(ErrorKind::WouldBlock);
        assert!(is_update_lock_contention(&error));
    }

    #[test]
    #[cfg(windows)]
    fn windows_file_lock_errors_are_update_contention() {
        assert!(is_update_lock_contention(
            &std::io::Error::from_raw_os_error(32)
        ));
        assert!(is_update_lock_contention(
            &std::io::Error::from_raw_os_error(33)
        ));
    }

    #[test]
    #[cfg(target_os = "linux")]
    fn replaces_appimage_with_backup_and_executable_mode() {
        use std::os::unix::fs::PermissionsExt;

        let dir = tempfile::tempdir().unwrap();
        let appimage = dir.path().join("P99LoginProxy.AppImage");
        std::fs::write(&appimage, b"old").unwrap();
        std::env::set_var("APPIMAGE", &appimage);

        let launch = replace_appimage(b"new").unwrap();
        assert_eq!(launch, appimage);
        assert_eq!(std::fs::read(&appimage).unwrap(), b"new");
        let mode = std::fs::metadata(&appimage).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o755);
        let backup = dir.path().join(format!(
            "P99LoginProxy-{}-x86_64.AppImage.bak",
            version_string()
        ));
        assert_eq!(std::fs::read(backup).unwrap(), b"old");
    }
}
