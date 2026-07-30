use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use tracing::{debug, info, warn};

use crate::eqhost::EqHostWriter;

const RUSTLE_MARKERS: &[&str] = &[
    "iw_bag1_slot9",
    "iw_bag1_slot10",
    "iw_bag2_slot9",
    "iw_bag2_slot10",
    "iw_bag3_slot9",
    "iw_bag3_slot10",
    "iw_bag4_slot9",
    "iw_bag4_slot10",
    "iw_bag5_slot9",
    "iw_bag5_slot10",
    "iw_bag6_slot9",
    "iw_bag6_slot10",
    "iw_bag7_slot9",
    "iw_bag7_slot10",
    "iw_bag8_slot9",
    "iw_bag8_slot10",
];

const DEFAULT_EQ_PATHS: &[&str] = &[
    r"Program Files (x86)\EverQuest",
    r"Program Files\EverQuest",
    r"EverQuest",
    r"Games\EverQuest",
    r"Program Files (x86)\Sony\EverQuest",
    r"Program Files\Sony\EverQuest",
];

/// True when *path* contains ``eqgame.exe`` (Python ``is_valid_eq_directory``).
pub fn is_valid_eq_directory(path: &Path) -> bool {
    path.is_dir() && path.join("eqgame.exe").is_file()
}

#[cfg(windows)]
fn available_drives() -> Vec<PathBuf> {
    (b'A'..=b'Z')
        .filter_map(|letter| {
            let drive = format!("{}:\\", letter as char);
            PathBuf::from(&drive)
                .exists()
                .then_some(PathBuf::from(drive))
        })
        .collect()
}

#[cfg(not(windows))]
fn available_drives() -> Vec<PathBuf> {
    Vec::new()
}

/// Locate EverQuest using legacy v1 heuristics (configured override, CWD, default paths).
pub fn find_eq_directory(configured: Option<&str>) -> Option<PathBuf> {
    if let Some(dir) = configured.filter(|value| !value.trim().is_empty()) {
        let path = PathBuf::from(dir);
        if is_valid_eq_directory(&path) {
            return Some(path);
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        if is_valid_eq_directory(&cwd) {
            info!(path = %cwd.display(), "found EverQuest in the current directory");
            return Some(cwd);
        }
    }

    for drive in available_drives() {
        for subpath in DEFAULT_EQ_PATHS {
            let candidate = drive.join(subpath);
            if is_valid_eq_directory(&candidate) {
                info!(path = %candidate.display(), "found EverQuest in a default install path");
                return Some(candidate);
            }
        }
    }

    #[cfg(not(windows))]
    {
        for candidate in find_wine_eq_directories() {
            if is_valid_eq_directory(&candidate) {
                info!(path = %candidate.display(), "found EverQuest in a Wine/Proton prefix");
                return Some(candidate);
            }
        }
    }

    None
}

#[cfg(not(windows))]
fn find_wine_eq_directories() -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    let home = directories::BaseDirs::new()
        .map(|dirs| dirs.home_dir().to_path_buf())
        .unwrap_or_else(|| PathBuf::from("/"));

    let mut wine_prefixes = vec![home.join(".wine")];
    if let Ok(prefix) = std::env::var("WINEPREFIX") {
        if !prefix.trim().is_empty() {
            wine_prefixes.push(PathBuf::from(prefix));
        }
    }

    let lutris_dir = home.join("Games");
    if lutris_dir.is_dir() {
        if let Ok(entries) = std::fs::read_dir(&lutris_dir) {
            for entry in entries.flatten() {
                if entry.path().is_dir() {
                    wine_prefixes.push(entry.path());
                }
            }
        }
    }

    for prefix in wine_prefixes {
        if !prefix.is_dir() {
            continue;
        }
        let drive_c = prefix.join("drive_c");
        if !drive_c.is_dir() {
            continue;
        }
        for subpath in DEFAULT_EQ_PATHS {
            candidates.push(drive_c.join(subpath));
        }
    }

    candidates
}

/// When ``eq_directory`` is blank, discover EQ, persist it, and return the path.
pub fn discover_and_persist_eq_directory(
    file: &mut crate::config::ConfigFileV1,
    config_path: &Path,
) -> Option<PathBuf> {
    if file
        .eq_directory
        .as_ref()
        .is_some_and(|value| !value.trim().is_empty())
    {
        return file.eq_directory.as_ref().map(PathBuf::from);
    }

    let discovered = find_eq_directory(None)?;
    let path_str = discovered.to_string_lossy().into_owned();
    file.eq_directory = Some(path_str.clone());
    if let Err(error) = crate::proxyconfig_ini::write_proxyconfig_ini(config_path, file) {
        warn!(%error, path = %config_path.display(), "could not persist discovered EverQuest directory");
    } else {
        info!(eq_directory = %path_str, "discovered and persisted EverQuest directory");
    }
    Some(discovered)
}

