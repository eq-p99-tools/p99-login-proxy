use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::RwLock;

use keyring::Entry;
use proxy_core::{config_file_path, scrub_proxyconfig_tokens, ConfigFileV1};
use secrecy::{ExposeSecret, SecretString};
use thiserror::Error;
use tracing::warn;

#[derive(Debug, Error)]
pub enum SecretError {
    #[error("secret service unavailable")]
    Unavailable,
    #[error("not found")]
    NotFound,
    #[error("io error: {0}")]
    Io(String),
}

pub trait SecretStore: Send + Sync {
    fn store_token(&self, backend: &str, token: &str) -> Result<(), SecretError>;
    fn load_token(&self, backend: &str) -> Result<Option<SecretString>, SecretError>;
    fn clear_token(&self, backend: &str) -> Result<(), SecretError>;
    fn has_token(&self, backend: &str) -> bool;
}

/// Session-only store when OS credential service is unavailable.
#[derive(Debug, Default)]
pub struct SessionSecretStore {
    tokens: RwLock<HashMap<String, SecretString>>,
}

impl SecretStore for SessionSecretStore {
    fn store_token(&self, backend: &str, token: &str) -> Result<(), SecretError> {
        self.tokens
            .write()
            .unwrap()
            .insert(backend.to_string(), SecretString::from(token.to_string()));
        Ok(())
    }

    fn load_token(&self, backend: &str) -> Result<Option<SecretString>, SecretError> {
        Ok(self
            .tokens
            .read()
            .unwrap()
            .get(backend)
            .map(|s| SecretString::from(s.expose_secret().to_string())))
    }

    fn clear_token(&self, backend: &str) -> Result<(), SecretError> {
        self.tokens.write().unwrap().remove(backend);
        Ok(())
    }

    fn has_token(&self, backend: &str) -> bool {
        self.tokens.read().unwrap().contains_key(backend)
    }
}

const KEYRING_SERVICE: &str = "com.p99loginproxy";

fn keyring_entry(backend: &str) -> Result<Entry, SecretError> {
    Entry::new(KEYRING_SERVICE, &format!("sso:{backend}")).map_err(|_| SecretError::Unavailable)
}

/// OS keyring-backed token store.
#[derive(Debug, Default)]
pub struct KeyringSecretStore;

impl SecretStore for KeyringSecretStore {
    fn store_token(&self, backend: &str, token: &str) -> Result<(), SecretError> {
        keyring_entry(backend)?
            .set_password(token)
            .map_err(|e| SecretError::Io(e.to_string()))
    }

    fn load_token(&self, backend: &str) -> Result<Option<SecretString>, SecretError> {
        match keyring_entry(backend)?.get_password() {
            Ok(value) if !value.is_empty() => Ok(Some(SecretString::from(value))),
            Ok(_) => Ok(None),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(e) => Err(SecretError::Io(e.to_string())),
        }
    }

    fn clear_token(&self, backend: &str) -> Result<(), SecretError> {
        match keyring_entry(backend)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(e) => Err(SecretError::Io(e.to_string())),
        }
    }

    fn has_token(&self, backend: &str) -> bool {
        self.load_token(backend)
            .ok()
            .flatten()
            .is_some_and(|t| !t.expose_secret().is_empty())
    }
}

/// Persistent store: memory cache plus the OS keyring.
#[derive(Debug)]
pub struct PersistentSecretStore {
    session: SessionSecretStore,
    keyring: KeyringSecretStore,
    config_path: Option<PathBuf>,
}

impl Default for PersistentSecretStore {
    fn default() -> Self {
        Self::new(config_file_path())
    }
}

impl PersistentSecretStore {
    pub fn new(config_path: Option<PathBuf>) -> Self {
        Self {
            session: SessionSecretStore::default(),
            keyring: KeyringSecretStore,
            config_path,
        }
    }

    /// Migrate legacy plaintext INI/TOML tokens into the keyring, then scrub the
    /// portable INI. Existing keyring values always win.
    pub fn bootstrap_from_config(&self, api_tokens: &HashMap<String, String>) {
        self.migrate_from_config_with(api_tokens, &self.keyring);
    }

