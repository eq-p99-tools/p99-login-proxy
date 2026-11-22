//! Every popup the app shows goes through [`present_modal`]: server `show_modal`
//! messages, login notes from `login_auth_response`, and local errors and
//! warnings (rejected logins, Rustle UI). Popups with `always_on_top` queue in a
//! separate topmost window until acknowledged; the rest go to the main window's
//! in-app dialog. A login is never held for a popup.

use std::sync::Mutex as StdMutex;
use std::time::{SystemTime, UNIX_EPOCH};

use runtime::{LoginNotes, ModalLevel, ServerModal};
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, UserAttentionType, WebviewUrl, WebviewWindowBuilder};
use tracing::warn;

use crate::notifications::send_notification;

pub const MODAL_WINDOW: &str = "modal";
/// Tells the topmost window to reload its queue.
pub const MODALS_UPDATED_EVENT: &str = "modals-updated";
/// Carries one [`ModalEntry`] to the main window's in-app dialog.
pub const SHOW_MODAL_EVENT: &str = "show-modal";
/// Oldest unacknowledged topmost popups are dropped past this many.
const MAX_PENDING: usize = 20;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CharacterNote {
    pub name: String,
    pub notes: String,
    /// The EQ username typed at login was this character's name.
    pub typed: bool,
}

