//! Read and write portable ``proxyconfig.ini`` (ConfigParser format).

use std::collections::HashMap;
use std::path::Path;

use crate::config::{ConfigError, ConfigFileV1};
use ini::Ini;

/// Parse ``proxyconfig.ini`` into the native config model.
pub fn parse_proxyconfig_ini(path: &Path) -> Result<ConfigFileV1, ConfigError> {
    let ini = Ini::load_from_file_noescape(path)
        .map_err(|e| ConfigError::Validation(format!("failed to read {}: {e}", path.display())))?;
    let default = ini
        .section(Some("DEFAULT"))
        .or_else(|| Some(ini.general_section()));

    let listen_host = read_raw_default_value(path, "listen_host")
        .or_else(|| optional_str(default, "listen_host"))
        .unwrap_or_else(|| "0.0.0.0".to_string());
    let allow_non_loopback = listen_host == "0.0.0.0";

    let mut sso_backend = read_raw_default_value(path, "sso_api_name")
        .unwrap_or_else(|| get_str(default, "sso_api_name", "Good Guys"));
    sso_backend = normalize_backend_name(&sso_backend);

    let sso_api_url =
        read_raw_default_value(path, "sso_api").or_else(|| optional_str(default, "sso_api"));

    let mut api_tokens = read_raw_api_tokens_section(path);
    if api_tokens.is_empty() {
        if let Some(section) = ini.section(Some("api_tokens")) {
            for (key, value) in section.iter() {
                let name = normalize_backend_name(key);
                if !value.trim().is_empty() {
                    api_tokens.insert(name, value.trim().to_string());
                }
            }
        }
    }
    let legacy = get_str(default, "user_api_token", "");
    if !legacy.is_empty() && !api_tokens.contains_key(&sso_backend) {
        api_tokens.insert(sso_backend.clone(), legacy);
    }
    seed_p99_proxy_legacy_tokens(&mut api_tokens, path, default);

    let mut sso_backends = HashMap::new();
    if let Some(section) = ini.section(Some("sso_backends")) {
        for (key, value) in section.iter() {
            let name = normalize_backend_name(key);
            if !value.trim().is_empty() {
                sso_backends.insert(name, value.trim().to_string());
            }
        }
    }

    // rust-ini treats backslashes as escapes; read path fields from the raw file.
    let eq_directory = read_raw_default_value(path, "eq_directory")
        .or_else(|| optional_str(default, "eq_directory"));
    let eq_directory_secondary = read_raw_default_value(path, "eq_secondary_directory")
        .or_else(|| optional_str(default, "eq_secondary_directory"));
    let encryption = ini.section(Some("encryption"));
    let dark_mode = get_bool(default, "dark_mode", true);
    let theme_mode = normalize_theme_mode(
        &get_str(
            default,
            "theme_mode",
            if dark_mode { "dark" } else { "light" },
        ),
        dark_mode,
    );

    Ok(ConfigFileV1 {
        version: 1,
        listen_host,
        listen_port: get_u16(default, "listen_port", 6998),
        allow_non_loopback,
        proxy_enabled: get_bool(default, "proxy_enabled", true),
        proxy_only: get_bool(default, "proxy_only", false),
        always_on_top: get_bool(default, "always_on_top", false),
        launch_startup: get_bool(default, "launch_startup", false),
        launch_admin: get_bool(default, "launch_admin", true),
        warn_rustle: get_bool(default, "warn_rustle", false),
        auto_add_local_characters: get_bool(default, "auto_add_local_characters", true),
        skip_sso: false,
        skip_sso_accounts: get_str(default, "skip_sso_accounts", ""),
        sso_backend,
        sso_api_url,
        sso_verify_tls: get_bool(default, "sso_verify_tls", true),
        eq_directory,
        eq_directory_secondary,
        local_accounts_file: read_raw_default_value(path, "local_accounts_file")
            .unwrap_or_else(|| get_str(default, "local_accounts_file", "local_accounts.csv")),
        local_characters_file: read_raw_default_value(path, "local_characters_file")
            .unwrap_or_else(|| get_str(default, "local_characters_file", "local_characters.csv")),
        encryption_key: encryption
            .and_then(|section| section.get("key"))
            .and_then(parse_encryption_bytes)
            .unwrap_or([0; 8]),
        encryption_iv: encryption
            .and_then(|section| section.get("iv"))
            .and_then(parse_encryption_bytes)
            .unwrap_or([0; 8]),
        upstream_host: get_str(default, "login_server", "login.eqemulator.net"),
        upstream_port: get_u16(default, "login_port", 5998),
        login_timeout_secs: get_u64(default, "sso_timeout", 10),
        dark_mode,
        theme_mode,
        prerelease_updates: get_bool(default, "opt_into_prereleases", false),
        api_tokens,
        sso_backends,
        sso_ca_bundle: get_str(default, "sso_ca_bundle", "True"),
    })
}

