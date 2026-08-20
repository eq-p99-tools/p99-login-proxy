use std::collections::HashMap;
use std::net::Ipv4Addr;
use std::path::{Path, PathBuf};

use directories::ProjectDirs;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tracing::warn;

/// Built-in SSO backends (Python ``SSO_API_OPTIONS``), excluding Localhost.
pub const SSO_BACKENDS: &[(&str, &str)] = &[
    ("Good Guys", "https://proxy.p99loginproxy.net"),
    ("Kingdom", "https://bot.kingdomdkp.com"),
    ("Marginal Threat", "https://proxy.p99loginproxy.net"),
];

const SSO_BACKEND_LOCALHOST: (&str, &str) = ("Localhost", "http://localhost:5998");

/// Built-in backends for the running app version (Localhost only on prerelease builds).
pub fn builtin_sso_backends() -> Vec<(&'static str, &'static str)> {
    let mut options: Vec<(&str, &str)> = SSO_BACKENDS.to_vec();
    if !crate::app_version::version().pre.is_empty() {
        options.push(SSO_BACKEND_LOCALHOST);
    }
    options
}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("parse error: {0}")]
    Parse(#[from] toml::de::Error),
    #[error("serialize error: {0}")]
    Serialize(#[from] toml::ser::Error),
    #[error("validation: {0}")]
    Validation(String),
}

pub fn app_config_dir() -> Option<PathBuf> {
    config_file_path().and_then(|path| path.parent().map(Path::to_path_buf))
}

pub fn config_file_path() -> Option<PathBuf> {
    #[cfg(debug_assertions)]
    {
        if let Ok(cwd) = std::env::current_dir() {
            for dir in cwd.ancestors().take(4) {
                for candidate in [
                    dir.join("proxyconfig.ini"),
                    dir.join("p99-login-proxy").join("proxyconfig.ini"),
                    dir.join("pythonProject").join("proxyconfig.ini"),
                ] {
                    if candidate.is_file() {
                        return Some(candidate);
                    }
                }
            }
            return Some(cwd.join("proxyconfig.ini"));
        }
    }
    let appimage = if cfg!(target_os = "linux") {
        std::env::var_os("APPIMAGE").map(PathBuf::from)
    } else {
        None
    };
    release_config_file_path(appimage, std::env::current_exe().ok())
}

fn release_config_file_path(
    appimage: Option<PathBuf>,
    current_exe: Option<PathBuf>,
) -> Option<PathBuf> {
    appimage
        .or(current_exe)
        .and_then(|exe| exe.parent().map(|dir| dir.join("proxyconfig.ini")))
}

fn legacy_native_config_file_path() -> Option<PathBuf> {
    ProjectDirs::from("com", "P99LoginProxy", "P99LoginProxy")
        .map(|dirs| dirs.config_dir().join("config.toml"))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfigFileV1 {
    pub version: u32,
    #[serde(default = "default_listen_host")]
    pub listen_host: String,
    #[serde(default = "default_listen_port")]
    pub listen_port: u16,
    #[serde(default)]
    pub allow_non_loopback: bool,
    #[serde(default = "default_proxy_enabled")]
    pub proxy_enabled: bool,
    #[serde(default)]
    pub proxy_only: bool,
    #[serde(default)]
    pub always_on_top: bool,
    #[serde(default)]
    pub launch_startup: bool,
    #[serde(default = "default_launch_admin")]
    pub launch_admin: bool,
    #[serde(default)]
    pub warn_rustle: bool,
    #[serde(default = "default_auto_add_local_characters")]
    pub auto_add_local_characters: bool,
    #[serde(default)]
    pub skip_sso_accounts: String,
    #[serde(default)]
    pub sso_backend: String,
    #[serde(default)]
    pub sso_api_url: Option<String>,
    #[serde(default)]
    pub sso_verify_tls: bool,
    #[serde(default)]
    pub eq_directory: Option<String>,
    #[serde(default)]
    pub eq_directory_secondary: Option<String>,
    #[serde(default = "default_local_accounts_file")]
    pub local_accounts_file: String,
    #[serde(default = "default_local_characters_file")]
    pub local_characters_file: String,
    #[serde(default = "default_encryption_bytes")]
    pub encryption_key: [u8; 8],
    #[serde(default = "default_encryption_bytes")]
    pub encryption_iv: [u8; 8],
    #[serde(default = "default_upstream_host")]
    pub upstream_host: String,
    #[serde(default = "default_upstream_port")]
    pub upstream_port: u16,
    #[serde(default = "default_login_timeout_secs")]
    pub login_timeout_secs: u64,
    #[serde(default = "default_dark_mode")]
    pub dark_mode: bool,
    #[serde(default = "default_theme_mode")]
    pub theme_mode: String,
    #[serde(default)]
    pub prerelease_updates: bool,
    #[serde(default)]
    pub api_tokens: HashMap<String, String>,
    #[serde(default)]
    pub sso_backends: HashMap<String, String>,
    #[serde(default = "default_sso_ca_bundle")]
    pub sso_ca_bundle: String,
}

fn default_listen_host() -> String {
    "127.0.0.1".to_string()
}

fn default_listen_port() -> u16 {
    6998
}

fn default_upstream_port() -> u16 {
    5998
}

fn default_upstream_host() -> String {
    "login.eqemulator.net".to_string()
}

fn default_proxy_enabled() -> bool {
    true
}

fn default_launch_admin() -> bool {
    true
}

fn default_auto_add_local_characters() -> bool {
    false
}

fn default_login_timeout_secs() -> u64 {
    10
}

fn default_dark_mode() -> bool {
    true
}

fn default_theme_mode() -> String {
    "system".to_string()
}

fn default_local_accounts_file() -> String {
    "local_accounts.csv".to_string()
}

fn default_local_characters_file() -> String {
    "local_characters.csv".to_string()
}

fn default_encryption_bytes() -> [u8; 8] {
    [0; 8]
}

fn default_sso_ca_bundle() -> String {
    "True".to_string()
}

/// CA trust mode for SSO WebSocket TLS (Python ``_resolve_ca_mode``).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SsoCaBundleMode {
    /// Bundled Mozilla/webpki roots (Python ``certifi`` default).
    WebpkiRoots,
    /// Platform trust store (Python ``system`` / ``False``).
    System,
    /// User-supplied PEM bundle path.
    Custom(PathBuf),
}

impl SsoCaBundleMode {
    pub fn custom_path(&self) -> Option<&Path> {
        match self {
            Self::Custom(path) => Some(path),
            _ => None,
        }
    }
}

/// Resolve ``sso_ca_bundle`` from portable INI into a TLS trust mode.
pub fn resolve_sso_ca_bundle(raw: &str) -> Result<SsoCaBundleMode, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() || trimmed.eq_ignore_ascii_case("true") {
        return Ok(SsoCaBundleMode::WebpkiRoots);
    }
    if trimmed.eq_ignore_ascii_case("false") || trimmed.eq_ignore_ascii_case("system") {
        return Ok(SsoCaBundleMode::System);
    }
    let path = PathBuf::from(trimmed);
    if !path.is_file() {
        return Err(format!("SSO CA bundle not found: {}", path.display()));
    }
    Ok(SsoCaBundleMode::Custom(path))
}

