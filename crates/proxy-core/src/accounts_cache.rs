use std::collections::HashSet;

use serde_json::{Map, Value};

/// Cached SSO account names mirrored from Python ``ALL_CACHED_NAMES`` / ``CHARACTERS_CACHED``.
#[derive(Debug, Default, Clone)]
pub struct AccountCache {
    pub account_tree: Value,
    pub dynamic_tag_names: Vec<String>,
    pub all_cached_names: HashSet<String>,
    pub characters_cached: HashSet<String>,
    pub account_count: usize,
}

impl AccountCache {
    pub fn from_full_state(msg: &Value) -> Self {
        let tree = msg
            .get("account_tree")
            .cloned()
            .unwrap_or(Value::Object(Map::new()));
        let zones = string_array(msg.get("dynamic_tag_zones"));
        let classes = string_array(msg.get("dynamic_tag_classes"));
        Self::from_parts(&tree, &zones, &classes)
    }

    /// Build the cache from already-parsed ``full_state`` components.
    pub fn from_parts(
        account_tree: &Value,
        dynamic_tag_zones: &[String],
        dynamic_tag_classes: &[String],
    ) -> Self {
        let dynamic_tags = build_dynamic_tag_names(dynamic_tag_zones, dynamic_tag_classes);
        Self::rebuild_from_tree(account_tree, &dynamic_tags)
    }

    pub fn rebuild_from_tree(account_tree: &Value, dynamic_tag_names: &[String]) -> Self {
        let mut all_names = HashSet::new();
        let mut characters = HashSet::new();
        let count = account_tree.as_object().map(|o| o.len()).unwrap_or(0);

        if let Some(tree) = account_tree.as_object() {
            for (acct_name, data) in tree {
                all_names.insert(acct_name.to_lowercase());
                if let Some(aliases) = data.get("aliases").and_then(Value::as_array) {
                    for alias in aliases {
                        if let Some(s) = alias.as_str() {
                            all_names.insert(s.to_lowercase());
                        }
                    }
                }
                if let Some(tags) = data.get("tags").and_then(Value::as_array) {
                    for tag in tags {
                        if let Some(s) = tag.as_str() {
                            all_names.insert(s.to_lowercase());
                        }
                    }
                }
                if let Some(chars) = data.get("characters").and_then(Value::as_object) {
                    for name in chars.keys() {
                        let lc = name.to_lowercase();
                        all_names.insert(lc.clone());
                        characters.insert(lc);
                    }
                }
            }
        }

        for name in dynamic_tag_names {
            all_names.insert(name.to_lowercase());
        }

        Self {
            account_tree: account_tree.clone(),
            dynamic_tag_names: dynamic_tag_names.to_vec(),
            all_cached_names: all_names,
            characters_cached: characters,
            account_count: count,
        }
    }

    pub fn apply_delta(&mut self, delta: &Value) {
        if let Some(changes) = delta.get("changes") {
            self.apply_delta_changes(changes);
        }
    }

    /// Apply the ``changes`` array from a WS ``delta`` message.
    pub fn apply_delta_changes(&mut self, changes: &Value) {
        let mut tree = self.account_tree.clone();
        apply_changes_to_tree(&mut tree, changes);
        *self = Self::rebuild_from_tree(&tree, &self.dynamic_tag_names);
    }

    pub fn contains_name(&self, name: &str) -> bool {
        self.all_cached_names.contains(&name.to_lowercase())
    }
}

/// Apply incremental WS ``delta`` changes (Python ``_apply_delta``).
pub fn apply_delta_to_tree(tree: &mut Value, delta: &Value) {
    if let Some(changes) = delta.get("changes") {
        apply_changes_to_tree(tree, changes);
    }
}

