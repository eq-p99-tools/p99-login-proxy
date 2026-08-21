use std::collections::{HashMap, HashSet};
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};

use std::time::Duration;

use proxy_core::model::{ProxyLifecycle, WsConnectionState};
use proxy_core::ProxyMode;
use proxy_core::{
    config_file_path, detect_rustle_ui, discover_and_persist_eq_directory,
    ensure_eqclient_log_enabled, get_client_settings, load_config, load_local_data,
    resolve_sso_api_url, resolve_sso_ca_bundle, save_config_file, save_local_characters,
    try_load_local_data, ConfigFileV1, EqConfigStatus, EqHostWriter, LocalCharacter,
    SsoCaBundleMode, ValidatedConfig,
};

use secrecy::ExposeSecret;

use serde_json::Value;

use tokio::sync::{mpsc, watch};

use tokio::task::JoinSet;

use tokio_util::sync::CancellationToken;

use tracing::{info, warn};

use crate::config::{eqhost_connect_host, ProxyLocalData, ProxyRuntimeConfig};

use crate::events::AppEvent;

use crate::log_watcher::EqLogWatcherHandle;

use crate::proxy_stats::ProxyStatsTracker;

use crate::secrets::{PersistentSecretStore, SecretStore};

use crate::status::{set_lifecycle, set_ws_error, set_ws_state, RuntimeSnapshot, SnapshotTx};

use crate::udp::UdpProxyHandle;

use crate::websocket::{SsoClientConfig, WsHandle, WsStateEvent};

const EVENT_CAPACITY: usize = 256;

pub struct AppSupervisor {
    cancel: CancellationToken,

    join_set: JoinSet<()>,

    snapshot_tx: SnapshotTx,

    event_tx: mpsc::Sender<AppEvent>,

    secrets: Arc<dyn SecretStore>,

    proxy_config: ProxyRuntimeConfig,

    local_data: ProxyLocalData,

    local_character_names: Arc<RwLock<HashSet<String>>>,

    pending_local_account: Option<String>,

    auto_add_local_characters: bool,

    eq_directory: Option<PathBuf>,

    eq_directory_secondary: Option<PathBuf>,

    rustle_checked: bool,

    rustle_present: bool,

    warn_rustle: bool,

    sso_backend: String,

    udp: Option<UdpProxyHandle>,

    ws: Option<WsHandle>,

    log_watchers: Vec<EqLogWatcherHandle>,

    inventory_watcher: Option<crate::inventory_watcher::InventoryWatcherHandle>,

    stats: Arc<ProxyStatsTracker>,
}

