//! Login notes window: a separate, non-modal, always-on-top window listing the
//! notes for SSO logins until the user acknowledges them. The login itself is
//! never held; this only displays what `login_auth_response.notes` carried.

use std::time::{SystemTime, UNIX_EPOCH};

use runtime::LoginNotes;
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, UserAttentionType, WebviewUrl, WebviewWindowBuilder};
use tracing::warn;

use crate::notifications::send_notification;

pub const LOGIN_NOTES_WINDOW: &str = "login-notes";
pub const LOGIN_NOTES_UPDATED_EVENT: &str = "login-notes-updated";
/// Oldest unacknowledged logins are dropped past this many.
const MAX_PENDING: usize = 20;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CharacterNote {
    pub name: String,
    pub notes: String,
    /// The EQ username typed at login was this character's name.
    pub typed: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct LoginNotesEntry {
    pub id: u64,
    pub username: String,
    pub account: String,
    pub account_notes: Option<String>,
    pub characters: Vec<CharacterNote>,
    pub received_at_ms: u64,
}

#[derive(Debug, Default)]
pub struct LoginNotesQueue {
    next_id: u64,
    entries: Vec<LoginNotesEntry>,
}

impl LoginNotesQueue {
    pub fn push(
        &mut self,
        username: &str,
        account: &str,
        notes: &LoginNotes,
        received_at_ms: u64,
    ) -> &LoginNotesEntry {
        self.next_id += 1;
        let entry = build_entry(self.next_id, username, account, notes, received_at_ms);
        self.entries.push(entry);
        if self.entries.len() > MAX_PENDING {
            let excess = self.entries.len() - MAX_PENDING;
            self.entries.drain(..excess);
        }
        self.entries.last().expect("just pushed")
    }

    /// Pending entries, newest first.
    pub fn entries(&self) -> Vec<LoginNotesEntry> {
        self.entries.iter().rev().cloned().collect()
    }

    pub fn clear(&mut self) {
        self.entries.clear();
    }
}

fn build_entry(
    id: u64,
    username: &str,
    account: &str,
    notes: &LoginNotes,
    received_at_ms: u64,
) -> LoginNotesEntry {
    let mut characters: Vec<CharacterNote> = notes
        .characters
        .iter()
        .filter(|(_, text)| !text.trim().is_empty())
        .map(|(name, text)| CharacterNote {
            name: name.clone(),
            notes: text.trim().to_string(),
            typed: name.eq_ignore_ascii_case(username),
        })
        .collect();
    characters.sort_by(|a, b| {
        b.typed
            .cmp(&a.typed)
            .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });
    LoginNotesEntry {
        id,
        username: username.to_string(),
        account: account.to_string(),
        account_notes: notes
            .account
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string),
        characters,
        received_at_ms,
    }
}

pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or_default()
}

/// Show (or raise) the notes window and tell it to reload its entries.
pub fn show_login_notes_window(app: &AppHandle, entry: &LoginNotesEntry) {
    send_notification(
        app,
        "Login Notes",
        &format!("{} has notes. See the Login Notes window.", entry.account),
    );

    if let Some(window) = app.get_webview_window(LOGIN_NOTES_WINDOW) {
        let _ = window.unminimize();
        let _ = window.show();
        // Toggling re-asserts the topmost z-order above windows raised since it opened.
        let _ = window.set_always_on_top(false);
        let _ = window.set_always_on_top(true);
        let _ = window.set_focus();
        let _ = window.request_user_attention(Some(UserAttentionType::Critical));
        let _ = app.emit_to(LOGIN_NOTES_WINDOW, LOGIN_NOTES_UPDATED_EVENT, ());
        return;
    }

    match WebviewWindowBuilder::new(app, LOGIN_NOTES_WINDOW, WebviewUrl::default())
        .title("Login Notes")
        .inner_size(480.0, 380.0)
        .min_inner_size(360.0, 240.0)
        .always_on_top(true)
        .center()
        .focused(true)
        .resizable(true)
        .build()
    {
        Ok(window) => {
            let _ = window.request_user_attention(Some(UserAttentionType::Critical));
        }
        Err(e) => warn!("failed to open login notes window: {e}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn notes(account: Option<&str>, chars: &[(&str, &str)]) -> LoginNotes {
        LoginNotes {
            account: account.map(str::to_string),
            characters: chars
                .iter()
                .map(|(n, t)| (n.to_string(), t.to_string()))
                .collect(),
        }
    }

    #[test]
    fn typed_character_sorts_first_and_is_flagged() {
        let mut queue = LoginNotesQueue::default();
        let entry = queue.push(
            "zzzz",
            "realbot01",
            &notes(
                Some(" Shared bot "),
                &[
                    ("Alpha", "a note"),
                    ("Zzzz", "Kael factioned"),
                    ("Blank", "  "),
                ],
            ),
            1,
        );
        assert_eq!(entry.account_notes.as_deref(), Some("Shared bot"));
        let names: Vec<_> = entry.characters.iter().map(|c| c.name.as_str()).collect();
        assert_eq!(names, vec!["Zzzz", "Alpha"]);
        assert!(entry.characters[0].typed);
        assert!(!entry.characters[1].typed);
    }

    #[test]
    fn entries_are_newest_first_and_capped() {
        let mut queue = LoginNotesQueue::default();
        for i in 0..(MAX_PENDING + 5) {
            queue.push(
                &format!("user{i}"),
                "acct",
                &notes(Some("n"), &[]),
                i as u64,
            );
        }
        let entries = queue.entries();
        assert_eq!(entries.len(), MAX_PENDING);
        assert_eq!(entries[0].username, format!("user{}", MAX_PENDING + 4));
        assert!(entries[0].id > entries[1].id);
        queue.clear();
        assert!(queue.entries().is_empty());
    }
}
