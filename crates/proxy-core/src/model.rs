use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProxyLifecycle {
    Stopped,
    Starting,
    Running,
    Stopping,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WsConnectionState {
    Disconnected,
    Connecting,
    Connected,
    AuthFailed,
    Parked,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BootstrapState {
    pub version: String,
    pub platform: String,
    pub has_token: bool,
    pub proxy_lifecycle: ProxyLifecycle,
    pub ws_state: WsConnectionState,
    /// Detail message for the last WS auth failure (Python auth-failed detail).
    #[serde(default)]
    pub ws_error: Option<String>,
    pub listen_address: String,
    pub listen_port: u16,
}

impl Default for BootstrapState {
    fn default() -> Self {
        Self {
            version: crate::app_version::version_string().to_string(),
            platform: std::env::consts::OS.to_string(),
            has_token: false,
            proxy_lifecycle: ProxyLifecycle::Stopped,
            ws_state: WsConnectionState::Disconnected,
            ws_error: None,
            listen_address: "127.0.0.1".to_string(),
            listen_port: 6998,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalAccount {
    pub alias: String,
    pub username: String,
    pub password: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalCharacter {
    pub name: String,
    pub account_alias: String,
    #[serde(default)]
    pub server: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub class: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub level: Option<i32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub bind: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub park: Option<String>,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub items: HashMap<String, Value>,
}
