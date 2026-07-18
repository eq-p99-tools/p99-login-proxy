use std::collections::HashMap;

use crate::model::LocalCharacter;

#[derive(Debug, Default, Clone)]
pub struct LocalCharacterStore {
    by_key: HashMap<String, LocalCharacter>,
}

fn char_key(name: &str, server: &str) -> String {
    format!("{}:{}", name.to_lowercase(), server.to_lowercase())
}

impl LocalCharacterStore {
    pub fn list(&self) -> Vec<LocalCharacter> {
        self.by_key.values().cloned().collect()
    }

    pub fn upsert(&mut self, character: LocalCharacter) -> Result<(), &'static str> {
        let key = char_key(&character.name, &character.server);
        if let Some(existing) = self.by_key.get(&key) {
            if existing.account_alias.to_lowercase() != character.account_alias.to_lowercase() {
                return Err("account conflict for character");
            }
        }
        self.by_key.insert(key, character);
        Ok(())
    }

    pub fn remove(&mut self, name: &str, server: &str) -> bool {
        self.by_key.remove(&char_key(name, server)).is_some()
    }

    pub fn find(&self, name: &str, server: &str) -> Option<&LocalCharacter> {
        self.by_key.get(&char_key(name, server))
    }

    pub fn contains_name(&self, name: &str) -> bool {
        self.find_by_name(name).is_some()
    }

    pub fn find_by_name(&self, name: &str) -> Option<&LocalCharacter> {
        let needle = name.to_lowercase();
        self.by_key
            .values()
            .find(|c| c.name.to_lowercase() == needle)
    }
}