/// Update the native application's managed ``[DEFAULT]`` keys in-place.
///
/// This deliberately edits the original text instead of serializing an [`Ini`].
/// Python's ConfigParser files commonly contain comments, unknown keys and
/// backslash-heavy Windows paths which must survive a settings save unchanged.
/// Token entries are never generated or updated here. The runtime uses
/// [`scrub_proxyconfig_tokens`] only after migration to the OS keyring succeeds.
pub fn write_proxyconfig_ini(path: &Path, file: &ConfigFileV1) -> Result<(), ConfigError> {
    write_proxyconfig_ini_impl(path, file, false)
}

/// Rewrite an INI while removing all known legacy plaintext token fields.
pub fn scrub_proxyconfig_tokens(path: &Path, file: &ConfigFileV1) -> Result<(), ConfigError> {
    write_proxyconfig_ini_impl(path, file, true)
}

fn write_proxyconfig_ini_impl(
    path: &Path,
    file: &ConfigFileV1,
    scrub_tokens: bool,
) -> Result<(), ConfigError> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    let original = std::fs::read_to_string(path).unwrap_or_default();
    let newline = if original.contains("\r\n") {
        "\r\n"
    } else {
        "\n"
    };
    let had_trailing_newline = original.ends_with('\n');
    let mut output = Vec::new();
    let mut pending = managed_default_values(file);
    let mut section = String::new();
    let mut saw_default = false;
    let mut inserted_default_values = false;

    for line in original.lines() {
        let trimmed = line.trim();
        if let Some(name) = section_name(trimmed) {
            if section.eq_ignore_ascii_case("DEFAULT") && !inserted_default_values {
                append_pending_values(&mut output, &mut pending);
                inserted_default_values = true;
            }
            section = name.to_string();
            saw_default |= section.eq_ignore_ascii_case("DEFAULT");
            output.push(line.to_string());
            continue;
        }

        let is_default = section.is_empty() || section.eq_ignore_ascii_case("DEFAULT");
        if let Some((key, _)) = assignment(trimmed) {
            if scrub_tokens
                && ((is_default && key.eq_ignore_ascii_case("user_api_token"))
                    || section.eq_ignore_ascii_case("api_tokens")
                    || section.eq_ignore_ascii_case("api_tokens_old"))
            {
                continue;
            }
            if is_default {
                if let Some((canonical, value)) = take_managed_value(&mut pending, key) {
                    if let Some(value) = value {
                        output.push(format!("{canonical} = {value}"));
                    }
                    continue;
                }
            }
        }
        output.push(line.to_string());
    }

    if section.eq_ignore_ascii_case("DEFAULT") && !inserted_default_values {
        append_pending_values(&mut output, &mut pending);
    } else if !saw_default && !pending.is_empty() {
        let mut prefix = vec!["[DEFAULT]".to_string()];
        append_pending_values(&mut prefix, &mut pending);
        if !output.is_empty() {
            prefix.push(String::new());
        }
        prefix.append(&mut output);
        output = prefix;
    }

    let mut body = output.join(newline);
    if had_trailing_newline || original.is_empty() {
        body.push_str(newline);
    }
    std::fs::write(path, body)?;
    Ok(())
}

