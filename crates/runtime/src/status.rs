use proxy_core::model::{BootstrapState, ProxyLifecycle, WsConnectionState};
use serde::{Deserialize, Serialize};
use tokio::sync::watch;

use crate::events::ProxyStatus;
use crate::proxy_stats::ProxyStatsView;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeStateView {
    pub bootstrap: BootstrapState,
    pub proxy: ProxyStatus,
    pub stats: ProxyStatsView,
}

#[derive(Debug, Clone, Default)]
pub struct RuntimeSnapshot {
    pub bootstrap: BootstrapState,
    pub proxy: ProxyStatus,
    pub stats: ProxyStatsView,
}
pub type SnapshotTx = watch::Sender<RuntimeSnapshot>;
pub type SnapshotRx = watch::Receiver<RuntimeSnapshot>;

pub fn snapshot_channel() -> (SnapshotTx, SnapshotRx) {
    watch::channel(RuntimeSnapshot::default())
}

pub fn set_lifecycle(snapshot: &mut RuntimeSnapshot, lifecycle: ProxyLifecycle) {
    snapshot.bootstrap.proxy_lifecycle = lifecycle;
    snapshot.proxy.lifecycle = lifecycle;
}

pub fn set_ws_state(snapshot: &mut RuntimeSnapshot, state: WsConnectionState) {
    snapshot.bootstrap.ws_state = state;
    if state != WsConnectionState::AuthFailed {
        snapshot.bootstrap.ws_error = None;
    }
}

pub fn set_ws_error(snapshot: &mut RuntimeSnapshot, detail: Option<String>) {
    snapshot.bootstrap.ws_error = detail;
}