/// Apply a WS ``changes`` array (from a ``delta`` message) to an account tree.
pub fn apply_changes_to_tree(tree: &mut Value, changes: &Value) {
    let Some(obj) = tree.as_object_mut() else {
        return;
    };
    let Some(changes) = changes.as_array() else {
        return;
    };

    for change in changes {
        let Some(action) = change.get("action").and_then(Value::as_str) else {
            continue;
        };
        let Some(account) = change.get("account").and_then(Value::as_str) else {
            continue;
        };

        match action {
            "add" => {
                if let Some(data) = change.get("data") {
                    obj.insert(account.to_string(), data.clone());
                }
            }
            "remove" => {
                obj.remove(account);
            }
            "update" => {
                let mut entry = obj
                    .get(account)
                    .cloned()
                    .unwrap_or_else(|| Value::Object(Map::new()));
                if let Some(fields) = change.get("fields").and_then(Value::as_object) {
                    if let Some(entry_obj) = entry.as_object_mut() {
                        for list_field in ["aliases", "tags"] {
                            if let Some(diff) = fields.get(list_field).and_then(Value::as_object) {
                                let mut current: HashSet<String> = entry_obj
                                    .get(list_field)
                                    .and_then(Value::as_array)
                                    .map(|arr| {
                                        arr.iter()
                                            .filter_map(|v| v.as_str().map(str::to_string))
                                            .collect()
                                    })
                                    .unwrap_or_default();
                                if let Some(add) = diff.get("add").and_then(Value::as_array) {
                                    for v in add {
                                        if let Some(s) = v.as_str() {
                                            current.insert(s.to_string());
                                        }
                                    }
                                }
                                if let Some(remove) = diff.get("remove").and_then(Value::as_array) {
                                    for v in remove {
                                        if let Some(s) = v.as_str() {
                                            current.remove(s);
                                        }
                                    }
                                }
                                let mut sorted: Vec<_> = current.into_iter().collect();
                                sorted.sort();
                                entry_obj.insert(
                                    list_field.to_string(),
                                    Value::Array(sorted.into_iter().map(Value::String).collect()),
                                );
                            }
                        }

                        if let Some(char_diff) = fields.get("characters").and_then(Value::as_object)
                        {
                            let mut chars = entry_obj
                                .get("characters")
                                .and_then(Value::as_object)
                                .cloned()
                                .unwrap_or_default();
                            if let Some(add) = char_diff.get("add").and_then(Value::as_object) {
                                for (name, cdata) in add {
                                    chars.insert(name.clone(), cdata.clone());
                                }
                            }
                            if let Some(remove) = char_diff.get("remove").and_then(Value::as_array)
                            {
                                for v in remove {
                                    if let Some(name) = v.as_str() {
                                        chars.remove(name);
                                    }
                                }
                            }
                            if let Some(update) = char_diff.get("update").and_then(Value::as_object)
                            {
                                for (name, cdata) in update {
                                    chars.insert(name.clone(), cdata.clone());
                                }
                            }
                            entry_obj.insert("characters".to_string(), Value::Object(chars));
                        }

                        for scalar in ["last_login", "last_login_by", "active_character"] {
                            if let Some(v) = fields.get(scalar) {
                                entry_obj.insert(scalar.to_string(), v.clone());
                            }
                        }
                    }
                }
                obj.insert(account.to_string(), entry);
            }
            _ => {}
        }
    }
}

fn string_array(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

/// Build dynamic tag names from zone/class lists (Python ``get_dynamic_tag_list``).
pub fn build_dynamic_tag_names(zones: &[String], classes: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    for zone in zones {
        for class in classes {
            out.push(format!("{zone}_{class}"));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn delta_add_and_remove() {
        let mut tree = json!({});
        apply_delta_to_tree(
            &mut tree,
            &json!({
                "changes": [
                    { "action": "add", "account": "acct1", "data": { "aliases": ["a1"] } }
                ]
            }),
        );
        assert!(tree.get("acct1").is_some());
        apply_delta_to_tree(
            &mut tree,
            &json!({ "changes": [{ "action": "remove", "account": "acct1" }] }),
        );
        assert!(tree.get("acct1").is_none());
    }

    #[test]
    fn rebuild_tracks_aliases() {
        let tree = json!({ "main": { "aliases": ["Alias1"], "characters": { "Bob": {} } } });
        let cache = AccountCache::rebuild_from_tree(&tree, &[]);
        assert!(cache.contains_name("alias1"));
        assert!(cache.contains_name("bob"));
        assert_eq!(cache.account_count, 1);
    }
}
