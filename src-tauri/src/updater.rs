use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;

use chrono::{Local, NaiveTime, TimeZone};
use futures_util::StreamExt;
use proxy_core::load_config;
use pulldown_cmark::{html, Options, Parser};
use semver::Version;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter};
use tracing::{info, warn};

const GITHUB_RELEASES_URL: &str =
    "https://api.github.com/repos/eq-p99-tools/p99-login-proxy/releases?per_page=10";
const APP_VERSION: &str = env!("CARGO_PKG_VERSION");

static CHANGELOG_HTML: Mutex<Option<String>> = Mutex::new(None);

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
    content_type: String,
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
        version = APP_VERSION,
        notify_no_update, "checking for updates"
    );
    let changelog_result = fetch_github_changelog().await;
    if let Err(ref e) = changelog_result {
        warn!(error = %e, "failed to fetch changelog during update check");
    }

    let Ok(releases) = fetch_releases().await else {
        return update_check_result(
            false,
            None,
            if notify_no_update {
                format!("Version: {APP_VERSION}\n\nCould not retrieve release information.")
            } else {
                "Could not retrieve release information.".into()
            },
        );
    };

    let prerelease_ok = allows_prereleases();
    let current = match parse_version(APP_VERSION) {
        Ok(v) => v,
        Err(e) => {
            return update_check_result(
                false,
                None,
                format!("Invalid app version: {e}"),
            );
        }
    };

    let visible: Vec<_> = releases
        .into_iter()
        .filter(|r| prerelease_ok || !r.prerelease)
        .collect();

    let Some(latest) = visible.first() else {
        return update_check_result(
            false,
            None,
            if notify_no_update {
                format!("Version: {APP_VERSION}\n\nCould not retrieve release information.")
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
                "A new update is available.\n\nYour version: {APP_VERSION}\nNew version: {}",
                latest.version
            ),
        )
    } else {
        update_check_result(
            false,
            None,
            if notify_no_update {
                format!(
                    "Version: {APP_VERSION}\n\nThere is no update available, you are running the latest version."
                )
            } else {
                "You are on the latest version.".into()
            },
        )
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
        || parse_version(APP_VERSION).is_ok_and(|version| !version.pre.is_empty())
}

fn parse_version(raw: &str) -> Result<Version, String> {
    Version::parse(raw).map_err(|e| format!("invalid semver '{raw}': {e}"))
}

