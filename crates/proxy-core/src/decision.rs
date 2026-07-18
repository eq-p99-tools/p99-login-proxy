use std::collections::HashSet;

use secrecy::SecretString;

use crate::accounts::LocalAccountStore;
use crate::accounts_cache::AccountCache;
use crate::characters::LocalCharacterStore;
use tracing::warn;

#[derive(Debug, Clone)]
pub enum CredentialDecision {
    Passthrough,
    LocalRewrite {
        username: String,
        password: SecretString,
    },
    SsoAuth {
        username: String,
    },
    SkipSsoPassthrough,
}

pub struct CredentialRouter<'a> {
    pub proxy_only: bool,
    pub skip_sso_accounts: &'a HashSet<String>,
    pub has_token: bool,
    pub accounts: &'a LocalAccountStore,
    pub characters: &'a LocalCharacterStore,
    pub cached_names: &'a AccountCache,
}

impl<'a> CredentialRouter<'a> {
    pub fn decide(
        &self,
        username: &str,
        password: &str,
        server: Option<&str>,
    ) -> CredentialDecision {
        let username = username.to_lowercase();

        if self.proxy_only {
            return CredentialDecision::Passthrough;
        }
        if self.skip_sso_accounts.contains(&username) {
            return CredentialDecision::SkipSsoPassthrough;
        }

        if let Some((u, p)) = self.accounts.resolve(&username) {
            return CredentialDecision::LocalRewrite {
                username: u,
                password: p,
            };
        }
        if let Some(ch) = server
            .and_then(|s| self.characters.find(&username, s))
            .or_else(|| self.characters.find_by_name(&username))
        {
            if let Some((u, p)) = self.accounts.resolve(&ch.account_alias) {
                return CredentialDecision::LocalRewrite {
                    username: u,
                    password: p,
                };
            }
            warn!(
                character = %username,
                account = %ch.account_alias,
                "Local character references unknown account; passing through"
            );
            return CredentialDecision::Passthrough;
        }

        let in_local =
            self.accounts.contains_alias(&username) || self.characters.contains_name(&username);
        if !self.cached_names.contains_name(&username) && !in_local {
            return CredentialDecision::Passthrough;
        }

        if username.is_empty() && password.is_empty() {
            return CredentialDecision::Passthrough;
        }

        if self.has_token && self.cached_names.contains_name(&username) {
            return CredentialDecision::SsoAuth { username };
        }

        CredentialDecision::Passthrough
    }
}
