//! In-memory ring buffer of recent log lines for the UI.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};

const DEFAULT_CAPACITY: usize = 500;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogLine {
    pub timestamp: String,
    pub level: String,
    pub target: String,
    pub message: String,
}

#[derive(Clone)]
pub struct LogStore {
    inner: Arc<Mutex<VecDeque<LogLine>>>,
    capacity: usize,
}

impl LogStore {
    pub fn new() -> Self {
        Self::with_capacity(DEFAULT_CAPACITY)
    }

    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            inner: Arc::new(Mutex::new(VecDeque::with_capacity(capacity.min(64)))),
            capacity,
        }
    }

    pub fn push(&self, line: LogLine) {
        let mut guard = self.inner.lock().expect("log store lock");
        if guard.len() >= self.capacity {
            guard.pop_front();
        }
        guard.push_back(line);
    }

    pub fn recent(&self, limit: usize) -> Vec<LogLine> {
        let guard = self.inner.lock().expect("log store lock");
        let start = guard.len().saturating_sub(limit);
        guard.iter().skip(start).cloned().collect()
    }

    pub fn clear(&self) {
        let mut guard = self.inner.lock().expect("log store lock");
        guard.clear();
    }
}

impl Default for LogStore {
    fn default() -> Self {
        Self::new()
    }
}

/// Format runtime events for tracing and the activity log.
pub fn format_app_event(event: &crate::events::AppEvent) -> (tracing::Level, String) {
    use crate::events::AppEvent;
    use tracing::Level;

    match event {
        AppEvent::StateSnapshot { .. } => (Level::DEBUG, "state snapshot updated".into()),
        AppEvent::ProxyStatus { status } => (
            Level::INFO,
            format!(
                "proxy status lifecycle={:?} client_connected={} packets={}",
                status.lifecycle, status.client_connected, status.packets_forwarded
            ),
        ),
        AppEvent::UserConnected { endpoint } => {
            (Level::INFO, format!("EQ client connected: {endpoint}"))
        }
        AppEvent::AuthRejected { username, reason } => (
            Level::WARN,
            format!("auth rejected for {username}: {reason}"),
        ),
        AppEvent::RustleWarning { message } => (Level::WARN, message.clone()),
        AppEvent::Activity { message } => (Level::INFO, message.clone()),
        AppEvent::LoginProxied {
            alias,
            account,
            method,
        } => (
            Level::INFO,
            format!("login proxied alias={alias} account={account} method={method}"),
        ),
        AppEvent::StatsDirty => (Level::DEBUG, "stats updated".into()),
        AppEvent::ConnectionStarted => (Level::INFO, "connection started".into()),
        AppEvent::ConnectionCompleted => (Level::INFO, "connection completed".into()),
        AppEvent::FatalError { message } => (Level::ERROR, format!("fatal: {message}")),
    }
}