fn managed_default_values(file: &ConfigFileV1) -> Vec<(&'static str, Option<String>)> {
    vec![
        ("listen_host", Some(file.listen_host.clone())),
        ("listen_port", Some(file.listen_port.to_string())),
        ("login_server", Some(file.upstream_host.clone())),
        ("login_port", Some(file.upstream_port.to_string())),
        ("proxy_enabled", Some(python_bool(file.proxy_enabled))),
        ("proxy_only", Some(python_bool(file.proxy_only))),
        ("always_on_top", Some(python_bool(file.always_on_top))),
        ("launch_startup", Some(python_bool(file.launch_startup))),
        ("launch_admin", Some(python_bool(file.launch_admin))),
        ("warn_rustle", Some(python_bool(file.warn_rustle))),
        (
            "auto_add_local_characters",
            Some(python_bool(file.auto_add_local_characters)),
        ),
        ("skip_sso", Some(python_bool(file.skip_sso))),
        ("skip_sso_accounts", Some(file.skip_sso_accounts.clone())),
        ("sso_api_name", Some(file.sso_backend.clone())),
        ("sso_api", file.sso_api_url.clone()),
        ("sso_verify_tls", Some(python_bool(file.sso_verify_tls))),
        ("sso_ca_bundle", Some(file.sso_ca_bundle.clone())),
        ("sso_timeout", Some(file.login_timeout_secs.to_string())),
        ("eq_directory", file.eq_directory.clone()),
        (
            "eq_secondary_directory",
            file.eq_directory_secondary.clone(),
        ),
        (
            "local_accounts_file",
            Some(file.local_accounts_file.clone()),
        ),
        (
            "local_characters_file",
            Some(file.local_characters_file.clone()),
        ),
        ("dark_mode", Some(python_bool(file.dark_mode))),
        ("theme_mode", Some(file.theme_mode.clone())),
        (
            "opt_into_prereleases",
            Some(python_bool(file.prerelease_updates)),
        ),
    ]
}

fn section_name(line: &str) -> Option<&str> {
    line.strip_prefix('[')?.strip_suffix(']').map(str::trim)
}

fn assignment(line: &str) -> Option<(&str, &str)> {
    if line.starts_with('#') || line.starts_with(';') {
        return None;
    }
    line.split_once('=')
        .map(|(key, value)| (key.trim(), value.trim()))
}

fn take_managed_value(
    values: &mut Vec<(&'static str, Option<String>)>,
    key: &str,
) -> Option<(&'static str, Option<String>)> {
    let index = values
        .iter()
        .position(|(candidate, _)| candidate.eq_ignore_ascii_case(key))?;
    Some(values.remove(index))
}

fn append_pending_values(
    output: &mut Vec<String>,
    values: &mut Vec<(&'static str, Option<String>)>,
) {
    for (key, value) in values.drain(..) {
        if let Some(value) = value {
            output.push(format!("{key} = {value}"));
        }
    }
}

fn python_bool(value: bool) -> String {
    if value { "True" } else { "False" }.to_string()
}

fn normalize_theme_mode(raw: &str, dark_mode: bool) -> String {
    match raw.trim().to_ascii_lowercase().as_str() {
        "dark" => "dark".to_string(),
        "light" => "light".to_string(),
        "system" => "system".to_string(),
        "gnomish" | "akanon" => "gnomish".to_string(),
        "iceclad" => "iceclad".to_string(),
        "kelethin" => "kelethin".to_string(),
        "lavastorm" => "lavastorm".to_string(),
        "erudin" => "erudin".to_string(),
        "plane_of_sky" | "sky" => "erudin".to_string(),
        "paineel" => "paineel".to_string(),
        _ if dark_mode => "dark".to_string(),
        _ => "light".to_string(),
    }
}

fn parse_encryption_bytes(raw: &str) -> Option<[u8; 8]> {
    let compact = raw.trim().replace("\\x", "").replace("\\X", "");
    if compact.len() != 16 {
        return None;
    }
    let mut bytes = [0; 8];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&compact[index * 2..index * 2 + 2], 16).ok()?;
    }
    Some(bytes)
}

/// Visit every ``key = value`` assignment in a raw INI file without INI escape
/// processing (so Windows paths keep their ``\``).
///
/// The visitor receives the current section name (empty string for the implicit
/// top-of-file / ``[DEFAULT]`` region) plus the trimmed key and value. Blank
/// lines and ``#``/``;`` comments are skipped. Does nothing if the file cannot
/// be read.
fn for_each_raw_assignment<F: FnMut(&str, &str, &str)>(ini_path: &Path, mut visit: F) {
    let Ok(content) = std::fs::read_to_string(ini_path) else {
        return;
    };
    let mut section = String::new();
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with(';') {
            continue;
        }
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            section = trimmed[1..trimmed.len() - 1].trim().to_string();
            continue;
        }
        if let Some((key, value)) = trimmed.split_once('=') {
            visit(&section, key.trim(), value.trim());
        }
    }
}

