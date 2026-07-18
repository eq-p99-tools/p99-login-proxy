use std::net::{IpAddr, Ipv4Addr, SocketAddr};

use std::collections::HashSet;

use protocol::crypto::DesKeyIv;
use proxy_core::accounts::LocalAccountStore;
use proxy_core::characters::LocalCharacterStore;
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
            client_version: proxy_core::SSO_CLIENT_VERSION.to_string(),
        }
    }
}

/// True when the configured listen host is loopback-only (`127.0.0.1` / `localhost`).
pub fn is_loopback_host(host: &str) -> bool {
    host == "localhost" || host.parse::<Ipv4Addr>().is_ok_and(|a| a.is_loopback())
}

/// Pick a bind address that can reach *upstream*.
///
/// A socket bound to loopback cannot send UDP to an external login server on Windows
/// (WSAENETUNREACH / os error 10051). Python defaults to `0.0.0.0`; EQ still connects via
/// `127.0.0.1` in `eqhost.txt`.
pub fn effective_bind_host(listen_host: &str, upstream: SocketAddr) -> String {
    let upstream_loopback = match upstream.ip() {
        IpAddr::V4(v4) => v4.is_loopback(),
        IpAddr::V6(v6) => v6.is_loopback(),
    };
    if upstream_loopback || !is_loopback_host(listen_host) {
        listen_host.to_string()
    } else {
        "0.0.0.0".to_string()
    }
}

impl Default for ProxyRuntimeConfig {
    fn default() -> Self {
        Self {
            listen_host: "0.0.0.0".to_string(),
            listen_port: 5998,
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
            client_version: proxy_core::SSO_CLIENT_VERSION.to_string(),
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
    use std::net::{Ipv4Addr, SocketAddr};

    use super::{effective_bind_host, is_loopback_host};

    #[test]
    fn loopback_listen_upgraded_for_external_upstream() {
        let upstream: SocketAddr = (Ipv4Addr::new(70, 35, 159, 39), 5998).into();
        assert_eq!(effective_bind_host("127.0.0.1", upstream), "0.0.0.0");
    }

    #[test]
    fn loopback_listen_kept_for_loopback_upstream() {
        let upstream: SocketAddr = (Ipv4Addr::LOCALHOST, 5998).into();
        assert_eq!(effective_bind_host("127.0.0.1", upstream), "127.0.0.1");
    }

    #[test]
    fn non_loopback_listen_unchanged() {
        let upstream: SocketAddr = (Ipv4Addr::new(70, 35, 159, 39), 5998).into();
        assert_eq!(effective_bind_host("0.0.0.0", upstream), "0.0.0.0");
    }

    #[test]
    fn sso_client_version_meets_v2_contract() {
        assert_eq!(proxy_core::SSO_CLIENT_VERSION, "2.0.0-rc1");
        let cfg = super::ProxyRuntimeConfig::default();
        assert_eq!(cfg.client_version, "2.0.0-rc1");
    }

    #[test]
    fn detects_loopback_hosts() {
        assert!(is_loopback_host("127.0.0.1"));
        assert!(is_loopback_host("localhost"));
        assert!(!is_loopback_host("0.0.0.0"));
    }
}