    fn migrate_from_config_with(
        &self,
        api_tokens: &HashMap<String, String>,
        persistent_store: &dyn SecretStore,
    ) {
        let mut all_persisted = true;
        for (backend, token) in api_tokens {
            if token.trim().is_empty() {
                continue;
            }
            let _ = self.session.store_token(backend, token);
            match persistent_store.load_token(backend) {
                Ok(Some(existing)) => {
                    let _ = self.session.store_token(backend, existing.expose_secret());
                }
                Ok(None) => {
                    if let Err(error) = persistent_store.store_token(backend, token) {
                        all_persisted = false;
                        warn!(backend, %error, "could not migrate legacy token to OS keyring");
                    }
                }
                Err(error) => {
                    all_persisted = false;
                    warn!(backend, %error, "could not inspect OS keyring during token migration");
                }
            }
        }

        if all_persisted && !api_tokens.is_empty() {
            if let Some(path) = self.config_path.as_ref() {
                let scrubbed = ConfigFileV1 {
                    api_tokens: HashMap::new(),
                    ..proxy_core::load_config_file(path).unwrap_or_default()
                };
                if let Err(error) = scrub_proxyconfig_tokens(path, &scrubbed) {
                    warn!(%error, path = %path.display(), "failed to scrub plaintext tokens from INI");
                }
            }
        }
    }

    pub fn bootstrap_from_keyring(&self, backends: &[String]) {
        for backend in backends {
            if self.session.has_token(backend) {
                continue;
            }
            if let Ok(Some(token)) = self.keyring.load_token(backend) {
                let _ = self.session.store_token(backend, token.expose_secret());
            }
        }
    }
}

impl SecretStore for PersistentSecretStore {
    fn store_token(&self, backend: &str, token: &str) -> Result<(), SecretError> {
        self.session.store_token(backend, token)?;
        if let Err(e) = self.keyring.store_token(backend, token) {
            warn!(backend, error = %e, "keyring store failed; token is session-only");
        }
        Ok(())
    }

    fn load_token(&self, backend: &str) -> Result<Option<SecretString>, SecretError> {
        if let Ok(Some(token)) = self.session.load_token(backend) {
            return Ok(Some(token));
        }
        if let Ok(Some(token)) = self.keyring.load_token(backend) {
            let _ = self.session.store_token(backend, token.expose_secret());
            return Ok(Some(token));
        }
        Ok(None)
    }

    fn clear_token(&self, backend: &str) -> Result<(), SecretError> {
        self.session.clear_token(backend)?;
        let _ = self.keyring.clear_token(backend);
        Ok(())
    }

    fn has_token(&self, backend: &str) -> bool {
        self.load_token(backend)
            .ok()
            .flatten()
            .is_some_and(|t| !t.expose_secret().is_empty())
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    #[test]
    fn bootstrap_from_config_marks_backend_as_having_token() {
        let mut api_tokens = HashMap::new();
        api_tokens.insert(
            "Marginal Threat".to_string(),
            "SealNonchalantSide".to_string(),
        );
        api_tokens.insert(
            "Localhost".to_string(),
            "ReportFrailTrailSticky".to_string(),
        );

        let store = PersistentSecretStore::new(None);
        let migration_store = SessionSecretStore::default();
        store.migrate_from_config_with(&api_tokens, &migration_store);

        assert!(store.has_token("Marginal Threat"));
        assert!(store.has_token("Localhost"));
    }

    #[test]
    fn scrubs_tokens_from_ini_after_bootstrap() {
        let raw = r#"[DEFAULT]
sso_api_name = Marginal Threat
user_api_token = SealNonchalantSide

[api_tokens]
Marginal Threat = SealNonchalantSide
Localhost = ReportFrailTrailSticky
"#;
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("proxyconfig.ini");
        std::fs::write(&path, raw).unwrap();

        let file = proxy_core::load_config_file(&path).unwrap();
        let store = PersistentSecretStore::new(Some(path.clone()));
        let migration_store = SessionSecretStore::default();
        store.migrate_from_config_with(&file.api_tokens, &migration_store);

        assert!(store.has_token(&file.sso_backend));
        assert!(store.has_token("Localhost"));
        let written = std::fs::read_to_string(path).unwrap();
        assert!(!written.contains("user_api_token"));
        assert!(!written.contains("SealNonchalantSide"));
        assert!(!written.contains("ReportFrailTrailSticky"));
    }
}
