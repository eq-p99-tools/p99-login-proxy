use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;

use crate::icons::update_tray_and_window_icons;
use crate::notifications::notify_login_proxied;
use crate::tray::{refresh_tray_tooltip, update_toggle_menu_label};
use proxy_core::model::ProxyLifecycle;
use runtime::events::AppEvent;
use runtime::{format_app_event, AppSupervisor, LogStore, RuntimeStateView};
use tauri::{AppHandle, Emitter};
use tokio::sync::{mpsc, watch, Mutex};
use tracing::Level;

pub struct AppState {
    pub supervisor: Arc<Mutex<AppSupervisor>>,
    pub snapshot_rx: watch::Receiver<runtime::RuntimeSnapshot>,
    pub log_store: LogStore,
    pub log_file: Option<PathBuf>,
    pub tray_available: Arc<AtomicBool>,
    event_rx: StdMutex<Option<mpsc::Receiver<AppEvent>>>,
}

impl AppState {
    pub fn new(log_store: LogStore, log_file: Option<PathBuf>) -> Self {
        let (supervisor, snapshot_rx, event_rx) = AppSupervisor::new();
        Self {
            supervisor: Arc::new(Mutex::new(supervisor)),
            snapshot_rx,
            log_store,
            log_file,
            tray_available: Arc::new(AtomicBool::new(false)),
            event_rx: StdMutex::new(Some(event_rx)),
        }
    }

    pub fn attach_emitter(&self, app: AppHandle) {
        let supervisor = self.supervisor.clone();
        spawn_snapshot_emitter(app.clone(), self.snapshot_rx.clone(), supervisor.clone());
        spawn_uptime_ticker(supervisor.clone());
        if let Some(event_rx) = self.event_rx.lock().expect("event_rx lock").take() {
            spawn_event_loop(app.clone(), event_rx, supervisor);
        }
        tauri::async_runtime::spawn({
            let app = app.clone();
            let supervisor = self.supervisor.clone();
            async move {
                let (mode, backend) = {
                    let sup = supervisor.lock().await;
                    (
                        sup.runtime_state().stats.proxy_mode,
                        sup.sso_backend().to_string(),
                    )
                };
                update_tray_and_window_icons(&app, mode, &backend);
                refresh_tray_tooltip(&app).await;
            }
        });
    }

    pub fn set_tray_available(&self, available: bool) {
        self.tray_available.store(available, Ordering::Relaxed);
    }

    pub fn is_tray_available(&self) -> bool {
        self.tray_available.load(Ordering::Relaxed)
    }

    pub fn runtime_state(&self) -> runtime::RuntimeSnapshot {
        self.snapshot_rx.borrow().clone()
    }
}

fn spawn_event_loop(
    app: AppHandle,
    mut event_rx: mpsc::Receiver<AppEvent>,
    supervisor: Arc<Mutex<AppSupervisor>>,
) {
    tauri::async_runtime::spawn(async move {
        while let Some(event) = event_rx.recv().await {
            match &event {
                AppEvent::LoginProxied {
                    alias,
                    account,
                    method,
                } => {
                    notify_login_proxied(&app, alias, account, method);
                    let mut sup = supervisor.lock().await;
                    sup.stats_tracker().user_login(alias, account, method);
                    sup.note_login_method(method, account);
                    sup.touch_snapshot();
                }
                AppEvent::LocalCharacterUpdate {
                    name,
                    park,
                    bind,
                    level,
                    class,
                    items,
                } => {
                    let mut sup = supervisor.lock().await;
                    if sup.apply_local_character_update(
                        name,
                        park.as_deref(),
                        bind.as_deref(),
                        *level,
                        class.as_deref(),
                        items.as_ref(),
                    ) {
                        sup.touch_snapshot();
                    }
                }
                AppEvent::LogFileSwitched { character } => {
                    let mut sup = supervisor.lock().await;
                    if sup.try_auto_create_local_character(character) {
                        sup.touch_snapshot();
                    }
                }
                AppEvent::StatsDirty => {
                    let sup = supervisor.lock().await;
                    sup.touch_snapshot();
                }
                AppEvent::ConnectionStarted => {
                    let sup = supervisor.lock().await;
                    sup.stats_tracker().connection_started();
                    sup.touch_snapshot();
                }
                AppEvent::ConnectionCompleted => {
                    let sup = supervisor.lock().await;
                    sup.stats_tracker().connection_completed();
                    sup.touch_snapshot();
                }
                AppEvent::AuthRejected { username, reason } => {
                    let _ = app.emit(
                        "login-rejected",
                        serde_json::json!({ "username": username, "reason": reason }),
                    );
                }
                AppEvent::RustleWarning { message } => {
                    let _ = app.emit("rustle-warning", serde_json::json!({ "message": message }));
                }
                _ => {}
            }

            let (level, message) = format_app_event(&event);
            match level {
                Level::ERROR => tracing::error!("{message}"),
                Level::WARN => tracing::warn!("{message}"),
                Level::DEBUG => tracing::debug!("{message}"),
                _ => tracing::info!("{message}"),
            }
        }
        tracing::warn!("runtime event channel closed");
    });
}

fn spawn_uptime_ticker(supervisor: Arc<Mutex<AppSupervisor>>) {
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(1)).await;
            let sup = supervisor.lock().await;
            if sup.snapshot().bootstrap.proxy_lifecycle == ProxyLifecycle::Running {
                sup.touch_snapshot();
            }
        }
    });
}

fn spawn_snapshot_emitter(
    app: AppHandle,
    mut rx: watch::Receiver<runtime::RuntimeSnapshot>,
    supervisor: Arc<Mutex<AppSupervisor>>,
) {
    tauri::async_runtime::spawn(async move {
        let mut last_icon_state = None;
        loop {
            if rx.changed().await.is_err() {
                break;
            }
            let snap = rx.borrow().clone();
            let proxy_mode = snap.stats.proxy_mode;
            let view = RuntimeStateView {
                bootstrap: snap.bootstrap,
                proxy: snap.proxy,
                stats: snap.stats,
            };
            let _ = app.emit("runtime-state", &view);

            let backend = {
                let sup = supervisor.lock().await;
                sup.sso_backend().to_string()
            };
            let icon_state = (proxy_mode, backend);
            if last_icon_state.as_ref() != Some(&icon_state) {
                update_tray_and_window_icons(&app, icon_state.0, &icon_state.1);
                update_toggle_menu_label(&app);
                last_icon_state = Some(icon_state);
            }
            refresh_tray_tooltip(&app).await;
        }
    });
}