fn compile_changelog_html(releases: &[ParsedRelease]) -> String {
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

/// Run the silent startup update check, then a daily check at local noon
/// (parity with the Python APScheduler 12:00 cron job).
pub async fn run_startup_and_scheduled_checks(app: AppHandle) {
    let result = check_for_updates(false).await;
    emit_if_available(&app, &result);

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

const ZIP_CONTENT_TYPES: &[&str] = &[
    "application/x-zip-compressed",
    "application/zip",
    "application/octet-stream",
];
const STABLE_EXE_NAME: &str = "P99LoginProxy.exe";

fn select_zip_asset(release: &ParsedRelease) -> Option<&GitHubAsset> {
    release.assets.iter().find(|asset| {
        ZIP_CONTENT_TYPES.contains(&asset.content_type.as_str())
            || asset.name.to_ascii_lowercase().ends_with(".zip")
    })
}

/// Download the selected release and replace the portable executable.
///
/// Returns the path to launch after the caller has shut down the proxy.
#[cfg(windows)]
pub async fn install_update(app: &AppHandle, version: &str) -> Result<PathBuf, String> {
    let target = parse_version(version)?;
    let releases = fetch_releases().await?;
    let release = releases
        .iter()
        .find(|release| release.version == target)
        .ok_or_else(|| format!("GitHub release v{target} was not found"))?;
    let asset =
        select_zip_asset(release).ok_or_else(|| format!("Release v{target} has no zip asset"))?;

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
        let _ = app.emit(
            "update-progress",
            serde_json::json!({"downloaded": bytes.len(), "total": total}),
        );
    }

    replace_portable_executable(&bytes)
}

#[cfg(not(windows))]
pub async fn install_update(_app: &AppHandle, _version: &str) -> Result<PathBuf, String> {
    Err("Automatic updates are only supported by the portable Windows build.".to_string())
}

#[cfg(windows)]
fn replace_portable_executable(zip_bytes: &[u8]) -> Result<PathBuf, String> {
    let current_exe = std::env::current_exe().map_err(|error| error.to_string())?;
    let current_name = current_exe
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default();
    if !current_name.eq_ignore_ascii_case(STABLE_EXE_NAME) {
        return Err("Automatic update requires the portable P99LoginProxy.exe build.".to_string());
    }
    let exe_dir = current_exe
        .parent()
        .ok_or_else(|| "Current executable has no parent directory".to_string())?;
    let backup = exe_dir.join(format!("P99LoginProxy-{APP_VERSION}.exe"));
    if backup.exists() {
        std::fs::remove_file(&backup).map_err(|error| error.to_string())?;
    }
    std::fs::rename(&current_exe, &backup)
        .map_err(|error| format!("Failed to back up current executable: {error}"))?;

    let result = extract_first_zip_member(zip_bytes, exe_dir);
    if let Err(error) = result {
        let _ = std::fs::rename(&backup, &current_exe);
        return Err(error);
    }
    Ok(current_exe)
}

fn extract_first_zip_member(zip_bytes: &[u8], destination: &Path) -> Result<PathBuf, String> {
    let mut archive = zip::ZipArchive::new(Cursor::new(zip_bytes))
        .map_err(|error| format!("Invalid update zip: {error}"))?;
    let mut member = archive
        .by_index(0)
        .map_err(|error| format!("Update zip is empty: {error}"))?;
    let enclosed = member
        .enclosed_name()
        .ok_or_else(|| "Update zip contains an unsafe path".to_string())?;
    if member.is_dir() {
        return Err("The first update zip member is not an executable".to_string());
    }
    let extracted = destination.join(enclosed);
    if let Some(parent) = extracted.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let mut bytes = Vec::new();
    member
        .read_to_end(&mut bytes)
        .map_err(|error| format!("Could not read update zip: {error}"))?;
    std::fs::write(&extracted, bytes)
        .map_err(|error| format!("Could not extract update: {error}"))?;

    let stable = destination.join(STABLE_EXE_NAME);
    if extracted != stable {
        if stable.exists() {
            std::fs::remove_file(&stable).map_err(|error| error.to_string())?;
        }
        std::fs::rename(&extracted, &stable)
            .map_err(|error| format!("Could not rename update executable: {error}"))?;
    }
    Ok(stable)
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
    fn selects_first_zip_like_asset() {
        let release = ParsedRelease {
            version: Version::new(2, 0, 1),
            body: String::new(),
            prerelease: false,
            assets: vec![
                GitHubAsset {
                    name: "notes.txt".to_string(),
                    content_type: "text/plain".to_string(),
                    browser_download_url: "notes".to_string(),
                },
                GitHubAsset {
                    name: "P99LoginProxy-2.0.1.zip".to_string(),
                    content_type: "application/octet-stream".to_string(),
                    browser_download_url: "first".to_string(),
                },
                GitHubAsset {
                    name: "other.zip".to_string(),
                    content_type: "application/zip".to_string(),
                    browser_download_url: "second".to_string(),
                },
            ],
        };
        assert_eq!(
            select_zip_asset(&release).map(|asset| asset.browser_download_url.as_str()),
            Some("first")
        );
    }

    #[test]
    fn extracts_first_member_to_stable_name() {
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        zip.start_file(
            "P99LoginProxy-2.0.1.exe",
            zip::write::SimpleFileOptions::default(),
        )
        .unwrap();
        zip.write_all(b"portable exe").unwrap();
        let archive = zip.finish().unwrap().into_inner();
        let dir = tempfile::tempdir().unwrap();

        let path = extract_first_zip_member(&archive, dir.path()).unwrap();
        assert_eq!(path, dir.path().join(STABLE_EXE_NAME));
        assert_eq!(std::fs::read(path).unwrap(), b"portable exe");
    }

    #[test]
    fn rejects_unsafe_first_member() {
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        zip.start_file("../escape.exe", zip::write::SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"bad").unwrap();
        let archive = zip.finish().unwrap().into_inner();
        let dir = tempfile::tempdir().unwrap();
        assert!(extract_first_zip_member(&archive, dir.path()).is_err());
    }
}
