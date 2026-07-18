use proxy_core::model::BootstrapState;
use proxy_core::{
    config_file_path, list_sso_backend_options, load_config_file, load_local_data,
    save_config_file, save_local_accounts, save_local_characters, ConfigFileV1, EqHostWriter,
    ProxyMode,
};
use runtime::{LogLine, RuntimeStateView};
use secrecy::ExposeSecret;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Manager, State};

use crate::icons::update_tray_and_window_icons;
use crate::state::AppState;

pub(crate) fn apply_always_on_top(app: &AppHandle, enabled: bool) {
    if let Some(window) = app.get_webview_window("main") {
        if let Err(e) = window.set_always_on_top(enabled) {
            tracing::warn!(enabled, error = %e, "failed to set always_on_top");
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProxySettingsView {
    pub listen_host: String,
    pub listen_port: u16,
    pub upstream_host: String,
    pub upstream_port: u16,
    pub proxy_only: bool,
    pub skip_sso_accounts: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfigView {
    pub listen_host: String,
    pub listen_port: u16,
    pub upstream_host: String,
    pub upstream_port: u16,
    pub proxy_enabled: bool,
    pub proxy_only: bool,
    pub always_on_top: bool,
    pub launch_startup: bool,
    pub launch_admin: bool,
    pub warn_rustle: bool,
    pub auto_add_local_characters: bool,
    pub skip_sso_accounts: String,
    pub sso_backend: String,
    pub dark_mode: bool,
    pub theme_mode: String,
    pub prerelease_updates: bool,
    pub eq_directory: Option<String>,
    pub eq_directory_secondary: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SsoBackendOption {
    pub name: String,
    pub api_url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SsoAccountsView {
    pub account_tree: Value,
    pub account_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalAccountInput {
    pub name: String,
    #[serde(default)]
    pub password: String,
    pub aliases: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalCharacterInput {
    pub name: String,
    pub account_alias: String,
    #[serde(default)]
    pub server: String,
    #[serde(default)]
    pub class: Option<String>,
    #[serde(default)]
    pub level: Option<i32>,
    #[serde(default)]
    pub bind: Option<String>,
    #[serde(default)]
    pub park: Option<String>,
    #[serde(default)]
    pub items: std::collections::HashMap<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogSnapshot {
    pub lines: Vec<LogLine>,
    pub file_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SsoStatusView {
    pub backend: String,
    pub api_url: String,
    pub has_token: bool,
    /// Stored access key for the active backend (matches Python ``USER_API_TOKEN`` display).
    pub api_token: String,
    pub ws_state: proxy_core::model::WsConnectionState,
    /// Detail for the last WS auth failure (shown in the "SSO Service:" row).
    pub ws_error: Option<String>,
    pub account_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalDataView {
    pub accounts: Vec<proxy_core::model::LocalAccount>,
    pub characters: Vec<proxy_core::model::LocalCharacter>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EqSettingsView {
    pub eq_directory: Option<String>,
    pub eq_directory_secondary: Option<String>,
    pub eqhost_path: Option<String>,
    pub eqhost_contents: Option<String>,
    pub eqhost_backup_contents: Option<String>,
    pub eqhost_backup_exists: bool,
    pub proxy_enabled_in_eqhost: bool,
    pub eq_directory_valid: bool,
}

#[tauri::command]
pub fn get_sso_backends() -> Result<Vec<SsoBackendOption>, String> {
    let file = proxy_core::load_config().map_err(|e| e.to_string())?;
    Ok(list_sso_backend_options(&file)
        .into_iter()
        .map(|(name, api_url)| SsoBackendOption { name, api_url })
        .collect())
}

#[tauri::command]
pub async fn get_sso_accounts(state: State<'_, AppState>) -> Result<SsoAccountsView, String> {
    let sup = state.supervisor.lock().await;
    let cache = sup
        .sso_client()
        .and_then(|c| c.cache().try_read().ok().map(|g| g.clone()))
        .unwrap_or_default();
    Ok(SsoAccountsView {
        account_tree: cache.account_tree,
        account_count: cache.account_count,
    })
}

#[tauri::command]
pub async fn reconnect_sso(state: State<'_, AppState>) -> Result<SsoStatusView, String> {
    let mut sup = state.supervisor.lock().await;
    sup.reconnect_sso().await;
    drop(sup);
    get_sso_status(state).await
}

#[tauri::command]
pub async fn set_sso_backend(
    backend: String,
    api_url: Option<String>,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<SsoStatusView, String> {
    let mut sup = state.supervisor.lock().await;
    sup.set_sso_backend(backend.clone(), api_url).await?;
    let mode = sup.runtime_state().stats.proxy_mode;
    drop(sup);
    update_tray_and_window_icons(&app, mode, &backend);
    get_sso_status(state).await
}

#[tauri::command]
pub async fn get_app_config() -> Result<AppConfigView, String> {
    let file = proxy_core::load_config().map_err(|e| e.to_string())?;
    Ok(AppConfigView {
        listen_host: file.listen_host,
        listen_port: file.listen_port,
        upstream_host: file.upstream_host,
        upstream_port: file.upstream_port,
        proxy_enabled: file.proxy_enabled,
        proxy_only: file.proxy_only,
        always_on_top: file.always_on_top,
        launch_startup: file.launch_startup,
        launch_admin: file.launch_admin,
        warn_rustle: file.warn_rustle,
        auto_add_local_characters: file.auto_add_local_characters,
        skip_sso_accounts: file.skip_sso_accounts,
        sso_backend: file.sso_backend,
        dark_mode: file.dark_mode,
        theme_mode: file.theme_mode,
        prerelease_updates: file.prerelease_updates,
        eq_directory: file.eq_directory,
        eq_directory_secondary: file.eq_directory_secondary,
    })
}

#[tauri::command]
pub async fn save_app_config(
    config: AppConfigView,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<AppConfigView, String> {
    let path = config_file_path().ok_or("config path unavailable")?;
    let mut file = if path.exists() {
        load_config_file(&path).map_err(|e| e.to_string())?
    } else {
        ConfigFileV1::default()
    };
    file.listen_host = config.listen_host;
    file.listen_port = config.listen_port;
    file.upstream_host = config.upstream_host;
    file.upstream_port = config.upstream_port;
    file.proxy_enabled = config.proxy_enabled;
    file.proxy_only = config.proxy_only;
    file.always_on_top = config.always_on_top;
    file.launch_startup = config.launch_startup;
    file.launch_admin = config.launch_admin;
    file.warn_rustle = config.warn_rustle;
    file.auto_add_local_characters = config.auto_add_local_characters;
    file.skip_sso_accounts = config.skip_sso_accounts;
    file.sso_backend = config.sso_backend.clone();
    file.dark_mode = config.dark_mode;
    file.theme_mode = config.theme_mode;
    file.prerelease_updates = config.prerelease_updates;
    file.eq_directory = config.eq_directory.clone().filter(|s| !s.trim().is_empty());
    file.eq_directory_secondary = config
        .eq_directory_secondary
        .clone()
        .filter(|s| !s.trim().is_empty());
    save_config_file(&path, &file).map_err(|e| e.to_string())?;
    {
        let mut sup = state.supervisor.lock().await;
        sup.apply_runtime_config(&file)?;
        sup.set_eq_directory(file.eq_directory.as_ref().map(std::path::PathBuf::from));
    }
    apply_always_on_top(&app, file.always_on_top);
    get_app_config().await
}

#[tauri::command]
pub async fn save_local_data(
    accounts: Vec<LocalAccountInput>,
    characters: Vec<LocalCharacterInput>,
    state: State<'_, AppState>,
) -> Result<LocalDataView, String> {
    use proxy_core::characters::LocalCharacterStore;
    use proxy_core::model::LocalCharacter;
    use secrecy::SecretString;

    let existing = load_local_data();
    let mut account_store = existing.accounts;
    for row in accounts {
        let name = row.name.trim();
        if name.is_empty() {
            continue;
        }
        let password = if row.password.is_empty() {
            account_store
                .resolve(name)
                .map(|(_, p)| p.expose_secret().to_string())
                .unwrap_or_default()
        } else {
            row.password.clone()
        };
        if password.is_empty() {
            return Err(format!("password required for new account '{name}'"));
        }
        account_store.insert(
            name.to_string(),
            name.to_string(),
            SecretString::from(password.clone()),
        );
        for alias in row.aliases {
            let a = alias.trim();
            if !a.is_empty() {
                account_store.insert(
                    a.to_string(),
                    name.to_string(),
                    SecretString::from(password.clone()),
                );
            }
        }
    }

    let mut char_store = LocalCharacterStore::default();
    for row in characters {
        let name = row.name.trim();
        if name.is_empty() {
            continue;
        }
        let _ = char_store.upsert(LocalCharacter {
            name: name.to_string(),
            account_alias: row.account_alias.trim().to_lowercase(),
            server: row.server.trim().to_string(),
            class: row.class.filter(|s| !s.trim().is_empty()),
            level: row.level,
            bind: row.bind.filter(|s| !s.trim().is_empty()),
            park: row.park.filter(|s| !s.trim().is_empty()),
            items: row.items,
        });
    }

    save_local_accounts(&account_store).map_err(|e| e.to_string())?;
    save_local_characters(&char_store).map_err(|e| e.to_string())?;

    {
        let mut sup = state.supervisor.lock().await;
        sup.set_local_data(runtime::ProxyLocalData {
            accounts: account_store,
            characters: char_store,
        });
    }
    get_local_data(state).await
}

#[tauri::command]
pub async fn reload_local_data(state: State<'_, AppState>) -> Result<LocalDataView, String> {
    let mut sup = state.supervisor.lock().await;
    sup.reload_local_data();
    drop(sup);
    get_local_data(state).await
}

#[tauri::command]
pub async fn get_local_data(state: State<'_, AppState>) -> Result<LocalDataView, String> {
    let sup = state.supervisor.lock().await;
    let data = sup.local_data();
    Ok(LocalDataView {
        accounts: data.accounts.list(),
        characters: data.characters.list(),
    })
}

#[tauri::command]
pub async fn get_eq_settings(state: State<'_, AppState>) -> Result<EqSettingsView, String> {
    let sup = state.supervisor.lock().await;
    let eq_dir = sup.eq_directory().cloned();
    let config_path = config_file_path().ok_or("config path unavailable")?;
    let file = if config_path.exists() {
        load_config_file(&config_path).map_err(|e| e.to_string())?
    } else {
        ConfigFileV1::default()
    };
    let mut view = EqSettingsView {
        eq_directory: eq_dir.as_ref().map(|p| p.display().to_string()),
        eq_directory_secondary: file.eq_directory_secondary.clone(),
        eqhost_path: None,
        eqhost_contents: None,
        eqhost_backup_contents: None,
        eqhost_backup_exists: false,
        proxy_enabled_in_eqhost: false,
        eq_directory_valid: false,
    };
    if let Some(ref dir) = eq_dir {
        view.eq_directory_valid = EqHostWriter::validate_eq_directory(dir).is_ok();
        let eqhost_path = dir.join("eqhost.txt");
        let backup_path = eqhost_path.with_extension("txt.bak");
        view.eqhost_path = Some(eqhost_path.display().to_string());
        view.eqhost_backup_exists = backup_path.is_file();
        let cfg = sup.proxy_config();
        view.proxy_enabled_in_eqhost =
            EqHostWriter::is_proxy_enabled_in_directory(dir, &cfg.listen_host, cfg.listen_port);
        if let Ok(text) = EqHostWriter::read_eqhost(dir) {
            view.eqhost_contents = Some(text);
        }
        if backup_path.is_file() {
            if let Ok(bytes) = std::fs::read(&backup_path) {
                view.eqhost_backup_contents = Some(
                    String::from_utf8_lossy(&bytes)
                        .trim_start_matches('\u{feff}')
                        .to_string(),
                );
            }
        }
    }
    Ok(view)
}

#[tauri::command]
pub async fn set_eq_directory(
    path: String,
    state: State<'_, AppState>,
) -> Result<EqSettingsView, String> {
    let config_path = config_file_path().ok_or("config path unavailable")?;
    let mut file = if config_path.exists() {
        load_config_file(&config_path).map_err(|e| e.to_string())?
    } else {
        ConfigFileV1::default()
    };
    file.eq_directory = if path.trim().is_empty() {
        None
    } else {
        Some(path.trim().to_string())
    };
    save_config_file(&config_path, &file).map_err(|e| e.to_string())?;
    {
        let mut sup = state.supervisor.lock().await;
        let eq_directory = file.eq_directory.as_ref().map(std::path::PathBuf::from);
        if let Some(ref dir) = eq_directory {
            if !proxy_core::ensure_eqclient_log_enabled(dir) {
                return Err(format!(
                    "Could not enable Log=TRUE in {}. Check file permissions.",
                    dir.join("eqclient.ini").display()
                ));
            }
        }
        sup.set_eq_directory(eq_directory);
        sup.reconnect_sso().await;
        sup.touch_snapshot();
    }
    get_eq_settings(state).await
}

#[tauri::command]
pub async fn browse_eq_executable(app: AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    let window = app
        .get_webview_window("main")
        .ok_or("main window not found")?;
    let picked = window
        .dialog()
        .file()
        .set_title("Select eqgame.exe")
        .set_parent(&window)
        .add_filter("EverQuest", &["exe"])
        .blocking_pick_file();
    Ok(picked.map(|p| {
        let s = p.to_string();
        if s.to_ascii_lowercase().ends_with("eqgame.exe") {
            std::path::Path::new(&s)
                .parent()
                .map(|d| d.display().to_string())
                .unwrap_or(s)
        } else {
            s
        }
    }))
}

#[tauri::command]
pub async fn reset_eqhost_backup(state: State<'_, AppState>) -> Result<EqSettingsView, String> {
    let (eq_dir, upstream_host, upstream_port) = {
        let sup = state.supervisor.lock().await;
        let eq_dir = sup
            .eq_directory()
            .cloned()
            .ok_or("EverQuest directory not configured")?;
        let cfg = sup.proxy_config();
        (eq_dir, cfg.upstream_host.clone(), cfg.upstream_port)
    };
    EqHostWriter::reset_eqhost_backup(&eq_dir, &upstream_host, upstream_port)
        .map_err(|e| e.to_string())?;
    {
        let sup = state.supervisor.lock().await;
        sup.touch_snapshot();
    }
    get_eq_settings(state).await
}

#[tauri::command]
pub async fn restore_eqhost_backup(state: State<'_, AppState>) -> Result<EqSettingsView, String> {
    use proxy_core::model::ProxyLifecycle;

    let mut sup = state.supervisor.lock().await;
    let eq_dir = sup
        .eq_directory()
        .cloned()
        .ok_or("EverQuest directory not configured")?;
    let listen_port = sup.proxy_config().listen_port;
    let lifecycle = sup.snapshot().bootstrap.proxy_lifecycle;

    if lifecycle == ProxyLifecycle::Running || lifecycle == ProxyLifecycle::Starting {
        // stop_proxy (via Disabled) restores eqhost.txt from the backup file.
        sup.set_proxy_mode_selection(ProxyMode::Disabled).await?;
    } else {
        EqHostWriter::disable_proxy(&eq_dir, "127.0.0.1", listen_port)
            .map_err(|e| e.to_string())?;
        sup.set_proxy_mode_selection(ProxyMode::Disabled).await?;
    }
    sup.touch_snapshot();
    drop(sup);
    get_eq_settings(state).await
}

#[tauri::command]
pub async fn save_eqhost_contents(
    contents: String,
    state: State<'_, AppState>,
) -> Result<EqSettingsView, String> {
    let sup = state.supervisor.lock().await;
    let eq_dir = sup
        .eq_directory()
        .cloned()
        .ok_or("EverQuest directory not configured")?;
    EqHostWriter::write_eqhost(&eq_dir, &contents).map_err(|e| e.to_string())?;
    sup.touch_snapshot();
    drop(sup);
    get_eq_settings(state).await
}

#[tauri::command]
pub async fn open_eq_folder(app: AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    let sup = state.supervisor.lock().await;
    let dir = sup
        .eq_directory()
        .cloned()
        .ok_or("EverQuest directory not configured")?;
    drop(sup);
    tauri_plugin_opener::OpenerExt::opener(&app)
        .open_path(dir.display().to_string(), None::<&str>)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn launch_everquest(state: State<'_, AppState>) -> Result<(), String> {
    launch_everquest_from_state(state).await
}

pub async fn launch_everquest_from_state(state: State<'_, AppState>) -> Result<(), String> {
    let (dir, launch_admin) = {
        let sup = state.supervisor.lock().await;
        let dir = sup
            .eq_directory()
            .cloned()
            .ok_or("EverQuest directory not configured")?;
        let launch_admin = proxy_core::load_config()
            .map(|f| f.launch_admin)
            .unwrap_or(true);
        (dir, launch_admin)
    };
    launch_everquest_at(&dir, launch_admin)
}

pub async fn launch_everquest_from_app(app: AppHandle) -> Result<(), String> {
    let (dir, launch_admin) = {
        let state = app.state::<AppState>();
        let sup = state.supervisor.lock().await;
        let dir = sup
            .eq_directory()
            .cloned()
            .ok_or("EverQuest directory not configured")?;
        let launch_admin = proxy_core::load_config()
            .map(|f| f.launch_admin)
            .unwrap_or(true);
        (dir, launch_admin)
    };
    launch_everquest_at(&dir, launch_admin)
}

pub fn launch_everquest_at(dir: &std::path::Path, launch_admin: bool) -> Result<(), String> {
    EqHostWriter::validate_eq_directory(dir).map_err(|e| e.to_string())?;
    let exe = dir.join("eqgame.exe");
    #[cfg(windows)]
    {
        if launch_admin {
            match shell_execute_eq(&exe, dir, true) {
                Ok(()) => return Ok(()),
                Err(e) => {
                    tracing::warn!(
                        "elevated launch failed; retrying detached without elevation: {e}"
                    );
                }
            }
        }
        spawn_eqgame_detached(&exe, dir)
    }
    #[cfg(not(windows))]
    {
        // Parity with the Python client: EverQuest is a Windows binary, so on
        // Linux/macOS launch it through Wine (`wine eqgame.exe patchme`).
        use std::os::unix::process::CommandExt;

        std::process::Command::new("wine")
            .current_dir(dir)
            .arg(&exe)
            .arg("patchme")
            .process_group(0)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .map_err(|e| {
                format!(
                    "failed to launch EverQuest via wine: {e}. Ensure Wine is installed and on PATH."
                )
            })?;
        Ok(())
    }
}

#[cfg(windows)]
fn spawn_eqgame_detached(exe: &std::path::Path, dir: &std::path::Path) -> Result<(), String> {
    use std::os::windows::process::CommandExt;

    // Tauri/WebView2 runs inside a Windows job object. ShellExecute("open") and
    // Command::spawn without breakaway inherit that job, so EQ exits when we do.
    const DETACHED_PROCESS: u32 = 0x0000_0008;
    const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
    const CREATE_BREAKAWAY_FROM_JOB: u32 = 0x0100_0000;

    std::process::Command::new(exe)
        .current_dir(dir)
        .arg("patchme")
        .creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|e| format!("failed to launch EverQuest: {e}"))?;
    Ok(())
}

// The single FFI call in the app: elevate/launch the EQ client via ShellExecuteW.
#[cfg(windows)]
#[allow(unsafe_code)]
fn shell_execute_eq(
    exe: &std::path::Path,
    dir: &std::path::Path,
    elevated: bool,
) -> Result<(), String> {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWDEFAULT;

    fn to_wide(value: &OsStr) -> Vec<u16> {
        value.encode_wide().chain(std::iter::once(0)).collect()
    }

    let verb = to_wide(if elevated {
        OsStr::new("runas")
    } else {
        OsStr::new("open")
    });
    let file = to_wide(exe.as_os_str());
    let params = to_wide(OsStr::new("patchme"));
    let cwd = to_wide(dir.as_os_str());

    let result = unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            verb.as_ptr(),
            file.as_ptr(),
            params.as_ptr(),
            cwd.as_ptr(),
            SW_SHOWDEFAULT,
        )
    };
    if result as isize <= 32 {
        return Err(format!("ShellExecute failed with code {}", result as isize));
    }
    Ok(())
}

#[tauri::command]
pub fn get_changelog() -> String {
    crate::updater::cached_changelog_html()
}

#[tauri::command]
pub async fn fetch_github_changelog() -> Result<String, String> {
    crate::updater::fetch_github_changelog().await
}

#[tauri::command]
pub async fn check_for_updates(
    notify_no_update: Option<bool>,
) -> crate::updater::UpdateCheckResult {
    crate::updater::check_for_updates(notify_no_update.unwrap_or(true)).await
}

#[tauri::command]
pub async fn install_update(
    app: AppHandle,
    state: State<'_, AppState>,
    version: String,
) -> Result<(), String> {
    let executable = crate::updater::install_update(&app, &version).await?;
    crate::tray::teardown_app_ui(&app);
    {
        let mut supervisor = state.supervisor.lock().await;
        supervisor.shutdown_in_place().await;
    }
    std::process::Command::new(&executable)
        .spawn()
        .map_err(|error| format!("Update installed, but relaunch failed: {error}"))?;
    app.exit(0);
    Ok(())
}

#[tauri::command]
pub fn clear_logs(state: State<'_, AppState>) {
    state.log_store.clear();
}

#[tauri::command]
pub async fn get_sso_status(state: State<'_, AppState>) -> Result<SsoStatusView, String> {
    let sup = state.supervisor.lock().await;
    sup.sync_bootstrap_token_flag();
    let snap = sup.snapshot();
    let backend = sup.sso_backend().to_string();
    let has_token = sup.secrets().has_token(&backend);
    let api_token = sup
        .secrets()
        .load_token(&backend)
        .ok()
        .flatten()
        .map(|t| t.expose_secret().to_string())
        .unwrap_or_default();
    let account_count = sup
        .sso_client()
        .and_then(|c| c.cache().try_read().ok().map(|g| g.account_count))
        .unwrap_or(0);
    Ok(SsoStatusView {
        backend,
        api_url: sup.proxy_config().sso_api_url.clone(),
        has_token,
        api_token,
        ws_state: snap.bootstrap.ws_state,
        ws_error: snap.bootstrap.ws_error.clone(),
        account_count,
    })
}

#[tauri::command]
pub async fn set_sso_token(
    token: String,
    state: State<'_, AppState>,
) -> Result<SsoStatusView, String> {
    let mut sup = state.supervisor.lock().await;
    sup.set_sso_token(&token).await?;
    drop(sup);
    get_sso_status(state).await
}

#[tauri::command]
pub async fn clear_sso_token(state: State<'_, AppState>) -> Result<SsoStatusView, String> {
    let mut sup = state.supervisor.lock().await;
    sup.clear_sso_token().await?;
    drop(sup);
    get_sso_status(state).await
}

#[tauri::command]
pub fn get_runtime_state(state: State<'_, AppState>) -> RuntimeStateView {
    let snap = state.runtime_state();
    RuntimeStateView {
        bootstrap: snap.bootstrap,
        proxy: snap.proxy,
        stats: snap.stats,
    }
}

#[tauri::command]
pub async fn set_proxy_mode_selection(
    mode: String,
    state: State<'_, AppState>,
) -> Result<RuntimeStateView, String> {
    let parsed = match mode.as_str() {
        "enabled_sso" => ProxyMode::EnabledSso,
        "enabled_proxy_only" => ProxyMode::EnabledProxyOnly,
        "disabled" => ProxyMode::Disabled,
        other => return Err(format!("unknown proxy mode: {other}")),
    };
    let mut sup = state.supervisor.lock().await;
    sup.set_proxy_mode_selection(parsed).await?;
    let snap = sup.runtime_state();
    Ok(RuntimeStateView {
        bootstrap: snap.bootstrap,
        proxy: snap.proxy,
        stats: snap.stats,
    })
}

#[tauri::command]
pub async fn update_listen_port(
    listen_port: u16,
    state: State<'_, AppState>,
) -> Result<RuntimeStateView, String> {
    let mut sup = state.supervisor.lock().await;
    sup.update_listen_port(listen_port).await?;
    let snap = sup.runtime_state();
    Ok(RuntimeStateView {
        bootstrap: snap.bootstrap,
        proxy: snap.proxy,
        stats: snap.stats,
    })
}

#[tauri::command]
pub fn get_bootstrap_state(state: State<'_, AppState>) -> BootstrapState {
    state.bootstrap_state()
}

#[tauri::command]
pub async fn get_proxy_settings(state: State<'_, AppState>) -> Result<ProxySettingsView, String> {
    let sup = state.supervisor.lock().await;
    let cfg = sup.proxy_config();
    let skip_sso_accounts = match config_file_path() {
        Some(p) if p.exists() => load_config_file(&p)
            .map(|f| f.skip_sso_accounts)
            .unwrap_or_default(),
        _ => String::new(),
    };
    Ok(ProxySettingsView {
        listen_host: cfg.listen_host.clone(),
        listen_port: cfg.listen_port,
        upstream_host: cfg.upstream_host.clone(),
        upstream_port: cfg.upstream_port,
        proxy_only: cfg.proxy_only,
        skip_sso_accounts,
    })
}

#[tauri::command]
pub fn get_recent_logs(
    state: State<'_, AppState>,
    limit: Option<usize>,
    min_level: Option<String>,
) -> LogSnapshot {
    let limit = limit.unwrap_or(200).min(runtime::log_store::MAX_PER_LEVEL);
    let min_level = min_level.as_deref().unwrap_or("DEBUG");
    LogSnapshot {
        lines: state.log_store.recent_at_level(min_level, limit),
        file_path: state.log_file.as_ref().map(|p| p.display().to_string()),
    }
}

#[tauri::command]
pub async fn update_proxy_settings(
    settings: ProxySettingsView,
    state: State<'_, AppState>,
) -> Result<ProxySettingsView, String> {
    let mut sup = state.supervisor.lock().await;
    if sup.snapshot().bootstrap.proxy_lifecycle == proxy_core::model::ProxyLifecycle::Running {
        return Err("stop proxy before changing settings".into());
    }
    let path = config_file_path().ok_or("config path unavailable")?;
    let mut file = if path.exists() {
        load_config_file(&path).map_err(|e| e.to_string())?
    } else {
        ConfigFileV1::default()
    };
    file.listen_host = settings.listen_host.clone();
    file.listen_port = settings.listen_port;
    file.upstream_host = settings.upstream_host.clone();
    file.upstream_port = settings.upstream_port;
    file.proxy_only = settings.proxy_only;
    file.skip_sso_accounts = settings.skip_sso_accounts.clone();
    save_config_file(&path, &file).map_err(|e| e.to_string())?;
    sup.apply_runtime_config(&file)?;
    let cfg = sup.proxy_config();
    Ok(ProxySettingsView {
        listen_host: cfg.listen_host.clone(),
        listen_port: cfg.listen_port,
        upstream_host: cfg.upstream_host.clone(),
        upstream_port: cfg.upstream_port,
        proxy_only: cfg.proxy_only,
        skip_sso_accounts: settings.skip_sso_accounts,
    })
}

#[tauri::command]
pub fn show_window(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        window.show().map_err(|e| e.to_string())?;
        let _ = window.set_title(&proxy_core::window_title());
        window.set_focus().map_err(|e| e.to_string())?;
    }
    crate::tray::update_toggle_menu_label(&app);
    Ok(())
}

#[tauri::command]
pub fn hide_window(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        window.hide().map_err(|e| e.to_string())?;
    }
    crate::tray::update_toggle_menu_label(&app);
    Ok(())
}

#[tauri::command]
pub async fn request_shutdown(app: AppHandle, _state: State<'_, AppState>) -> Result<(), String> {
    crate::tray::shutdown_and_exit(app).await;
    Ok(())
}
