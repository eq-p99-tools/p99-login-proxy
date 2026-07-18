use std::collections::HashMap;

use secrecy::{ExposeSecret, SecretString};

use crate::model::LocalAccount;

#[derive(Debug, Clone, Default)]
pub struct LocalAccountStore {
    by_alias: HashMap<String, (String, SecretString)>,
}

impl LocalAccountStore {
    pub fn from_rows(rows: impl IntoIterator<Item = (String, String, SecretString)>) -> Self {
        let mut store = Self::default();
        for (alias, username, password) in rows {
            store.insert(alias, username, password);
        }
        store
    }

    pub fn insert(&mut self, alias: String, username: String, password: SecretString) {
        let key = alias.to_lowercase();
        self.by_alias.insert(key, (username, password));
    }

    pub fn remove(&mut self, alias: &str) -> bool {
        self.by_alias.remove(&alias.to_lowercase()).is_some()
    }

    pub fn list(&self) -> Vec<LocalAccount> {
        self.by_alias
            .iter()
            .map(|(alias, (username, password))| LocalAccount {
                alias: alias.clone(),
                username: username.clone(),
                password: password.expose_secret().to_string(),
            })
            .collect()
    }

    pub fn resolve(&self, alias: &str) -> Option<(String, SecretString)> {
        self.by_alias
            .get(&alias.to_lowercase())
            .map(|(u, p)| (u.clone(), SecretString::from(p.expose_secret().to_string())))
    }

    pub fn contains_alias(&self, alias: &str) -> bool {
        self.by_alias.contains_key(&alias.to_lowercase())
    }

    /// Rows for CSV export: ``(account_name, password, aliases)``.
    pub fn rows_for_csv(&self) -> Vec<(String, String, Vec<String>)> {
        let listed = self.list();
        let mut users: std::collections::HashMap<String, (String, Vec<String>)> =
            std::collections::HashMap::new();
        for entry in listed {
            users.entry(entry.username.clone()).or_insert_with(|| {
                let password = self
                    .resolve(&entry.username)
                    .map(|(_, p)| p.expose_secret().to_string())
                    .unwrap_or_default();
                (password, Vec::new())
            });
            if entry.alias.to_lowercase() != entry.username.to_lowercase() {
                if let Some((_, aliases)) = users.get_mut(&entry.username) {
                    aliases.push(entry.alias);
                }
            }
        }
        users
            .into_iter()
            .map(|(name, (password, aliases))| (name, password, aliases))
            .collect()
    }
}
