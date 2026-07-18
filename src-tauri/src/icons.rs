use proxy_core::ProxyMode;
use tauri::image::Image;
use tauri::{include_image, AppHandle, Manager};
use tracing::warn;

use std::sync::atomic::{AtomicBool, Ordering};

static UI_UPDATES_ENABLED: AtomicBool = AtomicBool::new(true);

/// Stop tray/window icon updates during app teardown (snapshot emitters may still fire).
pub fn disable_ui_updates() {
    UI_UPDATES_ENABLED.store(false, Ordering::Relaxed);
}

pub fn ui_updates_enabled() -> bool {
    UI_UPDATES_ENABLED.load(Ordering::Relaxed)
}

pub const TRAY_ID: &str = "main-tray";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TrayIconState {
    Default,
    ProxyOnly,
    Disabled,
}

fn icon_set_for_backend(backend: &str) -> &'static str {
    match backend {
        "Kingdom" => "kingdom",
        _ => "p99",
    }
}

fn state_for_mode(mode: ProxyMode) -> TrayIconState {
    match mode {
        ProxyMode::EnabledSso => TrayIconState::Default,
        ProxyMode::EnabledProxyOnly => TrayIconState::ProxyOnly,
        ProxyMode::Disabled => TrayIconState::Disabled,
    }
}

fn load_tray_icon(icon_set: &str, state: TrayIconState) -> Image<'static> {
    match (icon_set, state) {
        ("kingdom", TrayIconState::Default) => {
            include_image!("icons/tray/kingdom/default.png").to_owned()
        }
        ("kingdom", TrayIconState::ProxyOnly) => {
            include_image!("icons/tray/kingdom/proxy_only.png").to_owned()
        }
        ("kingdom", TrayIconState::Disabled) => {
            include_image!("icons/tray/kingdom/disabled.png").to_owned()
        }
        (_, TrayIconState::Default) => include_image!("icons/tray/p99/default.png").to_owned(),
        (_, TrayIconState::ProxyOnly) => include_image!("icons/tray/p99/proxy_only.png").to_owned(),
        (_, TrayIconState::Disabled) => include_image!("icons/tray/p99/disabled.png").to_owned(),
    }
}

pub fn initial_tray_icon() -> Image<'static> {
    load_tray_icon("p99", TrayIconState::Disabled)
}

pub fn update_tray_and_window_icons(app: &AppHandle, mode: ProxyMode, backend: &str) {
    if !ui_updates_enabled() {
        return;
    }
    let icon_set = icon_set_for_backend(backend);
    let state = state_for_mode(mode);
    let icon = load_tray_icon(icon_set, state);

    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        if let Err(e) = tray.set_icon(Some(icon.clone())) {
            warn!(error = %e, "failed to set tray icon");
        }
    }

    if let Some(window) = app.get_webview_window("main") {
        if let Err(e) = window.set_icon(icon) {
            warn!(error = %e, "failed to set window icon");
        }
    }
}