/// Read a ``[DEFAULT]`` key without INI escape processing (Windows paths keep ``\``).
fn read_raw_default_value(ini_path: &Path, key: &str) -> Option<String> {
    let mut found = None;
    for_each_raw_assignment(ini_path, |section, k, v| {
        if found.is_some() {
            return;
        }
        let is_default = section.is_empty() || section.eq_ignore_ascii_case("default");
        if is_default && k.eq_ignore_ascii_case(key) && !v.is_empty() {
            found = Some(v.to_string());
        }
    });
    found
}

/// Parse ``[api_tokens]`` directly from the file (keys may contain spaces).
fn read_raw_api_tokens_section(ini_path: &Path) -> HashMap<String, String> {
    let mut tokens = HashMap::new();
    for_each_raw_assignment(ini_path, |section, key, value| {
        if section.eq_ignore_ascii_case("api_tokens") && !value.is_empty() {
            tokens.insert(normalize_backend_name(key), value.to_string());
        }
    });
    tokens
}

fn normalize_backend_name(name: &str) -> String {
    match name.trim() {
        "P99 Login Proxy" | "P99 Login Proxy (GG)" => "Good Guys".to_string(),
        other => other.to_string(),
    }
}

/// When legacy INI used ``P99 Login Proxy`` as the backend, seed Good Guys + Marginal Threat tokens.
fn seed_p99_proxy_legacy_tokens(
    api_tokens: &mut HashMap<String, String>,
    ini_path: &Path,
    default: Option<&ini::Properties>,
) {
    let mut legacy_token: Option<String> = None;
    for_each_raw_assignment(ini_path, |section, key, value| {
        if section.eq_ignore_ascii_case("api_tokens")
            && (key == "P99 Login Proxy" || key == "P99 Login Proxy (GG)")
            && !value.is_empty()
        {
            legacy_token = Some(value.to_string());
        }
    });
    let backend_name = read_raw_default_value(ini_path, "sso_api_name")
        .or_else(|| default.and_then(|s| s.get("sso_api_name").map(str::to_string)))
        .unwrap_or_default();
    if legacy_token.is_none()
        && (backend_name.trim() == "P99 Login Proxy"
            || backend_name.trim() == "P99 Login Proxy (GG)")
    {
        let legacy = get_str(default, "user_api_token", "");
        if !legacy.is_empty() {
            legacy_token = Some(legacy);
        }
    }
    let Some(token) = legacy_token else {
        return;
    };
    for backend in ["Good Guys", "Marginal Threat"] {
        api_tokens
            .entry(backend.to_string())
            .or_insert_with(|| token.clone());
    }
}

fn get_str(section: Option<&ini::Properties>, key: &str, default: &str) -> String {
    section
        .and_then(|s| s.get(key))
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or(default)
        .to_string()
}

