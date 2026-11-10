use std::net::IpAddr;

use std::collections::HashSet;

use protocol::crypto::DesKeyIv;
use proxy_core::accounts::LocalAccountStore;
use proxy_core::characters::LocalCharacterStore;
use proxy_core::SsoCaBundleMode;
use secrecy::SecretString;

/// Runtime configuration for the live UDP login proxy.
#[derive(Debug, Clone)]
pub struct ProxyRuntimeConfig {
    pub listen_host: String,
    pub listen_port: u16,
    pub upstream_host: String,
    pub upstream_port: u16,
    pub proxy_only: bool,
    pub skip_sso_accounts: HashSet<String>,
    pub des_key_iv: DesKeyIv,
    pub idle_timeout_secs: u64,
    pub sso_backend: String,
    pub sso_api_url: String,
    pub sso_timeout_secs: u64,
    pub sso_verify_tls: bool,
    pub sso_ca_bundle: SsoCaBundleMode,
    pub client_version: String,
}

impl ProxyRuntimeConfig {
    pub fn from_validated(validated: &proxy_core::ValidatedConfig, sso_api_url: String) -> Self {
        Self {
            listen_host: validated.listen_host.clone(),
            listen_port: validated.listen_port,
            upstream_host: validated.upstream_host.clone(),
            upstream_port: validated.upstream_port,
            proxy_only: validated.proxy_only,
            skip_sso_accounts: validated.skip_sso_accounts.iter().cloned().collect(),
            des_key_iv: DesKeyIv {
                key: validated.encryption_key,
                iv: validated.encryption_iv,
            },
            idle_timeout_secs: 60,
            sso_backend: validated.sso_backend.clone(),
            sso_api_url,
            sso_timeout_secs: validated.login_timeout_secs,
            sso_verify_tls: validated.sso_verify_tls,
            sso_ca_bundle: validated.sso_ca_bundle.clone(),
            client_version: proxy_core::version_string().to_string(),
        }
    }
}

/// True when the configured listen host is loopback-only (`127.0.0.1` / `localhost`).
pub use proxy_core::config::is_loopback as is_loopback_host;

/// Address written to `eqhost.txt`. Wildcard bind addresses accept local
/// connections but are not valid destinations, so advertise IPv4 loopback.
pub fn eqhost_connect_host(listen_host: &str) -> &str {
    let host = listen_host.trim();
    if host
        .parse::<IpAddr>()
        .is_ok_and(|address| address.is_unspecified())
    {
        "127.0.0.1"
    } else {
        host
    }
}

impl Default for ProxyRuntimeConfig {
    fn default() -> Self {
        Self {
            listen_host: "127.0.0.1".to_string(),
            listen_port: 6998,
            upstream_host: "login.eqemulator.net".to_string(),
            upstream_port: 5998,
            proxy_only: false,
            skip_sso_accounts: HashSet::new(),
            des_key_iv: DesKeyIv {
                key: protocol::DEFAULT_DES_KEY,
                iv: protocol::DEFAULT_DES_IV,
            },
            idle_timeout_secs: 60,
            sso_backend: "Good Guys".to_string(),
            sso_api_url: "https://proxy.p99loginproxy.net".to_string(),
            sso_timeout_secs: 15,
            sso_verify_tls: true,
            sso_ca_bundle: SsoCaBundleMode::WebpkiRoots,
            client_version: proxy_core::version_string().to_string(),
        }
    }
}

impl ProxyRuntimeConfig {
    pub fn loopback_test(upstream_port: u16, listen_port: u16) -> Self {
        Self {
            listen_host: "127.0.0.1".to_string(),
            listen_port,
            upstream_host: "127.0.0.1".to_string(),
            upstream_port,
            proxy_only: false,
            ..Default::default()
        }
    }
}

/// Local credential sources used by the proxy for synchronous rewrites.
#[derive(Debug, Default, Clone)]
pub struct ProxyLocalData {
    pub accounts: LocalAccountStore,
    pub characters: LocalCharacterStore,
}

impl ProxyLocalData {
    pub fn with_account(alias: &str, username: &str, password: &str) -> Self {
        let mut accounts = LocalAccountStore::default();
        accounts.insert(
            alias.to_string(),
            username.to_string(),
            SecretString::from(password.to_string()),
        );
        Self {
            accounts,
            characters: LocalCharacterStore::default(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{eqhost_connect_host, is_loopback_host};

    #[test]
    fn default_listen_host_is_loopback() {
        assert!(is_loopback_host(
            &super::ProxyRuntimeConfig::default().listen_host
        ));
    }

    #[test]
    fn sso_client_version_meets_v2_contract() {
        assert!(proxy_core::version().major >= 2);
        let cfg = super::ProxyRuntimeConfig::default();
        assert_eq!(cfg.client_version, proxy_core::version_string());
    }

    #[test]
    fn detects_loopback_hosts() {
        assert!(is_loopback_host("127.0.0.1"));
        assert!(is_loopback_host("localhost"));
        assert!(!is_loopback_host("0.0.0.0"));
    }

    #[test]
    fn eqhost_uses_loopback_for_wildcard_binds() {
        assert_eq!(eqhost_connect_host("0.0.0.0"), "127.0.0.1");
        assert_eq!(eqhost_connect_host("::"), "127.0.0.1");
    }

    #[test]
    fn eqhost_preserves_specific_bind_address() {
        assert_eq!(eqhost_connect_host("192.168.1.12"), "192.168.1.12");
        assert_eq!(eqhost_connect_host("localhost"), "localhost");
    }
}
