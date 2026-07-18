use std::collections::HashMap;
use std::sync::LazyLock;

static ZONE_ALIASES: LazyLock<HashMap<String, String>> = LazyLock::new(|| {
    let raw: HashMap<String, String> =
        serde_json::from_str(include_str!("zone_aliases.json")).expect("zone_aliases.json");
    raw.into_iter()
        .map(|(k, v)| (k.to_lowercase(), v))
        .collect()
});

/// Map a display zone name to the canonical zone key (Python ``zone_to_zonekey``).
pub fn zone_to_zonekey(zone: &str) -> Option<String> {
    let trimmed = zone.trim();
    if trimmed.is_empty() {
        return None;
    }
    let lc = trimmed.to_lowercase();
    Some(ZONE_ALIASES.get(&lc).cloned().unwrap_or(lc))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_known_alias() {
        assert_eq!(zone_to_zonekey("Kael Drakkel").as_deref(), Some("kael"));
    }

    #[test]
    fn falls_back_to_lower_slug() {
        assert_eq!(zone_to_zonekey("Some Zone").as_deref(), Some("some zone"));
    }
}
