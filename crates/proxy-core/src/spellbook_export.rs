//! EQ `/outputfile spellbook` exports (`<Char>-Spellbook.txt`). The proxy sends
//! the raw text to the SSO server and never parses it locally.

use std::path::Path;

use crate::inventory_parser::character_name_from_export_path;

const SPELLBOOK_SUFFIX: &str = "-spellbook.txt";

/// Server drops spellbook text larger than this. Matches
/// `MAX_SPELLBOOK_TEXT_BYTES` in roboToald.
pub const MAX_SPELLBOOK_TEXT_BYTES: usize = 128 * 1024;

pub fn character_name_from_spellbook_path(path: &Path) -> Option<String> {
    character_name_from_export_path(path, SPELLBOOK_SUFFIX)
}

pub fn is_spellbook_file(path: &Path) -> bool {
    character_name_from_spellbook_path(path).is_some()
}

/// Raw export text to put on `update_spellbook`, or `None` when there is
/// nothing to send. Blank and oversized files are skipped so the stored server
/// spellbook stays as it was.
pub fn spellbook_export_to_send(text: &str) -> Option<&str> {
    if text.trim().is_empty() || text.len() > MAX_SPELLBOOK_TEXT_BYTES {
        None
    } else {
        Some(text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const P99_SAMPLE: &str = include_str!("../tests/data/p99-spellbook-sample.txt");

    #[test]
    fn character_name_comes_from_file_name() {
        assert_eq!(
            character_name_from_spellbook_path(Path::new("/eq/Zzzz-Spellbook.txt")).as_deref(),
            Some("Zzzz")
        );
        assert_eq!(
            character_name_from_spellbook_path(Path::new("Zzzz-spellbook.TXT")).as_deref(),
            Some("Zzzz")
        );
        assert!(!is_spellbook_file(Path::new("/eq/-Spellbook.txt")));
        assert!(!is_spellbook_file(Path::new("/eq/Zzzz-Inventory.txt")));
        assert!(!is_spellbook_file(Path::new("/eq/myspells.txt")));
    }

    #[test]
    fn real_p99_export_is_sent_verbatim() {
        assert_eq!(P99_SAMPLE.lines().count(), 21);
        assert_eq!(spellbook_export_to_send(P99_SAMPLE), Some(P99_SAMPLE));
    }

    #[test]
    fn blank_or_oversized_exports_are_not_sent() {
        assert_eq!(spellbook_export_to_send(" \n\t\n"), None);
        let huge = "1\tGate\n".repeat(MAX_SPELLBOOK_TEXT_BYTES / 7 + 1);
        assert_eq!(spellbook_export_to_send(&huge), None);
    }
}