/// Read ``Log=`` from ``eqclient.ini`` under *eq_dir* (Python ``read_eqclient_log_enabled``).
pub fn read_eqclient_log_enabled(eq_dir: &Path) -> Option<bool> {
    let path = eq_dir.join("eqclient.ini");
    if !path.is_file() {
        return None;
    }
    let raw = std::fs::read_to_string(&path).ok()?;
    parse_eqclient_log(&raw)
}

fn parse_eqclient_log(raw: &str) -> Option<bool> {
    let mut in_defaults = false;
    for line in raw.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            let section = trimmed[1..trimmed.len() - 1].trim().to_lowercase();
            in_defaults = section == "defaults";
            continue;
        }
        if !in_defaults {
            continue;
        }
        let Some((key, value)) = trimmed.split_once('=') else {
            continue;
        };
        if key.trim().eq_ignore_ascii_case("log") {
            return Some(value.trim().eq_ignore_ascii_case("true"));
        }
    }
    None
}

/// EQ folder readiness for the Proxy tab badge (eqhost proxy line + eqclient logging).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EqConfigStatus {
    pub eqhost_proxy_enabled: bool,
    pub eqclient_log_enabled: bool,
}

impl EqConfigStatus {
    pub fn evaluate(eq_dir: &Path, listen_host: &str, listen_port: u16) -> Self {
        Self {
            eqhost_proxy_enabled: EqHostWriter::is_proxy_enabled_in_directory(
                eq_dir,
                listen_host,
                listen_port,
            ),
            eqclient_log_enabled: read_eqclient_log_enabled(eq_dir) == Some(true),
        }
    }

    pub fn enabled(&self) -> bool {
        self.eqhost_proxy_enabled && self.eqclient_log_enabled
    }
}

/// Ensure ``Log=TRUE`` is set in ``eqclient.ini`` (Python ``ensure_eqclient_log_enabled``).
pub fn ensure_eqclient_log_enabled(eq_dir: &Path) -> bool {
    let path = eq_dir.join("eqclient.ini");
    if !path.is_file() {
        return false;
    }

    let content = match std::fs::read_to_string(&path) {
        Ok(c) => c,
        Err(e) => {
            debug!(path = %path.display(), error = %e, "could not read eqclient.ini");
            return false;
        }
    };

    let new_content = enable_log_in_defaults(&content);

    if new_content == content {
        return true;
    }

    try_clear_readonly(eq_dir);
    try_clear_readonly(&path);

    let backup_path = path.with_extension("ini.bak");
    if std::fs::copy(&path, &backup_path).is_err() {
        debug!(path = %path.display(), "could not back up eqclient.ini");
        return false;
    }
    info!(backup = %backup_path.display(), "backed up eqclient.ini");

    match std::fs::write(&path, &new_content) {
        Ok(()) => {
            let enabled = read_eqclient_log_enabled(eq_dir) == Some(true);
            if enabled {
                info!(path = %path.display(), "set Log=TRUE in eqclient.ini");
            } else {
                warn!(path = %path.display(), "eqclient.ini write completed but Log=TRUE was not detected");
            }
            enabled
        }
        Err(e) => {
            warn!(path = %path.display(), error = %e, "could not write eqclient.ini");
            false
        }
    }
}

fn enable_log_in_defaults(content: &str) -> String {
    let newline = if content.contains("\r\n") {
        "\r\n"
    } else {
        "\n"
    };
    let mut lines: Vec<String> = content.lines().map(str::to_string).collect();
    let defaults_index = lines
        .iter()
        .position(|line| line.trim().eq_ignore_ascii_case("[defaults]"));

    let Some(defaults_index) = defaults_index else {
        let body = content
            .trim_start_matches('\u{feff}')
            .trim_start_matches(['\r', '\n']);
        return format!("[Defaults]{newline}Log=TRUE{newline}{body}");
    };

    let section_end = lines
        .iter()
        .enumerate()
        .skip(defaults_index + 1)
        .find(|(_, line)| {
            let trimmed = line.trim();
            trimmed.starts_with('[') && trimmed.ends_with(']')
        })
        .map(|(index, _)| index)
        .unwrap_or(lines.len());

    if let Some(log_index) = (defaults_index + 1..section_end).find(|index| {
        lines[*index]
            .split_once('=')
            .is_some_and(|(key, _)| key.trim().eq_ignore_ascii_case("log"))
    }) {
        lines[log_index] = "Log=TRUE".to_string();
    } else {
        lines.insert(defaults_index + 1, "Log=TRUE".to_string());
    }

    let mut output = lines.join(newline);
    if content.ends_with('\n') {
        output.push_str(newline);
    }
    output
}

