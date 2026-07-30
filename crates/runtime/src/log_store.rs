//! In-memory ring buffers of recent log lines for the UI (Python ``QtLogHandler`` parity).

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};

/// Lines retained per severity bucket (Python ``MAX_PER_LEVEL``).
pub const MAX_PER_LEVEL: usize = 5_000;

const LEVEL_COUNT: usize = 5;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogLine {
    pub timestamp: String,
    pub level: String,
    pub target: String,
    pub message: String,
}

#[derive(Clone)]
struct StoredLine {
    seq: u64,
    line: LogLine,
}

struct LogStoreInner {
    seq: u64,
    buffers: [VecDeque<StoredLine>; LEVEL_COUNT],
    capacity: usize,
}

#[derive(Clone)]
pub struct LogStore {
    inner: Arc<Mutex<LogStoreInner>>,
}

fn level_bucket(level: &str) -> usize {
    match level.to_ascii_uppercase().as_str() {
        "TRACE" | "DEBUG" => 0,
        "INFO" => 1,
        "WARN" | "WARNING" => 2,
        "ERROR" => 3,
        "CRITICAL" | "FATAL" => 4,
        _ => 1,
    }
}

impl LogStore {
    pub fn new() -> Self {
        Self::with_capacity(MAX_PER_LEVEL)
    }

    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            inner: Arc::new(Mutex::new(LogStoreInner {
                seq: 0,
                buffers: std::array::from_fn(|_| VecDeque::new()),
                capacity,
            })),
        }
    }

    pub fn push(&self, line: LogLine) {
        let bucket = level_bucket(&line.level);
        let mut guard = self.inner.lock().expect("log store lock");
        guard.seq += 1;
        let entry = StoredLine {
            seq: guard.seq,
            line,
        };
        let capacity = guard.capacity;
        let buffer = &mut guard.buffers[bucket];
        if buffer.len() >= capacity {
            buffer.pop_front();
        }
        buffer.push_back(entry);
    }

    /// Merge buckets at or above ``min_level``, ordered by arrival (Python ``refilter``).
    pub fn recent_at_level(&self, min_level: &str, limit: usize) -> Vec<LogLine> {
        let min_bucket = level_bucket(min_level);
        let guard = self.inner.lock().expect("log store lock");
        let mut merged: Vec<&StoredLine> = guard.buffers[min_bucket..]
            .iter()
            .flat_map(|buffer| buffer.iter())
            .collect();
        merged.sort_by_key(|entry| entry.seq);
        let start = merged.len().saturating_sub(limit);
        merged[start..]
            .iter()
            .map(|entry| entry.line.clone())
            .collect()
    }

    pub fn recent(&self, limit: usize) -> Vec<LogLine> {
        self.recent_at_level("DEBUG", limit)
    }

    pub fn clear(&self) {
        let mut guard = self.inner.lock().expect("log store lock");
        for buffer in &mut guard.buffers {
            buffer.clear();
        }
        guard.seq = 0;
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
        AppEvent::LocalCharacterUpdate { name, .. } => {
            (Level::DEBUG, format!("local character update for {name}"))
        }
        AppEvent::LogFileSwitched { character } => {
            (Level::INFO, format!("switched EQ log file for {character}"))
        }
        AppEvent::StatsDirty => (Level::DEBUG, "stats updated".into()),
        AppEvent::ConnectionStarted => (Level::INFO, "connection started".into()),
        AppEvent::ConnectionCompleted => (Level::INFO, "connection completed".into()),
        AppEvent::FatalError { message } => (Level::ERROR, format!("fatal: {message}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn line(level: &str, message: impl Into<String>) -> LogLine {
        LogLine {
            timestamp: "1".into(),
            level: level.into(),
            target: "test".into(),
            message: message.into(),
        }
    }

    #[test]
    fn debug_spam_does_not_evict_warn_bucket() {
        let store = LogStore::with_capacity(3);
        store.push(line("WARN", "keep-me"));
        for i in 0..5 {
            store.push(line("DEBUG", format!("debug-{i}")));
        }

        let warn_only = store.recent_at_level("WARN", 10);
        assert_eq!(warn_only.len(), 1);
        assert_eq!(warn_only[0].message, "keep-me");
    }

    #[test]
    fn recent_at_level_merges_chronologically() {
        let store = LogStore::new();
        store.push(line("INFO", "first"));
        store.push(line("DEBUG", "second"));
        store.push(line("WARN", "third"));

        let all = store.recent_at_level("DEBUG", 10);
        assert_eq!(
            all.iter().map(|l| l.message.as_str()).collect::<Vec<_>>(),
            vec!["first", "second", "third"]
        );

        let info_up = store.recent_at_level("INFO", 10);
        assert_eq!(
            info_up
                .iter()
                .map(|l| l.message.as_str())
                .collect::<Vec<_>>(),
            vec!["first", "third"]
        );
    }

    #[test]
    fn clear_resets_all_buckets() {
        let store = LogStore::new();
        store.push(line("ERROR", "boom"));
        store.push(line("DEBUG", "noise"));
        store.clear();
        assert!(store.recent_at_level("DEBUG", 10).is_empty());
    }
}
