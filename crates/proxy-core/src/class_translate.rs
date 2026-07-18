use std::collections::HashMap;
use std::sync::LazyLock;

pub const CLASSES: &[&str] = &[
    "Bard",
    "Cleric",
    "Druid",
    "Enchanter",
    "Magician",
    "Monk",
    "Necromancer",
    "Paladin",
    "Ranger",
    "Rogue",
    "ShadowKnight",
    "Shaman",
    "Warrior",
    "Wizard",
];

static BASE_CLASS_ALIASES: LazyLock<HashMap<String, String>> = LazyLock::new(|| {
    let mut map = HashMap::new();
    for class in CLASSES {
        map.insert(class.to_lowercase(), (*class).to_string());
    }
    map.insert("shadow knight".to_string(), "ShadowKnight".to_string());
    map
});

static TITLE_TO_BASE_CLASS: LazyLock<HashMap<String, String>> = LazyLock::new(|| {
    [
        ("minstrel", "Bard"),
        ("troubadour", "Bard"),
        ("virtuoso", "Bard"),
        ("vicar", "Cleric"),
        ("templar", "Cleric"),
        ("high priest", "Cleric"),
        ("wanderer", "Druid"),
        ("preserver", "Druid"),
        ("hierophant", "Druid"),
        ("illusionist", "Enchanter"),
        ("beguiler", "Enchanter"),
        ("phantasmist", "Enchanter"),
        ("elementalist", "Magician"),
        ("conjurer", "Magician"),
        ("arch mage", "Magician"),
        ("disciple", "Monk"),
        ("master", "Monk"),
        ("grandmaster", "Monk"),
        ("heretic", "Necromancer"),
        ("defiler", "Necromancer"),
        ("warlock", "Necromancer"),
        ("cavalier", "Paladin"),
        ("knight", "Paladin"),
        ("crusader", "Paladin"),
        ("pathfinder", "Ranger"),
        ("outrider", "Ranger"),
        ("warder", "Ranger"),
        ("rake", "Rogue"),
        ("blackguard", "Rogue"),
        ("assassin", "Rogue"),
        ("reaver", "ShadowKnight"),
        ("revenant", "ShadowKnight"),
        ("grave lord", "ShadowKnight"),
        ("mystic", "Shaman"),
        ("luminary", "Shaman"),
        ("oracle", "Shaman"),
        ("champion", "Warrior"),
        ("myrmidon", "Warrior"),
        ("warlord", "Warrior"),
        ("channeler", "Wizard"),
        ("evoker", "Wizard"),
        ("sorcerer", "Wizard"),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v.to_string()))
    .collect()
});

/// Normalize a /who class or title string to a canonical class key.
pub fn resolve_class(raw: &str) -> Option<String> {
    let key = raw
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase();
    if key.is_empty() {
        return None;
    }
    BASE_CLASS_ALIASES
        .get(&key)
        .or_else(|| TITLE_TO_BASE_CLASS.get(&key))
        .cloned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_base_class() {
        assert_eq!(resolve_class("Warrior").as_deref(), Some("Warrior"));
    }

    #[test]
    fn resolves_title() {
        assert_eq!(resolve_class("Warlord").as_deref(), Some("Warrior"));
    }

    #[test]
    fn resolves_shadow_knight() {
        assert_eq!(
            resolve_class("Shadow Knight").as_deref(),
            Some("ShadowKnight")
        );
    }
}