/// Best-effort removal of the read-only flag before writing EQ config files.
pub fn try_clear_readonly(path: &Path) {
    try_clear_readonly_impl(path);
}

#[cfg(unix)]
fn try_clear_readonly_impl(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    if let Ok(meta) = std::fs::metadata(path) {
        let mut perms = meta.permissions();
        perms.set_mode(perms.mode() | 0o200);
        let _ = std::fs::set_permissions(path, perms);
    }
}

#[cfg(windows)]
fn try_clear_readonly_impl(path: &Path) {
    let _ = std::process::Command::new("attrib")
        .args(["-R", &path.display().to_string()])
        .status();
}

#[cfg(not(any(unix, windows)))]
fn try_clear_readonly_impl(_path: &Path) {}

/// Scan ``uifiles/`` under each EQ root for Rustle UI fingerprints.
pub fn detect_rustle_ui(eq_roots: &[PathBuf]) -> bool {
    for root in eq_roots {
        let uifiles = root.join("uifiles");
        if !uifiles.is_dir() {
            continue;
        }
        let Ok(entries) = std::fs::read_dir(&uifiles) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if !path.is_dir() {
                continue;
            }
            if check_dir_for_rustle(&path) {
                warn!(dir = %path.display(), "Rustle UI detected");
                return true;
            }
        }
    }
    false
}

fn check_dir_for_rustle(dir: &Path) -> bool {
    let inv = dir.join("EQUI_Inventory.xml");
    if !inv.is_file() {
        return false;
    }
    let Ok(content) = std::fs::read_to_string(&inv) else {
        return false;
    };
    let lc = content.to_lowercase();
    RUSTLE_MARKERS.iter().any(|m| lc.contains(m))
}

/// Build ``client_settings`` for WebSocket auth (Python ``get_client_settings``).
pub fn get_client_settings(
    eq_roots: &[PathBuf],
    rustle_checked: bool,
    rustle_present: bool,
) -> Value {
    let primary = eq_roots.first();
    let Some(eq_dir) = primary else {
        return json!({});
    };
    let log_enabled = read_eqclient_log_enabled(eq_dir).unwrap_or(false);
    let mut settings = json!({ "log_enabled": log_enabled });
    if rustle_checked {
        settings["rustle_present"] = json!(rustle_present);
    }
    settings
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn parses_log_setting() {
        let dir = TempDir::new().unwrap();
        std::fs::write(
            dir.path().join("eqclient.ini"),
            "[Defaults]\nLog=TRUE\nOther=1\n",
        )
        .unwrap();
        assert_eq!(read_eqclient_log_enabled(dir.path()), Some(true));
    }

    #[test]
    fn enables_log_inside_defaults_without_touching_other_sections() {
        let input = "[Defaults]\r\nSound=TRUE\r\n[KeyMaps]\r\nLog=FALSE\r\n";
        let output = enable_log_in_defaults(input);
        assert_eq!(
            output,
            "[Defaults]\r\nLog=TRUE\r\nSound=TRUE\r\n[KeyMaps]\r\nLog=FALSE\r\n"
        );
        assert_eq!(parse_eqclient_log(&output), Some(true));
    }

    #[test]
    fn repairs_missing_defaults_section() {
        let output = enable_log_in_defaults("Sound=TRUE\n[KeyMaps]\nKey=1\n");
        assert!(output.starts_with("[Defaults]\nLog=TRUE\nSound=TRUE\n"));
        assert_eq!(parse_eqclient_log(&output), Some(true));
    }

    #[test]
    fn eq_config_status_requires_proxy_and_log() {
        let dir = TempDir::new().unwrap();
        let eq_dir = dir.path();
        std::fs::write(eq_dir.join("eqclient.ini"), "[Defaults]\nLog=TRUE\n").unwrap();
        std::fs::write(
            eq_dir.join("eqhost.txt"),
            "[LoginServer]\nHost=localhost:5998\n",
        )
        .unwrap();
        let status = EqConfigStatus::evaluate(eq_dir, "127.0.0.1", 5998);
        assert!(status.eqhost_proxy_enabled);
        assert!(status.eqclient_log_enabled);
        assert!(status.enabled());

        std::fs::write(eq_dir.join("eqclient.ini"), "[Defaults]\nLog=FALSE\n").unwrap();
        let disabled_log = EqConfigStatus::evaluate(eq_dir, "127.0.0.1", 5998);
        assert!(disabled_log.eqhost_proxy_enabled);
        assert!(!disabled_log.eqclient_log_enabled);
        assert!(!disabled_log.enabled());
    }

    #[test]
    fn find_eq_directory_detects_valid_install() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("eqgame.exe"), b"stub").unwrap();
        assert!(find_eq_directory(Some(dir.path().to_str().unwrap())).is_some());
    }
}