impl AppSupervisor {
    pub fn new() -> (
        Self,
        watch::Receiver<RuntimeSnapshot>,
        mpsc::Receiver<AppEvent>,
    ) {
        let cancel = CancellationToken::new();

        let (snapshot_tx, snapshot_rx) = crate::status::snapshot_channel();

        let (event_tx, event_rx) = mpsc::channel(EVENT_CAPACITY);

        let config_path = config_file_path();

        let mut file = match load_config() {
            Ok(f) => f,
            Err(e) => {
                warn!("failed to load config ({e}); secrets/bootstrap may be incomplete");
                ConfigFileV1::default()
            }
        };

        if let Some(ref path) = config_path {
            let _ = discover_and_persist_eq_directory(&mut file, path);
        }

        let persistent = PersistentSecretStore::new(config_path.clone());
        persistent.bootstrap_from_config(&file.api_tokens);
        let mut token_backends: Vec<String> = file.api_tokens.keys().cloned().collect();
        for backend in file.sso_backends.keys() {
            if !token_backends.iter().any(|name| name == backend) {
                token_backends.push(backend.clone());
            }
        }
        if !token_backends.iter().any(|b| b == &file.sso_backend) {
            token_backends.push(file.sso_backend.clone());
        }
        persistent.bootstrap_from_keyring(&token_backends);
        let secrets: Arc<dyn SecretStore> = Arc::new(persistent);

        let sso_backend = file.sso_backend.clone();
        let sso_api = resolve_sso_api_url(&file);
        let (proxy_config, eq_directory, eq_directory_secondary) =
            match ValidatedConfig::from_file(&file) {
                Ok(validated) => {
                    let eq_directory = validated.eq_directory.clone();
                    let eq_directory_secondary = validated.eq_directory_secondary.clone();
                    let cfg = ProxyRuntimeConfig::from_validated(&validated, sso_api);
                    (cfg, eq_directory, eq_directory_secondary)
                }
                Err(e) => {
                    warn!("config validation failed ({e}); using defaults for listen/upstream");
                    let sso_ca_bundle = resolve_sso_ca_bundle(&file.sso_ca_bundle)
                        .unwrap_or(SsoCaBundleMode::WebpkiRoots);
                    let cfg = ProxyRuntimeConfig {
                        sso_backend: sso_backend.clone(),
                        sso_api_url: sso_api,
                        sso_verify_tls: file.sso_verify_tls,
                        sso_ca_bundle,
                        sso_timeout_secs: file.login_timeout_secs.max(1),
                        proxy_only: file.proxy_only,
                        skip_sso_accounts: proxy_core::parse_skip_sso_accounts(
                            &file.skip_sso_accounts,
                        )
                        .into_iter()
                        .collect(),
                        ..ProxyRuntimeConfig::default()
                    };
                    let eq_directory = file.eq_directory.as_ref().map(PathBuf::from);
                    let eq_directory_secondary =
                        file.eq_directory_secondary.as_ref().map(PathBuf::from);
                    (cfg, eq_directory, eq_directory_secondary)
                }
            };

        info!(
            sso_backend = %sso_backend,
            api_token_backends = file.api_tokens.len(),
            has_token = secrets.has_token(&sso_backend),
            "loaded SSO config"
        );

        let bundle = load_local_data();

        let local_data = ProxyLocalData {
            accounts: bundle.accounts,
            characters: bundle.characters,
        };

        let local_character_names = Arc::new(RwLock::new(
            local_data
                .characters
                .list()
                .into_iter()
                .map(|c| c.name.to_lowercase())
                .collect::<HashSet<String>>(),
        ));

        let mut snap = snapshot_rx.borrow().clone();

        snap.bootstrap.has_token = secrets.has_token(&sso_backend);

        let _ = snapshot_tx.send(snap);

        let stats = Arc::new(ProxyStatsTracker::default());

        let supervisor = Self {
            cancel,

            join_set: JoinSet::new(),

            snapshot_tx,

            event_tx,

            secrets,

            proxy_config,

            local_data,

            local_character_names,

            pending_local_account: None,

            auto_add_local_characters: file.auto_add_local_characters,

            eq_directory,

            eq_directory_secondary,

            rustle_checked: false,

            rustle_present: false,

            warn_rustle: file.warn_rustle,

            sso_backend,

            udp: None,

            ws: None,

            log_watchers: Vec::new(),

            inventory_watcher: None,

            stats,
        };

        (supervisor, snapshot_rx, event_rx)
    }

    pub fn set_local_data(&mut self, local: ProxyLocalData) {
        self.local_data = local.clone();
        self.refresh_local_character_names();
        if let Some(udp) = &self.udp {
            udp.update_local_data(local);
        }
    }

    pub fn proxy_config(&self) -> &ProxyRuntimeConfig {
        &self.proxy_config
    }

    pub fn sso_backend(&self) -> &str {
        &self.sso_backend
    }

    pub fn eq_directory(&self) -> Option<&PathBuf> {
        self.eq_directory.as_ref()
    }

    pub fn local_data(&self) -> &ProxyLocalData {
        &self.local_data
    }

    pub fn set_eq_directory(&mut self, path: Option<PathBuf>) {
        self.eq_directory = path;
        self.rustle_checked = false;
    }

    pub fn reload_local_data(&mut self) -> Result<(), String> {
        let bundle = try_load_local_data().map_err(|error| error.to_string())?;
        self.set_local_data(ProxyLocalData {
            accounts: bundle.accounts,
            characters: bundle.characters,
        });
        info!("local account/character data reloaded");
        Ok(())
    }

