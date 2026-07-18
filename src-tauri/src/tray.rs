use std::sync::OnceLock;

use proxy_core::model::ProxyLifecycle;
use runtime::RuntimeSnapshot;
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager,
};

use crate::commands::{hide_window, launch_everquest_from_app, show_window};
use crate::icons::{disable_ui_updates, initial_tray_icon, ui_updates_enabled, TRAY_ID};
use crate::notifications::notify_minimized_to_tray;
use crate::state::AppState;
use crate::updater;

const APP_NAME: &str = "P99 Login Proxy";

static TOGGLE_MENU_ITEM: OnceLock<MenuItem<tauri::Wry>> = OnceLock::new();

pub fn format_tray_tooltip(
    snap: &RuntimeSnapshot,
    local_accounts: usize,
    sso_accounts: usize,
) -> String {
    let status = match snap.bootstrap.proxy_lifecycle {
        ProxyLifecycle::Running => "Listening",
        ProxyLifecycle::Starting => "Starting",
        ProxyLifecycle::Stopping => "Stopping",
        ProxyLifecycle::Stopped => "Stopped",
    };
    format!(
        "{APP_NAME}\n\
         Status: {status}\n\
         Connections: {} active, {} total\n\
         Local Accounts: {local_accounts}\n\
         SSO Accounts: {sso_accounts}",
        snap.stats.active_connections, snap.stats.total_connections
    )
}

pub fn update_tray_tooltip(app: &AppHandle, tooltip: &str) {
    if !ui_updates_enabled() {
        return;
    }
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let _ = tray.set_tooltip(Some(tooltip));
    }
}

pub async fn refresh_tray_tooltip(app: &AppHandle) {
    if !ui_updates_enabled() {
        return;
    }
    let Some(state) = app.try_state::<AppState>() else {
        return;
    };
    let snap = state.runtime_state();
    let (local_accounts, sso_accounts) = {
        let sup = state.supervisor.lock().await;
        let local_accounts = sup.local_data().accounts.rows_for_csv().len();
        let sso_accounts = sup
            .sso_client()
            .and_then(|c| c.cache().try_read().ok().map(|g| g.account_count))
            .unwrap_or(0);
        (local_accounts, sso_accounts)
    };
    let tooltip = format_tray_tooltip(&snap, local_accounts, sso_accounts);
    update_tray_tooltip(app, &tooltip);
}

pub fn is_main_window_visible(app: &AppHandle) -> bool {
    app.get_webview_window("main")
        .and_then(|w| w.is_visible().ok())
        .unwrap_or(false)
}

pub fn update_toggle_menu_label(app: &AppHandle) {
    if !ui_updates_enabled() {
        return;
    }
    let visible = is_main_window_visible(app);
    let label = if visible {
        "Hide Application"
    } else {
        "Show Application"
    };
    if let Some(item) = TOGGLE_MENU_ITEM.get() {
        let _ = item.set_text(label);
    }
}

pub fn setup_tray(app: &AppHandle) -> tauri::Result<bool> {
    let toggle = MenuItem::with_id(app, "toggle", "Show Application", true, None::<&str>)?;
    let _ = TOGGLE_MENU_ITEM.set(toggle.clone());
    let launch_eq = MenuItem::with_id(app, "launch_eq", "Launch EverQuest", true, None::<&str>)?;
    let check_updates = MenuItem::with_id(
        app,
        "check_updates",
        "Check for Updates",
        true,
        None::<&str>,
    )?;
    let separator = PredefinedMenuItem::separator(app)?;
    let exit = MenuItem::with_id(app, "exit", "Exit", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[&toggle, &launch_eq, &check_updates, &separator, &exit],
    )?;

    let _tray = TrayIconBuilder::with_id(TRAY_ID)
        .icon(initial_tray_icon())
        .menu(&menu)
        .show_menu_on_left_click(false)
        .tooltip(APP_NAME)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "toggle" => {
                if is_main_window_visible(&app) {
                    let _ = hide_window(app.clone());
                } else {
                    let _ = show_window(app.clone());
                }
                update_toggle_menu_label(&app);
            }
            "launch_eq" => {
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = launch_everquest_from_app(app).await {
                        tracing::warn!(error = %e, "Launch EverQuest from tray failed");
                    }
                });
            }
            "check_updates" => {
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    let result = updater::check_for_updates(true).await;
                    if result.available {
                        let _ = show_window(app.clone());
                        updater::emit_if_available(&app, &result);
                    } else {
                        let _ = show_window(app.clone());
                        updater::emit_update_check_info(&app, &result);
                    }
                });
            }
            "exit" => {
                request_app_exit(app.clone());
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            let app = tray.app_handle();
            match event {
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } => {
                    let _ = show_window(app.clone());
                    update_toggle_menu_label(&app);
                }
                TrayIconEvent::DoubleClick {
                    button: MouseButton::Left,
                    ..
                } => {
                    if is_main_window_visible(&app) {
                        let _ = hide_window(app.clone());
                    } else {
                        let _ = show_window(app.clone());
                    }
                    update_toggle_menu_label(&app);
                }
                TrayIconEvent::Enter { .. } | TrayIconEvent::Move { .. } => {
                    update_toggle_menu_label(&app);
                }
                _ => {}
            }
        })
        .build(app)?;

    update_toggle_menu_label(app);
    Ok(true)
}

pub fn on_window_close_requested(app: &AppHandle, tray_available: bool) -> bool {
    if tray_available {
        let _ = hide_window(app.clone());
        notify_minimized_to_tray(app);
        update_toggle_menu_label(app);
        true
    } else {
        request_app_exit(app.clone());
        true
    }
}

pub fn teardown_app_ui(app: &AppHandle) {
    disable_ui_updates();
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.destroy();
    }
}

async fn shutdown_supervisor(app: &AppHandle) {
    if let Some(state) = app.try_state::<AppState>() {
        let shutdown = async {
            let mut sup = state.supervisor.lock().await;
            sup.shutdown_in_place().await;
        };
        if tokio::time::timeout(std::time::Duration::from_secs(3), shutdown)
            .await
            .is_err()
        {
            tracing::warn!("supervisor shutdown timed out; exiting anyway");
        }
    }
}

pub async fn shutdown_and_exit(app: AppHandle) {
    teardown_app_ui(&app);
    shutdown_supervisor(&app).await;
    app.exit(0);
}

pub fn request_app_exit(app: AppHandle) {
    teardown_app_ui(&app);
    tauri::async_runtime::spawn(async move {
        shutdown_supervisor(&app).await;
        app.exit(0);
    });
}