impl Default for ConfigFileV1 {
    fn default() -> Self {
        Self {
            version: 1,
            listen_host: default_listen_host(),
            listen_port: default_listen_port(),
            allow_non_loopback: false,
            proxy_enabled: true,
            proxy_only: false,
            always_on_top: false,
            launch_startup: false,
            launch_admin: true,
            warn_rustle: false,
            auto_add_local_characters: false,
            skip_sso_accounts: String::new(),
            sso_backend: "Good Guys".to_string(),
            sso_api_url: None,
            sso_verify_tls: true,
            eq_directory: None,
            eq_directory_secondary: None,
            local_accounts_file: default_local_accounts_file(),
            local_characters_file: default_local_characters_file(),
            encryption_key: default_encryption_bytes(),
            encryption_iv: default_encryption_bytes(),
            upstream_host: default_upstream_host(),
            upstream_port: default_upstream_port(),
            login_timeout_secs: default_login_timeout_secs(),
            dark_mode: default_dark_mode(),
            theme_mode: default_theme_mode(),
            prerelease_updates: false,
            api_tokens: HashMap::new(),
            sso_backends: HashMap::new(),
            sso_ca_bundle: default_sso_ca_bundle(),
        }
    }
}

pub fn parse_skip_sso_accounts(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|s| s.to_lowercase())
        .collect()
}