    fn refresh_local_character_names(&self) {
        let names: HashSet<String> = self
            .local_data
            .characters
            .list()
            .into_iter()
            .map(|c| c.name.to_lowercase())
            .collect();
        if let Ok(mut guard) = self.local_character_names.write() {
            *guard = names;
        }
    }

    pub fn note_login_method(&mut self, method: &str, account: &str) {
        self.pending_local_account =
            if matches!(method, "local" | "local_char") && !account.is_empty() {
                Some(account.trim().to_lowercase())
            } else {
                None
            };
    }

    pub fn apply_local_character_update(
        &mut self,
        name: &str,
        park: Option<&str>,
        bind: Option<&str>,
        level: Option<i32>,
        class: Option<&str>,
        items: Option<&HashMap<String, Value>>,
    ) -> bool {
        let Some(existing) = self.local_data.characters.find_by_name(name).cloned() else {
            return false;
        };

        let mut changed = false;
        let mut updated = existing;

        if let Some(park) = park {
            if updated.park.as_deref() != Some(park) {
                updated.park = Some(park.to_string());
                changed = true;
            }
        }
        if let Some(bind) = bind {
            if updated.bind.as_deref() != Some(bind) {
                updated.bind = Some(bind.to_string());
                changed = true;
            }
        }
        if let Some(level) = level {
            if updated.level != Some(level) {
                updated.level = Some(level);
                changed = true;
            }
        }
        if let Some(class) = class {
            if updated.class.as_deref() != Some(class) {
                updated.class = Some(class.to_string());
                changed = true;
            }
        }
        if let Some(items) = items {
            for (key, value) in items {
                let current = updated.items.get(key);
                if current != Some(value) {
                    updated.items.insert(key.clone(), value.clone());
                    changed = true;
                }
            }
        }

        if !changed {
            return false;
        }

        if self.local_data.characters.upsert(updated).is_err() {
            warn!(character = %name, "failed to upsert local character update");
            return false;
        }

        if let Err(e) = save_local_characters(&self.local_data.characters) {
            warn!(character = %name, error = %e, "failed to save local characters after update");
            return false;
        }

        self.refresh_local_character_names();
        true
    }

    pub fn try_auto_create_local_character(&mut self, character_name: &str) -> bool {
        if !self.auto_add_local_characters {
            return false;
        }
        if character_name.trim().is_empty() {
            return false;
        }

        let Some(pending) = self.pending_local_account.clone() else {
            return false;
        };
        if !self.local_data.accounts.contains_alias(&pending) {
            warn!(
                character = %character_name,
                account = %pending,
                "skipping auto-add: pending local account is no longer in local_accounts.csv"
            );
            return false;
        }

        if self.local_data.characters.contains_name(character_name) {
            let existing_account = self
                .local_data
                .characters
                .find_by_name(character_name)
                .map(|c| c.account_alias.to_lowercase())
                .unwrap_or_default();
            if existing_account != pending {
                warn!(
                    character = %character_name,
                    existing_account = %existing_account,
                    pending_account = %pending,
                    "local character bound to different account; not overwriting"
                );
            }
            return false;
        }

        let character = LocalCharacter {
            name: character_name.to_string(),
            account_alias: pending,
            server: String::new(),
            class: None,
            level: None,
            bind: None,
            park: None,
            items: HashMap::new(),
        };

        if self.local_data.characters.upsert(character).is_err() {
            warn!(character = %character_name, "failed to auto-create local character");
            return false;
        }

        if let Err(e) = save_local_characters(&self.local_data.characters) {
            warn!(character = %character_name, error = %e, "failed to save auto-created local character");
            return false;
        }

        self.refresh_local_character_names();
        info!(character = %character_name, "auto-created local character row");
        true
    }

    pub async fn reconnect_sso(&mut self) {
        self.restart_ws().await;
    }

