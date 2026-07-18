use std::collections::HashMap;
use std::net::Ipv4Addr;
use std::path::{Path, PathBuf};

use directories::ProjectDirs;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tracing::warn;

/// Built-in SSO backends (Python ``SSO_API_OPTIONS``).
pub const SSO_BACKENDS: &[(&str, &str)] = &[
    ("Good Guys", "https://proxy.p99loginproxy.net"),
    ("Kingdom", "https://bot.kingdomdkp.com"),
    ("Marginal Threat", "https://proxy.p99loginproxy.net"),
    ("Localhost", "http://localhost:5998"),
];

/// Semver reported on SSO WebSocket/HTTP auth (must meet guild ``min_client_version``).
pub const SSO_CLIENT_VERSION: &str = env!("CARGO_PKG_VERSION");

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
    std::env::current_exe()
        .ok()
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
    pub skip_sso: bool,
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
    #[serde(default)]
    pub login_timeout_secs: u64,
    #[serde(default = "default_dark_mode")]
    pub dark_mode: bool,
    #[serde(default = "default_theme_mode")]
    pub theme_mode: String,
    #[serde(default)]
    pub prerelease_updates: bool,
    #[serde(default)]
    pub api_tokens: HashMap<String, String>,
}

fn default_listen_host() -> String {
    "127.0.0.1".to_string()
}

fn default_listen_port() -> u16 {
    5998
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
    true
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
            auto_add_local_characters: true,
            skip_sso: false,
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
    pub skip_sso: bool,
    pub skip_sso_accounts: Vec<String>,
    pub sso_backend: String,
    pub sso_verify_tls: bool,
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
            skip_sso: file.skip_sso,
            skip_sso_accounts: parse_skip_sso_accounts(&file.skip_sso_accounts),
            sso_backend: file.sso_backend.clone(),
            sso_verify_tls: file.sso_verify_tls,
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

fn is_loopback(host: &str) -> bool {
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
    match file.sso_backend.as_str() {
        "Good Guys" | "Marginal Threat" => "https://proxy.p99loginproxy.net".to_string(),
        "Kingdom" => "https://bot.kingdomdkp.com".to_string(),
        "Localhost" => "http://localhost:5998".to_string(),
        _ => String::new(),
    }
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