#[derive(Debug, Clone)]
pub struct ValidatedConfig {
    pub listen_host: String,
    pub listen_port: u16,
    pub proxy_enabled: bool,
    pub proxy_only: bool,
    pub always_on_top: bool,
    pub launch_startup: bool,
    pub launch_admin: bool,
    pub warn_rustle: bool,
    pub auto_add_local_characters: bool,
    pub skip_sso_accounts: Vec<String>,
    pub sso_backend: String,
    pub sso_verify_tls: bool,
    pub sso_ca_bundle: SsoCaBundleMode,
    pub eq_directory: Option<PathBuf>,
    pub eq_directory_secondary: Option<PathBuf>,
    pub encryption_key: [u8; 8],
    pub encryption_iv: [u8; 8],
    pub upstream_host: String,
    pub upstream_port: u16,
    pub login_timeout_secs: u64,
    pub dark_mode: bool,
    pub prerelease_updates: bool,
}

impl ValidatedConfig {
    pub fn from_file(file: &ConfigFileV1) -> Result<Self, ConfigError> {
        if !file.allow_non_loopback && !is_loopback(&file.listen_host) {
            return Err(ConfigError::Validation(
                "non-loopback bind requires allow_non_loopback".into(),
            ));
        }
        if file.listen_port == 0 {
            return Err(ConfigError::Validation(
                "listen_port must be non-zero".into(),
            ));
        }
        let (upstream_host, upstream_port) =
            crate::net_util::split_host_port(&file.upstream_host, file.upstream_port);
        let sso_ca_bundle =
            resolve_sso_ca_bundle(&file.sso_ca_bundle).map_err(ConfigError::Validation)?;
        Ok(Self {
            listen_host: file.listen_host.clone(),
            listen_port: file.listen_port,
            proxy_enabled: file.proxy_enabled,
            proxy_only: file.proxy_only,
            always_on_top: file.always_on_top,
            launch_startup: file.launch_startup,
            launch_admin: file.launch_admin,
            warn_rustle: file.warn_rustle,
            auto_add_local_characters: file.auto_add_local_characters,
            skip_sso_accounts: parse_skip_sso_accounts(&file.skip_sso_accounts),
            sso_backend: file.sso_backend.clone(),
            sso_verify_tls: file.sso_verify_tls,
            sso_ca_bundle,
            eq_directory: file.eq_directory.as_ref().map(PathBuf::from),
            eq_directory_secondary: file.eq_directory_secondary.as_ref().map(PathBuf::from),
            encryption_key: file.encryption_key,
            encryption_iv: file.encryption_iv,
            upstream_host,
            upstream_port,
            login_timeout_secs: file.login_timeout_secs.max(1),
            dark_mode: file.dark_mode,
            prerelease_updates: file.prerelease_updates,
        })
    }
}

/// True when `host` is loopback-only (`127.0.0.1` / `localhost`).
pub fn is_loopback(host: &str) -> bool {
    host == "localhost" || host.parse::<Ipv4Addr>().is_ok_and(|a| a.is_loopback())
}

pub fn load_config_file(path: &Path) -> Result<ConfigFileV1, ConfigError> {
    crate::proxyconfig_ini::parse_proxyconfig_ini(path)
}