    pub async fn set_sso_backend(
        &mut self,
        backend: String,
        api_url: Option<String>,
    ) -> Result<(), String> {
        let resolved_url = api_url
            .clone()
            .filter(|u| !u.trim().is_empty())
            .unwrap_or_else(|| {
                let mut stub = load_config().unwrap_or_default();
                stub.sso_backend = backend.clone();
                resolve_sso_api_url(&stub)
            });
        self.persist_config(|file| {
            file.sso_backend = backend.clone();
            file.sso_api_url = Some(resolved_url.clone());
        })?;

        let was_running = self.udp.is_some();
        self.sso_backend = backend.clone();
        self.proxy_config.sso_backend = backend;
        self.proxy_config.sso_api_url = resolved_url;
        let _ = self.secrets.load_token(&self.sso_backend);
        self.sync_bootstrap_token_flag();
        self.restart_ws().await;
        if was_running {
            if let Some(udp) = self.udp.take() {
                udp.stop().await;
            }
            self.start_proxy().await?;
        }
        Ok(())
    }

    pub fn persist_config<F>(&self, update: F) -> Result<ConfigFileV1, String>
    where
        F: FnOnce(&mut ConfigFileV1),
    {
        let path = config_file_path().ok_or("config path unavailable")?;
        let mut file = load_config().map_err(|e| e.to_string())?;
        update(&mut file);
        save_config_file(&path, &file).map_err(|e| e.to_string())?;
        Ok(file)
    }

    pub fn apply_runtime_config(&mut self, file: &ConfigFileV1) -> Result<(), String> {
        let sso_backend = file.sso_backend.clone();
        let sso_api = resolve_sso_api_url(file);
        let validated = ValidatedConfig::from_file(file).map_err(|e| e.to_string())?;
        self.proxy_config = ProxyRuntimeConfig::from_validated(&validated, sso_api);
        self.sso_backend = sso_backend;
        self.eq_directory = validated.eq_directory.clone();
        self.eq_directory_secondary = validated.eq_directory_secondary.clone();
        self.rustle_checked = false;
        self.warn_rustle = file.warn_rustle;
        self.auto_add_local_characters = file.auto_add_local_characters;
        Ok(())
    }

    fn eq_install_roots(&self) -> Vec<PathBuf> {
        let mut roots = Vec::new();
        let mut seen = std::collections::HashSet::new();
        for path in [&self.eq_directory, &self.eq_directory_secondary]
            .into_iter()
            .flatten()
        {
            let key = path.display().to_string().to_lowercase();
            if seen.insert(key) && path.is_dir() {
                roots.push(path.clone());
            }
        }
        roots
    }

    fn client_settings_json(&mut self) -> serde_json::Value {
        let roots = self.eq_install_roots();
        if let Some(primary) = roots.first() {
            if !ensure_eqclient_log_enabled(primary) {
                warn!(
                    path = %primary.join("eqclient.ini").display(),
                    "could not ensure EQ logging is enabled"
                );
            }
        }
        if !self.rustle_checked && !roots.is_empty() {
            self.rustle_present = detect_rustle_ui(&roots);
            self.rustle_checked = true;
            if self.rustle_present && self.warn_rustle {
                let _ = self.event_tx.try_send(AppEvent::RustleWarning {
                    message: "A modified UI skin with non-standard inventory slots was \
                              detected in your EverQuest uifiles directory. This may \
                              cause issues or be blocked by some servers."
                        .to_string(),
                });
            }
        }
        get_client_settings(&roots, self.rustle_checked, self.rustle_present)
    }

    pub fn snapshot(&self) -> RuntimeSnapshot {
        self.snapshot_tx.borrow().clone()
    }

    pub fn secrets(&self) -> Arc<dyn SecretStore> {
        self.secrets.clone()
    }

    pub async fn set_sso_token(&mut self, token: &str) -> Result<(), String> {
        self.secrets
            .store_token(&self.sso_backend, token)
            .map_err(|e| e.to_string())?;

        self.sync_bootstrap_token_flag();

        self.restart_ws().await;

        Ok(())
    }

    pub async fn clear_sso_token(&mut self) -> Result<(), String> {
        self.secrets
            .clear_token(&self.sso_backend)
            .map_err(|e| e.to_string())?;

        self.sync_bootstrap_token_flag();

        self.stop_ws().await;

        Ok(())
    }

