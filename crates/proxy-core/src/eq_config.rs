use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use tracing::{debug, info, warn};

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

#[cfg(unix)]
fn try_clear_readonly(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    if let Ok(meta) = std::fs::metadata(path) {
        let mut perms = meta.permissions();
        perms.set_mode(perms.mode() | 0o200);
        let _ = std::fs::set_permissions(path, perms);
    }
}

#[cfg(windows)]
fn try_clear_readonly(path: &Path) {
    let _ = std::process::Command::new("attrib")
        .args(["-R", &path.display().to_string()])
        .status();
}

#[cfg(not(any(unix, windows)))]
fn try_clear_readonly(_path: &Path) {}

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
                warn!(dir = %path.display(), "Rustle UI detected in {}", path.display());
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
}