/// Resolve the HTTP(S) SSO API base URL from config (matches Python ``SSO_API_OPTIONS``).
pub fn resolve_sso_api_url(file: &ConfigFileV1) -> String {
    if let Some(url) = file.sso_api_url.as_ref() {
        if !url.trim().is_empty() {
            return url.trim().to_string();
        }
    }
    if let Some(url) = file.sso_backends.get(&file.sso_backend) {
        if !url.trim().is_empty() {
            return url.trim().to_string();
        }
    }
    match file.sso_backend.as_str() {
        "Good Guys" | "Marginal Threat" => "https://proxy.p99loginproxy.net".to_string(),
        "Kingdom" => "https://bot.kingdomdkp.com".to_string(),
        "Localhost" => "http://localhost:5998".to_string(),
        _ => String::new(),
    }
}

/// Built-in SSO backends merged with legacy ``[sso_backends]`` entries.
pub fn list_sso_backend_options(file: &ConfigFileV1) -> Vec<(String, String)> {
    let mut options: Vec<(String, String)> = builtin_sso_backends()
        .into_iter()
        .map(|(name, url)| (name.to_string(), url.to_string()))
        .collect();

    for (name, url) in &file.sso_backends {
        if url.trim().is_empty() {
            continue;
        }
        if let Some(existing) = options
            .iter_mut()
            .find(|(existing_name, _)| existing_name == name)
        {
            existing.1 = url.trim().to_string();
        } else {
            options.push((name.clone(), url.trim().to_string()));
        }
    }

    if !file.sso_backend.trim().is_empty() {
        let resolved = resolve_sso_api_url(file);
        if !resolved.is_empty() && !options.iter().any(|(name, _)| name == &file.sso_backend) {
            options.push((file.sso_backend.clone(), resolved));
        }
    }

    options
}

pub fn load_config() -> Result<ConfigFileV1, ConfigError> {
    let Some(path) = config_file_path() else {
        return Ok(ConfigFileV1::default());
    };
    if path.is_file() {
        return load_config_file(&path);
    }

    if let Some(toml_path) =
        legacy_native_config_file_path().filter(|candidate| candidate.is_file())
    {
        let raw = std::fs::read_to_string(&toml_path)?;
        let file: ConfigFileV1 = toml::from_str(&raw)?;
        crate::proxyconfig_ini::write_proxyconfig_ini(&path, &file)?;
        warn!(
            from = %toml_path.display(),
            to = %path.display(),
            "imported preview config.toml into portable proxyconfig.ini"
        );
        return Ok(file);
    }

    let file = ConfigFileV1::default();
    crate::proxyconfig_ini::write_proxyconfig_ini(&path, &file)?;
    Ok(file)
}

pub fn save_config_file(path: &Path, file: &ConfigFileV1) -> Result<(), ConfigError> {
    crate::proxyconfig_ini::write_proxyconfig_ini(path, file)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn localhost_backend_follows_app_prerelease() {
        let has_prerelease = !crate::app_version::version().pre.is_empty();
        let has_localhost = builtin_sso_backends()
            .iter()
            .any(|(name, _)| *name == "Localhost");
        assert_eq!(has_localhost, has_prerelease);
    }

    #[test]
    fn release_config_lives_beside_appimage() {
        let appimage = PathBuf::from("/home/player/P99LoginProxy.AppImage");
        let mounted_exe = PathBuf::from("/tmp/.mount_p99/usr/bin/P99LoginProxy");
        assert_eq!(
            release_config_file_path(Some(appimage), Some(mounted_exe)),
            Some(PathBuf::from("/home/player/proxyconfig.ini"))
        );
    }

    #[test]
    fn release_config_falls_back_to_executable_directory() {
        let exe = PathBuf::from("/opt/p99/P99LoginProxy");
        assert_eq!(
            release_config_file_path(None, Some(exe)),
            Some(PathBuf::from("/opt/p99/proxyconfig.ini"))
        );
    }
}