    pub fn sso_client(&self) -> Option<crate::websocket::SsoClient> {
        self.ws.as_ref().map(|w| w.client())
    }

    /// Re-read the SSO token flag from secrets and push it into the runtime snapshot.
    pub fn sync_bootstrap_token_flag(&self) {
        let mut snap = self.snapshot_tx.borrow().clone();

        snap.bootstrap.has_token = self.secrets.has_token(&self.sso_backend);

        let _ = self.snapshot_tx.send(snap);
    }

    async fn restart_ws(&mut self) {
        self.stop_ws().await;

        self.ensure_ws_started().await;
        self.ensure_log_watcher();
        self.ensure_inventory_watcher();
    }

    async fn ensure_ws_started(&mut self) {
        if self.ws.is_some() {
            return;
        }

        let token = match self.secrets.load_token(&self.sso_backend) {
            Ok(Some(t)) => t,

            _ => return,
        };

        if token.expose_secret().is_empty() || self.proxy_config.sso_api_url.is_empty() {
            return;
        }

        let (tx, mut rx) = mpsc::channel(32);

        let snapshot_tx = self.snapshot_tx.clone();

        self.join_set.spawn(async move {
            while let Some(ev) = rx.recv().await {
                let mut snap = snapshot_tx.borrow().clone();

                match ev {
                    WsStateEvent::Connecting => {
                        set_ws_state(&mut snap, WsConnectionState::Connecting)
                    }

                    WsStateEvent::Connected { .. } => {
                        set_ws_state(&mut snap, WsConnectionState::Connected)
                    }

                    WsStateEvent::Disconnected => {
                        set_ws_state(&mut snap, WsConnectionState::Disconnected)
                    }

                    WsStateEvent::AuthFailed { reason } => {
                        set_ws_state(&mut snap, WsConnectionState::AuthFailed);

                        set_ws_error(&mut snap, Some(reason));
                    }

                    WsStateEvent::Parked => set_ws_state(&mut snap, WsConnectionState::Parked),
                }

                let _ = snapshot_tx.send(snap);
            }
        });

        let ws_config = SsoClientConfig {
            api_url: self.proxy_config.sso_api_url.clone(),

            backend_name: self.sso_backend.clone(),

            client_version: self.proxy_config.client_version.clone(),

            verify_tls: self.proxy_config.sso_verify_tls,

            ca_bundle: self.proxy_config.sso_ca_bundle.clone(),

            timeout_secs: self.proxy_config.sso_timeout_secs,

            client_settings: self.client_settings_json(),
        };

        let handle = WsHandle::start(ws_config, token, self.cancel.child_token(), Some(tx));

        info!(backend = %self.sso_backend, "SSO WebSocket task started");

        self.ws = Some(handle);
        if let Some(udp) = &self.udp {
            udp.update_sso_client(self.sso_client());
        }
    }

    fn local_character_names(&self) -> HashSet<String> {
        self.local_character_names
            .read()
            .ok()
            .map(|names| names.clone())
            .unwrap_or_default()
    }

    fn should_watch_logs(&self) -> bool {
        !self.eq_install_roots().is_empty()
            && (self.secrets.has_token(&self.sso_backend)
                || !self.local_character_names().is_empty())
    }

    fn ensure_log_watcher(&mut self) {
        if !self.log_watchers.is_empty() || !self.should_watch_logs() {
            return;
        }
        let roots = self.eq_install_roots();
        if roots.is_empty() {
            return;
        }

        for root in roots {
            let Some(logs_dir) = Self::find_logs_subdir(&root) else {
                warn!(dir = %root.display(), "no Logs subdirectory found in EQ install root");
                continue;
            };
            let handle = EqLogWatcherHandle::start(
                logs_dir.clone(),
                self.sso_client(),
                Arc::clone(&self.local_character_names),
                self.stats.clone(),
                self.event_tx.clone(),
                self.cancel.child_token(),
            );
            info!(dir = %logs_dir.display(), "EQ log watcher started");
            self.log_watchers.push(handle);
        }
    }