/// What a popup shows. Always plain text; the UI never renders markup.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ModalBody {
    Text {
        message: String,
    },
    LoginNotes {
        username: String,
        account: String,
        account_notes: Option<String>,
        characters: Vec<CharacterNote>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModalRequest {
    pub title: String,
    pub level: ModalLevel,
    pub always_on_top: bool,
    /// A request whose id matches a still-pending popup is dropped.
    pub dedupe_id: Option<String>,
    pub body: ModalBody,
}

impl ModalRequest {
    /// An in-app dialog with a plain message.
    pub fn text(title: &str, message: &str, level: ModalLevel) -> Self {
        Self {
            title: title.to_string(),
            level,
            always_on_top: false,
            dedupe_id: None,
            body: ModalBody::Text {
                message: message.to_string(),
            },
        }
    }

    pub fn from_server(modal: &ServerModal) -> Self {
        Self {
            title: modal.title.clone(),
            level: modal.level,
            always_on_top: modal.always_on_top,
            dedupe_id: modal.id.clone(),
            body: ModalBody::Text {
                message: modal.message.clone(),
            },
        }
    }

    /// Login notes always stay on top: they matter while EQ has focus.
    pub fn login_notes(username: &str, account: &str, notes: &LoginNotes) -> Self {
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
        Self {
            title: format!("Login notes: {account}"),
            level: ModalLevel::Info,
            always_on_top: true,
            dedupe_id: None,
            body: ModalBody::LoginNotes {
                username: username.to_string(),
                account: account.to_string(),
                account_notes: notes
                    .account
                    .as_deref()
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                    .map(str::to_string),
                characters,
            },
        }
    }

    /// One line for the tray notification that accompanies a topmost popup.
    fn notification_text(&self) -> String {
        match &self.body {
            ModalBody::LoginNotes { account, .. } => {
                format!("{account} has notes. See the popup window.")
            }
            ModalBody::Text { message } => message.lines().next().unwrap_or_default().to_string(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ModalEntry {
    pub id: u64,
    pub title: String,
    pub level: ModalLevel,
    pub always_on_top: bool,
    pub dedupe_id: Option<String>,
    pub body: ModalBody,
    pub received_at_ms: u64,
}

/// Assigns ids and holds the topmost popups until they are acknowledged.
#[derive(Debug, Default)]
pub struct ModalQueue {
    next_id: u64,
    pending: Vec<ModalEntry>,
}

impl ModalQueue {
    /// Turn a request into an entry; topmost entries are also queued. `None`
    /// when a pending topmost entry already has the same dedupe id.
    pub fn push(&mut self, request: ModalRequest, received_at_ms: u64) -> Option<ModalEntry> {
        if let Some(key) = request.dedupe_id.as_deref() {
            if self
                .pending
                .iter()
                .any(|e| e.dedupe_id.as_deref() == Some(key))
            {
                return None;
            }
        }
        self.next_id += 1;
        let entry = ModalEntry {
            id: self.next_id,
            title: request.title,
            level: request.level,
            always_on_top: request.always_on_top,
            dedupe_id: request.dedupe_id,
            body: request.body,
            received_at_ms,
        };
        if entry.always_on_top {
            self.pending.push(entry.clone());
            if self.pending.len() > MAX_PENDING {
                let excess = self.pending.len() - MAX_PENDING;
                self.pending.drain(..excess);
            }
        }
        Some(entry)
    }

    /// Pending topmost entries, newest first.
    pub fn entries(&self) -> Vec<ModalEntry> {
        self.pending.iter().rev().cloned().collect()
    }

    pub fn clear(&mut self) {
        self.pending.clear();
    }
}

pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or_default()
}

/// The single entry point for showing a popup.
pub fn present_modal(app: &AppHandle, queue: &StdMutex<ModalQueue>, request: ModalRequest) {
    let notification = request.notification_text();
    let Some(entry) = queue
        .lock()
        .expect("modal queue lock")
        .push(request, now_ms())
    else {
        return;
    };
    if entry.always_on_top {
        send_notification(app, &entry.title, &notification);
        show_modal_window(app);
    } else if let Err(e) = app.emit_to("main", SHOW_MODAL_EVENT, &entry) {
        warn!("failed to show popup in main window: {e}");
    }
}

/// Show (or raise) the topmost popup window and tell it to reload its queue.
fn show_modal_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MODAL_WINDOW) {
        let _ = window.unminimize();
        let _ = window.show();
        // Toggling re-asserts the topmost z-order above windows raised since it opened.
        let _ = window.set_always_on_top(false);
        let _ = window.set_always_on_top(true);
        let _ = window.set_focus();
        let _ = window.request_user_attention(Some(UserAttentionType::Critical));
        let _ = app.emit_to(MODAL_WINDOW, MODALS_UPDATED_EVENT, ());
        return;
    }

    match WebviewWindowBuilder::new(app, MODAL_WINDOW, WebviewUrl::default())
        .title("P99 Login Proxy")
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
        Err(e) => warn!("failed to open popup window: {e}"),
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
    fn login_notes_flag_and_sort_the_typed_character_first() {
        let request = ModalRequest::login_notes(
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
        );
        assert!(request.always_on_top);
        assert_eq!(request.level, ModalLevel::Info);
        let ModalBody::LoginNotes {
            account_notes,
            characters,
            ..
        } = request.body
        else {
            panic!("expected login notes body");
        };
        assert_eq!(account_notes.as_deref(), Some("Shared bot"));
        let names: Vec<_> = characters.iter().map(|c| c.name.as_str()).collect();
        assert_eq!(names, vec!["Zzzz", "Alpha"]);
        assert!(characters[0].typed);
        assert!(!characters[1].typed);
    }

    #[test]
    fn server_modal_keeps_level_placement_and_id() {
        let request = ModalRequest::from_server(&ServerModal {
            id: Some("maint-1".into()),
            title: "Maintenance".into(),
            message: "Down at 9pm".into(),
            level: ModalLevel::Warning,
            always_on_top: true,
        });
        assert_eq!(request.level, ModalLevel::Warning);
        assert!(request.always_on_top);
        assert_eq!(request.dedupe_id.as_deref(), Some("maint-1"));
    }

    #[test]
    fn only_topmost_entries_are_queued() {
        let mut queue = ModalQueue::default();
        let in_app = queue
            .push(
                ModalRequest::text("SSO Login Rejected", "denied", ModalLevel::Error),
                1,
            )
            .expect("entry");
        assert!(!in_app.always_on_top);
        assert!(queue.entries().is_empty());

        queue
            .push(
                ModalRequest::login_notes("a", "acct", &notes(Some("n"), &[])),
                2,
            )
            .expect("entry");
        assert_eq!(queue.entries().len(), 1);
    }

    #[test]
    fn pending_dedupe_id_drops_repeats_until_cleared() {
        let mut queue = ModalQueue::default();
        let modal = ServerModal {
            id: Some("x".into()),
            title: "T".into(),
            message: "M".into(),
            level: ModalLevel::Info,
            always_on_top: true,
        };
        assert!(queue.push(ModalRequest::from_server(&modal), 1).is_some());
        assert!(queue.push(ModalRequest::from_server(&modal), 2).is_none());
        queue.clear();
        assert!(queue.push(ModalRequest::from_server(&modal), 3).is_some());
    }

    #[test]
    fn entries_are_newest_first_and_capped() {
        let mut queue = ModalQueue::default();
        for i in 0..(MAX_PENDING + 5) {
            queue.push(
                ModalRequest::login_notes(&format!("user{i}"), "acct", &notes(Some("n"), &[])),
                i as u64,
            );
        }
        let entries = queue.entries();
        assert_eq!(entries.len(), MAX_PENDING);
        assert_eq!(entries[0].received_at_ms, (MAX_PENDING + 4) as u64);
        assert!(entries[0].id > entries[1].id);
        queue.clear();
        assert!(queue.entries().is_empty());
    }
}
