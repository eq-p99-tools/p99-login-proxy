mod commands;
mod icons;
mod logging;
mod notifications;
mod state;
mod tray;
mod updater;

use std::sync::Arc;
use std::time::{Duration, Instant};

use proxy_core::window_title;
use runtime::{AppSupervisor, LogStore};
use tauri::Manager;
use tokio::sync::Mutex;

use crate::logging::init as init_logging;
use crate::state::AppState;
use crate::tray::{on_window_close_requested, setup_tray};

fn apply_main_window_title(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.set_title(&window_title());
    }
}

/// Detect a system suspend/resume by watching for wall-clock jumps and bounce
/// the UDP transport so the proxy keeps working after the machine wakes.
fn spawn_resume_monitor(supervisor: Arc<Mutex<AppSupervisor>>) {
    const TICK: Duration = Duration::from_secs(10);
    const RESUME_GAP: Duration = Duration::from_secs(30);
    tauri::async_runtime::spawn(async move {
        loop {
            let before = Instant::now();
            tokio::time::sleep(TICK).await;
            if before.elapsed() > TICK + RESUME_GAP {
                let mut sup = supervisor.lock().await;
                if let Err(e) = sup.bounce_proxy_transport().await {
                    tracing::warn!(error = %e, "resume proxy restart failed");
                }
            }
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let log_store = LogStore::new();
    let log_paths = init_logging(log_store.clone());
    let app_state = AppState::new(log_store, log_paths.file);

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            let _ = commands::show_window(app.clone());
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .manage(app_state)
        .setup(|app| {
            apply_main_window_title(&app.handle());
            let tray_ok = setup_tray(app.handle()).unwrap_or(false);
            if let Some(state) = app.try_state::<AppState>() {
                state.set_tray_available(tray_ok);
                state.attach_emitter(app.handle().clone());

                let app_handle = app.handle().clone();
                let supervisor = state.supervisor.clone();
                tauri::async_runtime::spawn(async move {
                    {
                        let mut sup = supervisor.lock().await;
                        sup.bootstrap_startup().await;
                    }

                    let config = proxy_core::load_config().ok();
                    if let Some(file) = config {
                        commands::apply_always_on_top(&app_handle, file.always_on_top);
                        if file.launch_startup {
                            if let Some(ref eq_dir) = file.eq_directory {
                                let path = std::path::PathBuf::from(eq_dir);
                                if let Err(e) =
                                    commands::launch_everquest_at(&path, file.launch_admin)
                                {
                                    tracing::warn!("launch_startup failed: {e}");
                                }
                            }
                        }
                    }
                });
            }
            if !tray_ok {
                tracing::warn!("system tray unavailable; window close will exit the app");
            }
            let update_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                updater::run_startup_and_scheduled_checks(update_handle).await;
            });

            if let Some(state) = app.try_state::<AppState>() {
                spawn_resume_monitor(state.supervisor.clone());
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                let tray_available = app
                    .try_state::<AppState>()
                    .map(|s| s.is_tray_available())
                    .unwrap_or(false);
                if on_window_close_requested(app, tray_available) {
                    api.prevent_close();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_bootstrap_state,
            commands::get_runtime_state,
            commands::get_sso_status,
            commands::get_sso_accounts,
            commands::get_sso_backends,
            commands::set_sso_token,
            commands::clear_sso_token,
            commands::set_sso_backend,
            commands::reconnect_sso,
            commands::get_app_config,
            commands::save_app_config,
            commands::get_local_data,
            commands::save_local_data,
            commands::reload_local_data,
            commands::get_eq_settings,
            commands::set_eq_directory,
            commands::get_changelog,
            commands::fetch_github_changelog,
            commands::check_for_updates,
            commands::install_update,
            commands::clear_logs,
            commands::get_proxy_settings,
            commands::update_proxy_settings,
            commands::set_proxy_mode_selection,
            commands::update_listen_port,
            commands::get_recent_logs,
            commands::launch_everquest,
            commands::reset_eqhost_backup,
            commands::restore_eqhost_backup,
            commands::save_eqhost_contents,
            commands::open_eq_folder,
            commands::browse_eq_executable,
            commands::show_window,
            commands::hide_window,
            commands::request_shutdown,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