    fn find_logs_subdir(eq_root: &Path) -> Option<PathBuf> {
        let entries = std::fs::read_dir(eq_root).ok()?;
        for entry in entries.flatten() {
            let name = entry.file_name();
            if name.to_string_lossy().eq_ignore_ascii_case("logs") && entry.path().is_dir() {
                return Some(entry.path());
            }
        }
        None
    }

    fn ensure_inventory_watcher(&mut self) {
        if self.inventory_watcher.is_some() || !self.should_watch_logs() {
            return;
        }
        let roots = self.eq_install_roots();
        if roots.is_empty() {
            return;
        }
        let handle = crate::inventory_watcher::InventoryWatcherHandle::start(
            roots,
            self.sso_client(),
            Arc::clone(&self.local_character_names),
            self.event_tx.clone(),
            self.cancel.child_token(),
        );
        info!("EQ inventory watcher started");
        self.inventory_watcher = Some(handle);
    }

    pub fn runtime_state(&self) -> RuntimeSnapshot {
        self.publish_snapshot_inner();
        self.snapshot_tx.borrow().clone()
    }

    fn publish_snapshot_inner(&self) {
        self.publish_runtime_state(None, None);
    }

    fn eq_config_status(&self) -> EqConfigStatus {
        let Some(ref eq_dir) = self.eq_directory else {
            return EqConfigStatus {
                eqhost_proxy_enabled: false,
                eqclient_log_enabled: false,
            };
        };
        EqConfigStatus::evaluate(
            eq_dir,
            &self.proxy_config.listen_host,
            self.proxy_config.listen_port,
        )
    }

    fn publish_runtime_state(
        &self,
        lifecycle: Option<ProxyLifecycle>,
        listen_addr: Option<SocketAddr>,
    ) {
        let eq_status = self.eq_config_status();
        self.stats.set_eq_config_status(
            eq_status.eqhost_proxy_enabled,
            eq_status.eqclient_log_enabled,
        );
        let mut snap = self.snapshot_tx.borrow().clone();
        if let Some(state) = lifecycle {
            set_lifecycle(&mut snap, state);
        }
        if let Some(addr) = listen_addr {
            snap.bootstrap.listen_address = addr.ip().to_string();
            snap.bootstrap.listen_port = addr.port();
            snap.proxy.listen_address = addr.to_string();
        }
        snap.stats = self.stats.snapshot(
            &snap.bootstrap.listen_address,
            snap.bootstrap.listen_port,
            snap.proxy.client_connected,
        );
        let _ = self.snapshot_tx.send(snap);
    }

    pub fn touch_snapshot(&self) {
        self.publish_snapshot_inner();
    }

    fn set_startup_error(&self, error: Option<String>) {
        let mut snapshot = self.snapshot_tx.borrow().clone();
        snapshot.bootstrap.startup_error = error;
        let _ = self.snapshot_tx.send(snapshot);
    }

    /// Parity with Python `eq_config.enable_proxy()` on startup / mode change.
    fn ensure_eqhost_proxy_enabled(&self) {
        let Some(ref eq_dir) = self.eq_directory else {
            return;
        };
        let proxy_host = eqhost_connect_host(&self.proxy_config.listen_host);
        if EqHostWriter::is_proxy_enabled_in_directory(
            eq_dir,
            proxy_host,
            self.proxy_config.listen_port,
        ) {
            return;
        }
        if let Err(e) = EqHostWriter::enable_proxy(
            eq_dir,
            proxy_host,
            self.proxy_config.listen_port,
            &self.proxy_config.upstream_host,
            self.proxy_config.upstream_port,
        ) {
            warn!(dir = %eq_dir.display(), error = %e, "failed to enable eqhost proxy line");
        } else {
            info!(dir = %eq_dir.display(), "eqhost.txt updated for proxy");
            self.touch_snapshot();
        }
    }