fn optional_str(section: Option<&ini::Properties>, key: &str) -> Option<String> {
    section
        .and_then(|s| s.get(key))
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

fn get_bool(section: Option<&ini::Properties>, key: &str, default: bool) -> bool {
    section
        .and_then(|s| s.get(key))
        .and_then(parse_bool)
        .unwrap_or(default)
}

fn get_u16(section: Option<&ini::Properties>, key: &str, default: u16) -> u16 {
    section
        .and_then(|s| s.get(key))
        .and_then(|v| v.trim().parse().ok())
        .unwrap_or(default)
}

fn get_u64(section: Option<&ini::Properties>, key: &str, default: u64) -> u64 {
    section
        .and_then(|s| s.get(key))
        .and_then(|v| v.trim().parse().ok())
        .unwrap_or(default)
}

fn parse_bool(raw: &str) -> Option<bool> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "true" | "yes" | "1" | "on" => Some(true),
        "false" | "no" | "0" | "off" => Some(false),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use super::*;
    use tempfile::TempDir;

    #[test]
    fn parses_proxyconfig_ini_fields() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("proxyconfig.ini");
        std::fs::write(
            &path,
            r#"[DEFAULT]
listen_port = 6790
proxy_only = False
eq_directory = C:/Games/EQ
sso_api = http://localhost:5998
sso_api_name = Localhost
dark_mode = True
skip_sso_accounts = foo, bar

[api_tokens]
Localhost = testtoken123
"#,
        )
        .unwrap();
        let cfg = parse_proxyconfig_ini(&path).unwrap();
        assert_eq!(cfg.listen_port, 6790);
        assert!(!cfg.proxy_only);
        assert_eq!(cfg.eq_directory.as_deref(), Some("C:/Games/EQ"));
        assert_eq!(cfg.sso_backend, "Localhost");
        assert_eq!(cfg.sso_api_url.as_deref(), Some("http://localhost:5998"));
        assert_eq!(
            cfg.api_tokens.get("Localhost").map(String::as_str),
            Some("testtoken123")
        );
        assert_eq!(cfg.skip_sso_accounts, "foo, bar");
    }

    #[test]
    fn preserves_windows_path_backslashes() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("proxyconfig.ini");
        std::fs::write(
            &path,
            r#"[DEFAULT]
eq_directory = C:\Program Files (x86)\Sony\EverQuest
listen_port = 6790
"#,
        )
        .unwrap();
        let cfg = parse_proxyconfig_ini(&path).unwrap();
        assert_eq!(
            cfg.eq_directory.as_deref(),
            Some(r"C:\Program Files (x86)\Sony\EverQuest")
        );
    }

    #[test]
    fn encryption_defaults_to_zero_and_accepts_python_hex_format() {
        let dir = TempDir::new().unwrap();
        let default_path = dir.path().join("default.ini");
        std::fs::write(&default_path, "[DEFAULT]\nlisten_port = 5998\n").unwrap();
        let defaults = parse_proxyconfig_ini(&default_path).unwrap();
        assert_eq!(defaults.encryption_key, [0; 8]);
        assert_eq!(defaults.encryption_iv, [0; 8]);

        let custom_path = dir.path().join("custom.ini");
        std::fs::write(
            &custom_path,
            "[encryption]\nkey = \\x01\\x02\\x03\\x04\\x05\\x06\\x07\\x08\niv = \\x08\\x07\\x06\\x05\\x04\\x03\\x02\\x01\n",
        )
        .unwrap();
        let custom = parse_proxyconfig_ini(&custom_path).unwrap();
        assert_eq!(custom.encryption_key, [1, 2, 3, 4, 5, 6, 7, 8]);
        assert_eq!(custom.encryption_iv, [8, 7, 6, 5, 4, 3, 2, 1]);
    }

    #[test]
    fn theme_mode_migrates_from_dark_mode_and_supports_system() {
        let dir = TempDir::new().unwrap();
        let legacy = dir.path().join("legacy.ini");
        std::fs::write(&legacy, "[DEFAULT]\ndark_mode = False\n").unwrap();
        assert_eq!(parse_proxyconfig_ini(&legacy).unwrap().theme_mode, "light");

        let native = dir.path().join("native.ini");
        std::fs::write(
            &native,
            "[DEFAULT]\ndark_mode = True\ntheme_mode = system\n",
        )
        .unwrap();
        assert_eq!(parse_proxyconfig_ini(&native).unwrap().theme_mode, "system");

        let gnomish = dir.path().join("gnomish.ini");
        std::fs::write(&gnomish, "[DEFAULT]\ntheme_mode = gnomish\n").unwrap();
        assert_eq!(parse_proxyconfig_ini(&gnomish).unwrap().theme_mode, "gnomish");

        let legacy_akanon = dir.path().join("legacy_akanon.ini");
        std::fs::write(&legacy_akanon, "[DEFAULT]\ntheme_mode = akanon\n").unwrap();
        assert_eq!(
            parse_proxyconfig_ini(&legacy_akanon).unwrap().theme_mode,
            "gnomish"
        );

        let iceclad = dir.path().join("iceclad.ini");
        std::fs::write(&iceclad, "[DEFAULT]\ntheme_mode = Iceclad\n").unwrap();
        assert_eq!(parse_proxyconfig_ini(&iceclad).unwrap().theme_mode, "iceclad");

        let kelethin = dir.path().join("kelethin.ini");
        std::fs::write(&kelethin, "[DEFAULT]\ntheme_mode = kelethin\n").unwrap();
        assert_eq!(parse_proxyconfig_ini(&kelethin).unwrap().theme_mode, "kelethin");

        let lavastorm = dir.path().join("lavastorm.ini");
        std::fs::write(&lavastorm, "[DEFAULT]\ntheme_mode = lavastorm\n").unwrap();
        assert_eq!(parse_proxyconfig_ini(&lavastorm).unwrap().theme_mode, "lavastorm");

        let sky = dir.path().join("sky.ini");
        std::fs::write(&sky, "[DEFAULT]\ntheme_mode = sky\n").unwrap();
        assert_eq!(parse_proxyconfig_ini(&sky).unwrap().theme_mode, "erudin");

        let legacy_sky = dir.path().join("legacy_sky.ini");
        std::fs::write(
            &legacy_sky,
            "[DEFAULT]\ntheme_mode = plane_of_sky\n",
        )
        .unwrap();
        assert_eq!(parse_proxyconfig_ini(&legacy_sky).unwrap().theme_mode, "erudin");

        let erudin = dir.path().join("erudin.ini");
        std::fs::write(&erudin, "[DEFAULT]\ntheme_mode = erudin\n").unwrap();
        assert_eq!(parse_proxyconfig_ini(&erudin).unwrap().theme_mode, "erudin");

        let paineel = dir.path().join("paineel.ini");
        std::fs::write(&paineel, "[DEFAULT]\ntheme_mode = paineel\n").unwrap();
        assert_eq!(parse_proxyconfig_ini(&paineel).unwrap().theme_mode, "paineel");
    }

    #[test]
    fn writes_managed_values_and_preserves_unknown_content() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("proxyconfig.ini");
        std::fs::write(
            &path,
            "[DEFAULT]\r\n; keep this comment\r\nlisten_port = 5998\r\ncustom = C:\\Games\\EQ\r\nuser_api_token = secret\r\n\r\n[api_tokens_old]\r\nhttps = //example = old-secret\r\n\r\n[api_tokens]\r\nGood Guys = secret\r\n\r\n[encryption]\r\nkey = \\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\r\n",
        )
        .unwrap();
        let file = ConfigFileV1 {
            listen_port: 6790,
            eq_directory: Some(r"C:\Program Files (x86)\Sony\EverQuest".to_string()),
            ..ConfigFileV1::default()
        };

        write_proxyconfig_ini(&path, &file).unwrap();
        let written = std::fs::read_to_string(&path).unwrap();
        assert!(written.contains("; keep this comment\r\n"));
        assert!(written.contains("listen_port = 6790\r\n"));
        assert!(written.contains(r"custom = C:\Games\EQ"));
        assert!(written.contains(r"eq_directory = C:\Program Files (x86)\Sony\EverQuest"));
        assert!(written.contains("[encryption]\r\nkey = \\x00"));
        assert!(written.contains("user_api_token = secret"));
        assert!(written.contains("Good Guys = secret"));

        let round_trip = parse_proxyconfig_ini(&path).unwrap();
        assert_eq!(round_trip.listen_port, 6790);
        assert_eq!(round_trip.eq_directory, file.eq_directory);

        scrub_proxyconfig_tokens(&path, &file).unwrap();
        let scrubbed = std::fs::read_to_string(&path).unwrap();
        assert!(!scrubbed.contains("user_api_token"));
        assert!(!scrubbed.contains("Good Guys = secret"));
        assert!(!scrubbed.contains("old-secret"));
    }

    #[test]
    fn imports_per_backend_api_tokens_from_ini() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("proxyconfig.ini");
        std::fs::write(
            &path,
            r#"[DEFAULT]
user_api_token = ReportFrailTrailSticky
sso_api_name = Localhost

[api_tokens]
Localhost = ReportFrailTrailSticky
P99 Login Proxy = SealNonchalantSide
P99 Login Proxy (GG) = WipeJaggedOranges
Good Guys = SealNonchalantSide
Marginal Threat = SealNonchalantSide
"#,
        )
        .unwrap();
        let cfg = parse_proxyconfig_ini(&path).unwrap();
        assert_eq!(
            cfg.api_tokens.get("Localhost").map(String::as_str),
            Some("ReportFrailTrailSticky")
        );
        assert_eq!(
            cfg.api_tokens.get("Good Guys").map(String::as_str),
            Some("SealNonchalantSide")
        );
        assert_eq!(
            cfg.api_tokens.get("Marginal Threat").map(String::as_str),
            Some("SealNonchalantSide")
        );
    }

    #[test]
    fn parses_workspace_proxyconfig_if_present() {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("..")
            .join("p99-login-proxy")
            .join("proxyconfig.ini");
        if !path.is_file() {
            return;
        }
        let cfg = parse_proxyconfig_ini(&path).expect("real proxyconfig.ini should parse");
        assert_eq!(cfg.sso_backend, "Localhost");
        assert_eq!(cfg.listen_port, 6790);
        assert!(cfg
            .eq_directory
            .as_ref()
            .is_some_and(|d| d.contains("EverQuest")));
    }
}
