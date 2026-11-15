use std::collections::HashMap;
use std::path::Path;

use serde_json::{Map, Number, Value};
use tracing::warn;

const TRACKED_ITEMS: &[(&str, &str)] = &[
    ("Trakanon Idol", "seb"),
    ("Key of Veeshan", "vp"),
    ("Sleeper's Key", "st"),
    ("Box of the Void", "void"),
    ("Necklace of Resolution", "neck"),
    ("Vial of Velium Vapors", "thurg"),
    ("Reaper of the Dead", "reaper"),
    ("Shiny Brass Idol", "brass_idol"),
];

const COUNTED_ITEMS: &[(&str, &str)] = &[
    ("Lizard Blood Potion", "lizard"),
    ("Pearl", "pearl"),
    ("Peridot", "peridot"),
    ("Mana Battery - Class Three", "mb3"),
    ("Mana Battery - Class Four", "mb4"),
    ("Mana Battery - Class Five", "mb5"),
];

pub fn character_name_from_inventory_path(path: &Path) -> Option<String> {
    let name = path.file_name()?.to_str()?;
    let lower = name.to_ascii_lowercase();
    const SUFFIX: &str = "-inventory.txt";
    if !lower.ends_with(SUFFIX) {
        return None;
    }
    let stem = &name[..name.len() - SUFFIX.len()];
    if stem.is_empty() {
        None
    } else {
        Some(stem.to_string())
    }
}

pub fn is_inventory_file(path: &Path) -> bool {
    path.file_name()
        .and_then(|n| n.to_str())
        .is_some_and(|n| n.to_ascii_lowercase().ends_with("-inventory.txt"))
}

/// Server drops inventory text larger than this. Matches
/// `MAX_INVENTORY_TEXT_BYTES` in roboToald.
pub const MAX_INVENTORY_TEXT_BYTES: usize = 512 * 1024;

/// Raw export text to put on `update_location`, or `None` when there is nothing
/// to send. Blank and oversized files are skipped so stored server items stay
/// as they were.
pub fn inventory_export_to_send(text: &str) -> Option<&str> {
    if text.trim().is_empty() || text.len() > MAX_INVENTORY_TEXT_BYTES {
        None
    } else {
        Some(text)
    }
}

pub fn default_inventory_result() -> HashMap<String, Value> {
    let mut out = HashMap::new();
    for (_, wire) in TRACKED_ITEMS {
        out.insert((*wire).to_string(), Value::Bool(false));
    }
    for (_, wire) in COUNTED_ITEMS {
        out.insert((*wire).to_string(), Value::Number(0.into()));
    }
    out
}

pub fn parse_inventory_file(path: &Path) -> HashMap<String, Value> {
    let mut result = default_inventory_result();
    let Ok(raw) = std::fs::read_to_string(path) else {
        return result;
    };
    let mut lines = raw.lines();
    let Some(header_line) = lines.next() else {
        return result;
    };
    let headers: Vec<&str> = header_line.split('\t').collect();
    let Some(name_idx) = headers.iter().position(|h| h.eq_ignore_ascii_case("Name")) else {
        warn!(path = %path.display(), "inventory file missing Name column");
        return result;
    };
    let count_idx = headers.iter().position(|h| h.eq_ignore_ascii_case("Count"));
    if count_idx.is_none() {
        warn!(
            path = %path.display(),
            "inventory file missing Count column (stack totals will be 0)"
        );
    }

    for row in lines {
        let cols: Vec<&str> = row.split('\t').collect();
        if cols.len() <= name_idx {
            continue;
        }
        let cell = cols[name_idx].trim();
        for (item_name, wire) in TRACKED_ITEMS {
            if cell == *item_name {
                result.insert(wire.to_string(), Value::Bool(true));
            }
        }
        for (item_name, wire) in COUNTED_ITEMS {
            if cell != *item_name {
                continue;
            }
            let add = count_idx
                .and_then(|idx| cols.get(idx))
                .and_then(|c| c.trim().parse::<i64>().ok())
                .unwrap_or(0);
            let current = result.get(*wire).and_then(Value::as_i64).unwrap_or(0);
            result.insert(
                (*wire).to_string(),
                Value::Number(Number::from(current + add)),
            );
        }
    }
    result
}

pub fn inventory_items_json(flags: &HashMap<String, Value>) -> Map<String, Value> {
    flags.iter().map(|(k, v)| (k.clone(), v.clone())).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn parses_tracked_item() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("Bob-Inventory.txt");
        std::fs::write(&path, "Name\tCount\nTrakanon Idol\t1\n").unwrap();
        let flags = parse_inventory_file(&path);
        assert_eq!(flags.get("seb"), Some(&Value::Bool(true)));
    }

    #[test]
    fn blank_or_oversized_exports_are_not_sent() {
        assert_eq!(inventory_export_to_send("  \n"), None);
        let huge = "x".repeat(MAX_INVENTORY_TEXT_BYTES + 1);
        assert_eq!(inventory_export_to_send(&huge), None);
        assert_eq!(
            inventory_export_to_send("Name\tCount\n"),
            Some("Name\tCount\n")
        );
    }
}