    pub async fn bootstrap_startup(&mut self) {
        let file = match load_config() {
            Ok(f) => f,
            Err(e) => {
                warn!("bootstrap_startup: config load failed ({e})");
                return;
            }
        };

        let mode = ProxyMode::from_config(file.proxy_enabled, file.proxy_only);
        self.stats.set_mode(mode);
        self.proxy_config.proxy_only = file.proxy_only;

        if let Some(ref eq_dir) = self.eq_directory {
            ensure_eqclient_log_enabled(eq_dir);
        }

        // Python starts ws_client.start() at app launch, independent of the UDP proxy.
        self.ensure_ws_started().await;
        self.ensure_log_watcher();
        self.ensure_inventory_watcher();

        if file.proxy_enabled && self.eq_directory.is_some() {
            // Do not persist unchanged config during bootstrap. Read-only config or
            // EQ files must not prevent the UDP proxy itself from starting.
            if let Err(e) = self.start_proxy().await {
                warn!("bootstrap_startup: auto-start proxy failed: {e}");
                self.set_startup_error(Some(
                    "Failed to start UDP proxy, check if another instance is running, and restart."
                        .into(),
                ));
            }
        } else if !file.proxy_enabled {
            self.publish_snapshot_inner();
        }

        info!(
            proxy_enabled = file.proxy_enabled,
            proxy_only = file.proxy_only,
            mode = ?mode,
            "startup config restored"
        );
    }

    pub async fn set_proxy_mode_selection(&mut self, mode: ProxyMode) -> Result<(), String> {
        let (proxy_enabled, proxy_only) = match mode {
            ProxyMode::Disabled => (false, false),
            ProxyMode::EnabledSso => (true, false),
            ProxyMode::EnabledProxyOnly => (true, true),
        };

        if mode.is_running() && self.eq_directory.is_none() {
            return Err("EverQuest directory not configured. Set it on the Advanced tab.".into());
        }

        self.persist_config(|file| {
            file.proxy_enabled = proxy_enabled;
            file.proxy_only = proxy_only;
        })?;
        self.stats.set_mode(mode);
        self.proxy_config.proxy_only = proxy_only;
        // Publish the selected/configured mode before performing socket work. If the
        // listener cannot start (for example, the port is occupied), the selector
        // still reflects the persisted user choice while lifecycle remains stopped.
        self.publish_snapshot_inner();

        match mode {
            ProxyMode::Disabled => {
                self.stop_proxy().await;
            }
            ProxyMode::EnabledSso | ProxyMode::EnabledProxyOnly => {
                if self.udp.is_some() {
                    self.stop_proxy().await;
                }
                self.start_proxy().await?;
            }
        }
        self.publish_snapshot_inner();
        Ok(())
    }

    pub async fn update_listen_port(&mut self, listen_port: u16) -> Result<(), String> {
        if listen_port == 0 {
            return Err("listen_port must be between 1 and 65535".into());
        }

        let file = self.persist_config(|file| {
            file.listen_port = listen_port;
        })?;
        self.apply_runtime_config(&file)?;

        let should_run = file.proxy_enabled;
        if self.udp.is_some() {
            self.stop_proxy().await;
        }

        if should_run {
            if self.eq_directory.is_none() {
                return Err(
                    "EverQuest directory not configured. Set it on the Advanced tab.".into(),
                );
            }
            self.start_proxy().await?;
        }

        self.publish_snapshot_inner();
        Ok(())
    }

    pub fn stats_tracker(&self) -> Arc<ProxyStatsTracker> {
        self.stats.clone()
    }

    async fn stop_ws(&mut self) {
        if let Some(ws) = self.ws.take() {
            ws.stop().await;
            if let Some(udp) = &self.udp {
                udp.update_sso_client(None);
            }

            let mut snap = self.snapshot_tx.borrow().clone();

            set_ws_state(&mut snap, WsConnectionState::Disconnected);

            let _ = self.snapshot_tx.send(snap);
        }
    }

