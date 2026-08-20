use std::collections::HashMap;

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
