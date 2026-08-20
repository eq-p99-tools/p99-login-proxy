use std::sync::Mutex;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use proxy_core::ProxyMode;
use serde::{Deserialize, Serialize};

/// Connection/login statistics mirrored from Python ``ProxyStats``.
#[derive(Debug)]
pub struct ProxyStatsTracker {
    inner: Mutex<ProxyStatsInner>,
}

#[derive(Debug)]
struct ProxyStatsInner {
    total_connections: u64,
    active_connections: u64,
    completed_connections: u64,
    start_time: Option<Instant>,
    last_alias: Option<String>,
    last_account: Option<String>,
    last_method: Option<String>,
    last_heartbeat_at_ms: Option<u64>,
    heartbeat_character: Option<String>,
    mode: ProxyMode,
    eqhost_proxy_enabled: bool,
    eqclient_log_enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ProxyStatsView {
    pub total_connections: u64,
    pub active_connections: u64,
    pub completed_connections: u64,
    pub uptime_secs: u64,
    pub uptime_display: String,
    pub last_username: Option<String>,
    pub last_account: Option<String>,
    pub last_login_method: Option<String>,
    pub last_heartbeat_at_ms: Option<u64>,
    pub heartbeat_character: Option<String>,
    pub proxy_mode: ProxyMode,
    pub eq_config_enabled: bool,
    pub eqhost_proxy_enabled: bool,
    pub eqclient_log_enabled: bool,
    pub listen_address: String,
    pub listen_port: u16,
    pub client_connected: bool,
}

impl Default for ProxyStatsTracker {
    fn default() -> Self {
        Self {
            inner: Mutex::new(ProxyStatsInner {
                total_connections: 0,
                active_connections: 0,
                completed_connections: 0,
                start_time: None,
                last_alias: None,
                last_account: None,
                last_method: None,
                last_heartbeat_at_ms: None,
                heartbeat_character: None,
                mode: ProxyMode::Disabled,
                eqhost_proxy_enabled: false,
                eqclient_log_enabled: false,
            }),
        }
    }
}

impl ProxyStatsTracker {
    pub fn set_mode(&self, mode: ProxyMode) {
        self.inner.lock().unwrap().mode = mode;
    }

    pub fn reset_uptime(&self) {
        self.inner.lock().unwrap().start_time = Some(Instant::now());
    }

    pub fn clear_uptime(&self) {
        self.inner.lock().unwrap().start_time = None;
    }

    pub fn set_eq_config_status(&self, eqhost_proxy_enabled: bool, eqclient_log_enabled: bool) {
        let mut g = self.inner.lock().unwrap();
        g.eqhost_proxy_enabled = eqhost_proxy_enabled;
        g.eqclient_log_enabled = eqclient_log_enabled;
    }

    pub fn connection_started(&self) {
        let mut g = self.inner.lock().unwrap();
        g.total_connections += 1;
        g.active_connections += 1;
    }

    pub fn connection_completed(&self) {
        let mut g = self.inner.lock().unwrap();
        g.active_connections = g.active_connections.saturating_sub(1);
        g.completed_connections += 1;
    }

    pub fn user_login(&self, alias: &str, account: &str, method: &str) {
        let mut g = self.inner.lock().unwrap();
        g.last_alias = Some(alias.to_string());
        g.last_account = Some(account.to_string());
        g.last_method = Some(method.to_string());
    }

    pub fn record_heartbeat(&self, character: &str) {
        let mut g = self.inner.lock().unwrap();
        g.last_heartbeat_at_ms = Some(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
        );
        g.heartbeat_character = Some(character.to_string());
    }

    pub fn snapshot(
        &self,
        listen_address: &str,
        listen_port: u16,
        client_connected: bool,
    ) -> ProxyStatsView {
        let g = self.inner.lock().unwrap();
        let uptime_secs = g.start_time.map(|t| t.elapsed().as_secs()).unwrap_or(0);
        let last_username = match (&g.last_alias, &g.last_account) {
            (Some(a), Some(b)) if a != b => Some(format!("{a} → {b}")),
            (Some(a), _) => Some(a.clone()),
            _ => None,
        };
        ProxyStatsView {
            total_connections: g.total_connections,
            active_connections: g.active_connections,
            completed_connections: g.completed_connections,
            uptime_secs,
            uptime_display: format_uptime(uptime_secs),
            last_username,
            last_account: g.last_account.clone(),
            last_login_method: g.last_method.clone(),
            last_heartbeat_at_ms: g.last_heartbeat_at_ms,
            heartbeat_character: g.heartbeat_character.clone(),
            proxy_mode: g.mode,
            eq_config_enabled: g.eqhost_proxy_enabled && g.eqclient_log_enabled,
            eqhost_proxy_enabled: g.eqhost_proxy_enabled,
            eqclient_log_enabled: g.eqclient_log_enabled,
            listen_address: listen_address.to_string(),
            listen_port,
            client_connected,
        }
    }
}

fn format_uptime(secs: u64) -> String {
    let hours = secs / 3600;
    let minutes = (secs % 3600) / 60;
    let seconds = secs % 60;
    if hours > 0 {
        format!("{hours}h {minutes}m {seconds}s")
    } else if minutes > 0 {
        format!("{minutes}m {seconds}s")
    } else {
        format!("{seconds}s")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uptime_format() {
        assert_eq!(format_uptime(45), "45s");
        assert_eq!(format_uptime(125), "2m 5s");
    }

    #[test]
    fn connection_counters_increment() {
        let tracker = ProxyStatsTracker::default();
        tracker.connection_started();
        tracker.connection_started();
        let snap = tracker.snapshot("127.0.0.1", 5998, true);
        assert_eq!(snap.total_connections, 2);
        assert_eq!(snap.active_connections, 2);
        assert_eq!(snap.completed_connections, 0);

        tracker.connection_completed();
        let snap = tracker.snapshot("127.0.0.1", 5998, false);
        assert_eq!(snap.active_connections, 1);
        assert_eq!(snap.completed_connections, 1);
    }

    #[test]
    fn uptime_tracks_listener_lifecycle() {
        let tracker = ProxyStatsTracker::default();
        let snap = tracker.snapshot("127.0.0.1", 5998, false);
        assert_eq!(snap.uptime_secs, 0);

        tracker.reset_uptime();
        std::thread::sleep(std::time::Duration::from_millis(1100));
        let snap = tracker.snapshot("127.0.0.1", 5998, false);
        assert!(snap.uptime_secs >= 1);

        tracker.clear_uptime();
        let snap = tracker.snapshot("127.0.0.1", 5998, false);
        assert_eq!(snap.uptime_secs, 0);
    }

    #[test]
    fn eq_config_enabled_requires_both_checks() {
        let tracker = ProxyStatsTracker::default();
        tracker.set_eq_config_status(true, false);
        let snap = tracker.snapshot("127.0.0.1", 5998, false);
        assert!(snap.eqhost_proxy_enabled);
        assert!(!snap.eqclient_log_enabled);
        assert!(!snap.eq_config_enabled);

        tracker.set_eq_config_status(true, true);
        let snap = tracker.snapshot("127.0.0.1", 5998, false);
        assert!(snap.eq_config_enabled);
    }
}
