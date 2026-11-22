use std::collections::{BTreeMap, HashMap};

use proxy_core::model::ProxyLifecycle;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProxyStatus {
    pub lifecycle: ProxyLifecycle,
    pub listen_address: String,
    pub client_connected: bool,
    pub packets_forwarded: u64,
}

impl Default for ProxyStatus {
    fn default() -> Self {
        Self {
            lifecycle: ProxyLifecycle::Stopped,
            listen_address: "127.0.0.1:5998".to_string(),
            client_connected: false,
            packets_forwarded: 0,
        }
    }
}

/// Login notes the server returned for the account a `login_auth` resolved to
/// (`login_auth_response.notes`). Plain text; never render as markup.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct LoginNotes {
    #[serde(default)]
    pub account: Option<String>,
    #[serde(default)]
    pub characters: BTreeMap<String, String>,
}

impl LoginNotes {
    pub fn is_empty(&self) -> bool {
        self.account.as_deref().is_none_or(|s| s.trim().is_empty())
            && self.characters.values().all(|s| s.trim().is_empty())
    }
}

/// Severity of a popup; picks its icon and styling.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ModalLevel {
    #[default]
    Info,
    Warning,
    Error,
}

impl ModalLevel {
    /// Unknown or missing levels fall back to `Info` so a newer server never
    /// breaks an older client.
    pub fn from_wire(raw: Option<&str>) -> Self {
        match raw {
            Some("warning") => Self::Warning,
            Some("error") => Self::Error,
            _ => Self::Info,
        }
    }
}

/// A popup the server asked for with a `show_modal` message. Plain text.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ServerModal {
    /// Lets the client drop a repeat of a popup that is still pending.
    pub id: Option<String>,
    pub title: String,
    pub message: String,
    pub level: ModalLevel,
    /// Show in a separate window that stays above other windows (including EQ
    /// in windowed mode) instead of a dialog inside the proxy window.
    pub always_on_top: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum AppEvent {
    StateSnapshot {
        bootstrap: proxy_core::model::BootstrapState,
    },
    ProxyStatus {
        status: ProxyStatus,
    },
    UserConnected {
        endpoint: String,
    },
    AuthRejected {
        username: String,
        reason: String,
    },
    RustleWarning {
        message: String,
    },
    Activity {
        message: String,
    },
    LoginProxied {
        alias: String,
        account: String,
        method: String,
    },
    /// An SSO login whose resolved account has notes. Emitted after the login
    /// packet is forwarded; the login is never held for it.
    LoginNotes {
        username: String,
        account: String,
        notes: LoginNotes,
    },
    /// The server sent a `show_modal` message.
    ShowModal {
        modal: ServerModal,
    },
    LocalCharacterUpdate {
        name: String,
        park: Option<String>,
        bind: Option<String>,
        level: Option<i32>,
        class: Option<String>,
        items: Option<HashMap<String, Value>>,
    },
    LogFileSwitched {
        character: String,
    },
    StatsDirty,
    ConnectionStarted,
    ConnectionCompleted,
}