    pub async fn start_proxy(&mut self) -> Result<(), String> {
        if self.udp.is_some() {
            return Err("proxy already running".into());
        }

        self.publish_runtime_state(Some(ProxyLifecycle::Starting), None);

        self.ensure_ws_started().await;

        self.ensure_log_watcher();
        self.ensure_inventory_watcher();

        info!("starting UDP login proxy");

        let config = self.proxy_config.clone();

        let local = self.local_data.clone();

        let sso = self.sso_client();

        let handle = match UdpProxyHandle::start(
            config.clone(),
            local,
            self.cancel.child_token(),
            self.event_tx.clone(),
            sso,
        )
        .await
        {
            Ok(handle) => handle,
            Err(error) => {
                self.stats.clear_uptime();
                self.publish_runtime_state(Some(ProxyLifecycle::Stopped), None);
                return Err(error);
            }
        };

        let listen_addr = handle.listen_addr;

        self.udp = Some(handle);

        self.stats.reset_uptime();
        self.publish_runtime_state(Some(ProxyLifecycle::Running), Some(listen_addr));
        self.set_startup_error(None);

        info!(listen = %listen_addr, "UDP login proxy running");

        self.ensure_eqhost_proxy_enabled();

        Ok(())
    }

    /// Restart the UDP listener socket without changing the persisted proxy
    /// mode. Used to recover the transport after the machine resumes from sleep
    /// (parity with the Python ``WM_POWERBROADCAST`` handler).
    pub async fn bounce_proxy_transport(&mut self) -> Result<(), String> {
        if self.udp.is_none() {
            return Ok(());
        }
        info!("restarting UDP proxy transport after system resume");
        self.publish_runtime_state(Some(ProxyLifecycle::Stopping), None);
        if let Some(udp) = self.udp.take() {
            udp.stop().await;
        }
        self.start_proxy().await
    }

    /// Parity with Python `eq_config.disable_proxy()` when eqhost points at the proxy.
    fn restore_eqhost_if_using_proxy(&self) {
        let Some(ref eq_dir) = self.eq_directory else {
            return;
        };
        let proxy_host = eqhost_connect_host(&self.proxy_config.listen_host);
        if !EqHostWriter::is_proxy_enabled_in_directory(
            eq_dir,
            proxy_host,
            self.proxy_config.listen_port,
        ) {
            return;
        }
        if let Err(e) = EqHostWriter::disable_proxy(
            eq_dir,
            &self.proxy_config.upstream_host,
            self.proxy_config.upstream_port,
        ) {
            warn!(dir = %eq_dir.display(), error = %e, "failed to restore eqhost.txt");
        } else {
            info!(dir = %eq_dir.display(), "eqhost.txt restored from backup");
            self.touch_snapshot();
        }
    }

    pub async fn stop_proxy(&mut self) {
        let was_running = self.udp.is_some();
        if was_running {
            self.publish_runtime_state(Some(ProxyLifecycle::Stopping), None);

            info!("stopping UDP login proxy");

            if let Some(udp) = self.udp.take() {
                udp.stop().await;
            }

            self.stats.clear_uptime();
        }

        self.restore_eqhost_if_using_proxy();
        self.publish_runtime_state(Some(ProxyLifecycle::Stopped), None);

        if was_running {
            info!("UDP login proxy stopped");
        }
    }

    pub async fn shutdown_in_place(&mut self) {
        info!("supervisor shutdown requested");

        self.cancel.cancel();

        self.stop_proxy().await;

        if let Some(ws) = self.ws.take() {
            ws.stop().await;
        }

        while let Some(watcher) = self.log_watchers.pop() {
            watcher.stop();
        }

        if let Some(watcher) = self.inventory_watcher.take() {
            watcher.stop();
        }

        let drain_deadline = tokio::time::Instant::now() + Duration::from_millis(500);

        while tokio::time::Instant::now() < drain_deadline {
            match self.join_set.try_join_next() {
                Some(Ok(())) => continue,

                Some(Err(e)) => warn!("task join error: {e}"),

                None => break,
            }
        }

        if tokio::time::timeout(Duration::from_secs(1), self.join_set.shutdown())
            .await
            .is_err()
        {
            warn!("background task shutdown timed out");
        }

        info!("supervisor shutdown complete");
    }
}

impl Default for AppSupervisor {
    fn default() -> Self {
        Self::new().0
    }
}
