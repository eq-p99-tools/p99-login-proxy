use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use base64::Engine;
use futures_util::{SinkExt, StreamExt};
use proxy_core::AccountCache;
use proxy_core::SsoCaBundleMode;
use secrecy::{ExposeSecret, SecretString};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::sync::{oneshot, Mutex, RwLock};
use tokio_tungstenite::tungstenite::Message;
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

const RECONNECT_MIN: Duration = Duration::from_secs(1);
const RECONNECT_MAX: Duration = Duration::from_secs(60);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug, Clone)]
pub struct SsoClientConfig {
    pub api_url: String,
    pub backend_name: String,
    pub client_version: String,
    pub verify_tls: bool,
    pub ca_bundle: SsoCaBundleMode,
    pub timeout_secs: u64,
    pub client_settings: Value,
}

#[derive(Debug, Clone)]
pub struct LoginAuthResult {
    pub real_user: Option<String>,
    pub encrypted_credentials: Option<Vec<u8>>,
    pub error: Option<String>,
}

type WsSender = futures_util::stream::SplitSink<
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>,
    Message,
>;

struct SsoClientInner {
    config: SsoClientConfig,
    token: SecretString,
    connected: AtomicBool,
    pending: Mutex<HashMap<String, oneshot::Sender<LoginAuthResult>>>,
    cache: Arc<RwLock<AccountCache>>,
    write: Mutex<Option<Arc<Mutex<WsSender>>>>,
    /// Last `update_location` payload sent per lowercased character name, used to
    /// suppress redundant sends (Python `ws_client._last_sent_location`).
    last_location: Mutex<HashMap<String, serde_json::Map<String, Value>>>,
}

/// Shared SSO WebSocket client used by the UDP proxy for ``login_auth``.
#[derive(Clone)]
pub struct SsoClient {
    inner: Arc<SsoClientInner>,
}

impl SsoClient {
    pub fn new(config: SsoClientConfig, token: SecretString) -> Self {
        Self {
            inner: Arc::new(SsoClientInner {
                config,
                token,
                connected: AtomicBool::new(false),
                pending: Mutex::new(HashMap::new()),
                cache: Arc::new(RwLock::new(AccountCache::default())),
                write: Mutex::new(None),
                last_location: Mutex::new(HashMap::new()),
            }),
        }
    }

    pub fn cache(&self) -> Arc<RwLock<AccountCache>> {
        self.inner.cache.clone()
    }

    pub fn is_connected(&self) -> bool {
        self.inner.connected.load(Ordering::Relaxed)
    }

    pub fn has_credentials(&self) -> bool {
        !self.inner.config.api_url.is_empty() && !self.inner.token.expose_secret().is_empty()
    }

    async fn set_write(&self, write: Option<Arc<Mutex<WsSender>>>) {
        *self.inner.write.lock().await = write;
    }

    async fn send_json<T: Serialize>(&self, value: &T) -> Result<(), String> {
        let write = {
            let guard = self.inner.write.lock().await;
            guard.as_ref().cloned()
        };
        let Some(write) = write else {
            return Err("not connected to send channel".into());
        };
        let text = serde_json::to_string(value).map_err(|e| e.to_string())?;
        let mut guard = write.lock().await;
        guard
            .send(Message::Text(text.into()))
            .await
            .map_err(|e| e.to_string())
    }

    pub async fn request_login_auth(&self, username: &str) -> LoginAuthResult {
        if !self.is_connected() {
            return LoginAuthResult {
                real_user: None,
                encrypted_credentials: None,
                error: Some("WebSocket not connected".into()),
            };
        }

        let request_id = Uuid::new_v4().simple().to_string();
        let (tx, rx) = oneshot::channel();
        self.inner
            .pending
            .lock()
            .await
            .insert(request_id.clone(), tx);

        let outbound = WsOutbound::LoginAuth {
            request_id: &request_id,
            username,
        };
        if let Err(e) = self.send_json(&outbound).await {
            self.inner.pending.lock().await.remove(&request_id);
            return LoginAuthResult {
                real_user: None,
                encrypted_credentials: None,
                error: Some(format!("send failed: {e}")),
            };
        }

        let timeout = Duration::from_secs(self.inner.config.timeout_secs.max(1));
        match tokio::time::timeout(timeout, rx).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => LoginAuthResult {
                real_user: None,
                encrypted_credentials: None,
                error: Some("login_auth channel closed".into()),
            },
            Err(_) => {
                warn!(username = %username, "login_auth request timed out");
                self.inner.pending.lock().await.remove(&request_id);
                LoginAuthResult {
                    real_user: None,
                    encrypted_credentials: None,
                    error: Some("Login auth request timed out".into()),
                }
            }
        }
    }

    pub async fn send_heartbeat(&self, character_name: &str) {
        if !self.is_connected() {
            return;
        }
        let msg = WsOutbound::Heartbeat { character_name };
        let _ = self.send_json(&msg).await;
    }

    pub async fn send_update_location(
        &self,
        character_name: &str,
        park_location: Option<&str>,
        bind_location: Option<&str>,
        level: Option<u32>,
        items: Option<serde_json::Map<String, Value>>,
    ) {
        if !self.is_connected() {
            return;
        }

        // Python tests each optional field for truthiness, so blank locations and
        // empty item maps are never put on the wire.
        let park_location = park_location.filter(|s| !s.is_empty());
        let bind_location = bind_location.filter(|s| !s.is_empty());
        let items = items.filter(|m| !m.is_empty());

        let mut fields = serde_json::Map::new();
        if let Some(park) = park_location {
            fields.insert("park_location".into(), Value::from(park));
        }
        if let Some(bind) = bind_location {
            fields.insert("bind_location".into(), Value::from(bind));
        }
        if let Some(level) = level {
            fields.insert("level".into(), Value::from(level));
        }
        if let Some(ref items) = items {
            fields.insert("items".into(), Value::Object(items.clone()));
        }

        let key = character_name.to_lowercase();
        let merged = {
            let last = self.inner.last_location.lock().await;
            let prev = last.get(&key).cloned().unwrap_or_default();
            match next_location_state(&prev, &fields) {
                Some(merged) => merged,
                None => return,
            }
        };

        let msg = WsOutbound::UpdateLocation {
            character_name,
            park_location,
            bind_location,
            level,
            items: items.as_ref(),
        };
        if self.send_json(&msg).await.is_ok() {
            self.inner.last_location.lock().await.insert(key, merged);
        }
    }

    pub async fn send_fte(&self, mob: &str, player: &str, character_name: &str, eq_log_time: &str) {
        if !self.is_connected() {
            return;
        }
        let msg = WsOutbound::Fte {
            mob,
            player,
            character_name,
            eq_log_time,
        };
        let _ = self.send_json(&msg).await;
    }

    pub async fn send_mob_death(&self, mob: &str, eq_log_time: &str, character_name: &str) {
        if !self.is_connected() {
            return;
        }
        let msg = WsOutbound::MobDeath {
            mob,
            eq_log_time,
            character_name,
        };
        let _ = self.send_json(&msg).await;
    }
}

/// Merge outgoing `update_location` fields into the last-sent snapshot, returning
/// `None` when the update carries nothing new and the send should be suppressed.
///
/// A message with no fields beyond `character_name` always goes out, matching
/// Python's `if data_fields and tentative == prev` guard.
fn next_location_state(
    prev: &serde_json::Map<String, Value>,
    fields: &serde_json::Map<String, Value>,
) -> Option<serde_json::Map<String, Value>> {
    let merged = merge_location_state(prev, fields);
    if !fields.is_empty() && merged == *prev {
        return None;
    }
    Some(merged)
}

/// Fold outgoing `update_location` fields into the last-sent snapshot for a
/// character. `items` merges key-by-key so a partial item update does not erase
/// slots reported earlier; every other field replaces its predecessor. Mirrors
/// Python `ws_client._merge_last_location_state`.
fn merge_location_state(
    prev: &serde_json::Map<String, Value>,
    fields: &serde_json::Map<String, Value>,
) -> serde_json::Map<String, Value> {
    let mut out = prev.clone();
    for (key, value) in fields {
        match (key.as_str(), value.as_object()) {
            ("items", Some(new_items)) => {
                let mut items = out
                    .get("items")
                    .and_then(Value::as_object)
                    .cloned()
                    .unwrap_or_default();
                items.extend(new_items.iter().map(|(k, v)| (k.clone(), v.clone())));
                out.insert("items".into(), Value::Object(items));
            }
            _ => {
                out.insert(key.clone(), value.clone());
            }
        }
    }
    out
}

/// Messages the client sends to the SSO WebSocket server.
///
/// `#[serde(tag = "type", rename_all = "snake_case")]` produces the exact
/// `{"type": "...", ...}` envelope the server dispatches on. Borrowed fields keep
/// sends allocation-free. This is the client-owned half of the contract; the
/// canonical schema lives in `roboToald/schemas/ws-protocol.schema.json`.
#[derive(Debug, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum WsOutbound<'a> {
    Auth {
        access_key: &'a str,
        client_version: &'a str,
        client_settings: &'a Value,
    },
    LoginAuth {
        request_id: &'a str,
        username: &'a str,
    },
    Heartbeat {
        character_name: &'a str,
    },
    UpdateLocation {
        character_name: &'a str,
        #[serde(skip_serializing_if = "Option::is_none")]
        park_location: Option<&'a str>,
        #[serde(skip_serializing_if = "Option::is_none")]
        bind_location: Option<&'a str>,
        #[serde(skip_serializing_if = "Option::is_none")]
        level: Option<u32>,
        #[serde(skip_serializing_if = "Option::is_none")]
        items: Option<&'a serde_json::Map<String, Value>>,
    },
    Fte {
        mob: &'a str,
        player: &'a str,
        character_name: &'a str,
        eq_log_time: &'a str,
    },
    MobDeath {
        mob: &'a str,
        eq_log_time: &'a str,
        character_name: &'a str,
    },
    Pong,
}

/// Messages the client receives from the SSO WebSocket server.
///
/// Tolerant by design so the client survives an evolving server contract:
/// `#[serde(other)] Unknown` absorbs message types this build does not know
/// (e.g. server-only additions), every optional field has `#[serde(default)]`,
/// and unknown extra fields are ignored. The bulk `account_tree` / `changes`
/// payloads stay as `Value` and flow into `AccountCache`; only the control-plane
/// fields the client acts on are strongly typed. Canonical schema:
/// `roboToald/schemas/ws-protocol.schema.json`.
#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum WsInbound {
    FullState {
        #[serde(default)]
        account_tree: Value,
        #[serde(default)]
        dynamic_tag_zones: Vec<String>,
        #[serde(default)]
        dynamic_tag_classes: Vec<String>,
    },
    Delta {
        #[serde(default)]
        changes: Value,
    },
    LoginAuthResponse {
        request_id: String,
        #[serde(default)]
        real_user: Option<String>,
        #[serde(default)]
        encrypted_credentials: Option<String>,
        #[serde(default)]
        error: Option<String>,
    },
    Ping,
    Pong,
    // Server sends `{"type": "error", "detail": ...}`; older/other builds may use
    // `message`/`reason` or the `auth_failed`/`close` tags. Treat them all as a
    // terminal auth error.
    #[serde(alias = "auth_failed", alias = "close")]
    Error {
        #[serde(default, alias = "message", alias = "reason", alias = "error")]
        detail: Option<String>,
    },
    #[serde(other)]
    Unknown,
}

pub struct WsHandle {
    cancel: CancellationToken,
    task: tokio::task::JoinHandle<()>,
    client: SsoClient,
}

impl WsHandle {
    pub fn client(&self) -> SsoClient {
        self.client.clone()
    }

    pub fn start(
        config: SsoClientConfig,
        token: SecretString,
        cancel: CancellationToken,
        on_state: Option<tokio::sync::mpsc::Sender<WsStateEvent>>,
    ) -> Self {
        let client = SsoClient::new(config.clone(), token.clone());
        let client_task = client.clone();
        let child = cancel.child_token();

        let task = tokio::spawn(async move {
            run_ws_loop(client_task, config, token, child, on_state).await;
        });

        Self {
            cancel,
            task,
            client,
        }
    }

    pub async fn stop(self) {
        self.cancel.cancel();
        let mut task = self.task;
        tokio::select! {
            _ = &mut task => {}
            _ = tokio::time::sleep(Duration::from_secs(2)) => {
                task.abort();
                let _ = task.await;
            }
        }
    }
}

#[derive(Debug, Clone)]
pub enum WsStateEvent {
    Connecting,
    Connected { account_count: usize },
    Disconnected,
    AuthFailed { reason: String },
    Parked,
}

fn build_ws_url(api_url: &str) -> String {
    let base = api_url.trim_end_matches('/');
    if let Some(rest) = base.strip_prefix("https://") {
        format!("wss://{rest}/ws/accounts")
    } else if let Some(rest) = base.strip_prefix("http://") {
        format!("ws://{rest}/ws/accounts")
    } else if base.starts_with("wss://") || base.starts_with("ws://") {
        format!("{base}/ws/accounts")
    } else {
        format!("wss://{base}/ws/accounts")
    }
}

async fn run_ws_loop(
    client: SsoClient,
    config: SsoClientConfig,
    token: SecretString,
    cancel: CancellationToken,
    on_state: Option<tokio::sync::mpsc::Sender<WsStateEvent>>,
) {
    let mut delay = RECONNECT_MIN;

    loop {
        if cancel.is_cancelled() {
            break;
        }

        if config.api_url.is_empty() || token.expose_secret().is_empty() {
            notify_state(&on_state, WsStateEvent::Parked);
            tokio::select! {
                _ = cancel.cancelled() => return,
                _ = tokio::time::sleep(Duration::from_secs(30)) => {}
            }
            continue;
        }

        notify_state(&on_state, WsStateEvent::Connecting);
        let url = build_ws_url(&config.api_url);
        if url.starts_with("wss://") && !config.verify_tls {
            warn!("SSO TLS: certificate verification DISABLED (sso_verify_tls=False)");
        }
        info!(%url, backend = %config.backend_name, client_version = %config.client_version, "connecting SSO WebSocket");

        let tls_connector = if url.starts_with("wss://") {
            match crate::sso_tls::build_tls_connector(config.verify_tls, &config.ca_bundle) {
                Ok(connector) => Some(connector),
                Err(error) => {
                    warn!("SSO TLS setup failed: {error}");
                    notify_state(&on_state, WsStateEvent::AuthFailed { reason: error });
                    sleep_backoff(&cancel, delay).await;
                    delay = (delay * 2).min(RECONNECT_MAX);
                    continue;
                }
            }
        } else {
            None
        };

        let connect = tokio::select! {
            biased;
            _ = cancel.cancelled() => return,
            result = tokio::time::timeout(CONNECT_TIMEOUT, async {
                if let Some(connector) = tls_connector {
                    tokio_tungstenite::connect_async_tls_with_config(
                        &url, None, false, Some(connector),
                    )
                    .await
                } else {
                    tokio_tungstenite::connect_async(&url).await
                }
            }) => result,
        };

        match connect {
            Ok(Ok((stream, _))) => {
                delay = RECONNECT_MIN;
                let (write, mut read) = stream.split();
                let write = Arc::new(Mutex::new(write));
                client.set_write(Some(write.clone())).await;

                let auth = WsOutbound::Auth {
                    access_key: token.expose_secret(),
                    client_version: &config.client_version,
                    client_settings: &config.client_settings,
                };
                if let Err(e) = client.send_json(&auth).await {
                    warn!("WS auth send failed: {e}");
                    teardown(&client, &on_state, true, false).await;
                    sleep_backoff(&cancel, delay).await;
                    delay = (delay * 2).min(RECONNECT_MAX);
                    continue;
                }

                debug!(
                    client_version = %config.client_version,
                    client_settings = %config.client_settings,
                    "WS auth message sent, awaiting server response"
                );

                let mut rejected = false;

                loop {
                    tokio::select! {
                        _ = cancel.cancelled() => {
                            teardown(&client, &on_state, true, false).await;
                            return;
                        }
                        msg = read.next() => {
                            match msg {
                                Some(Ok(Message::Text(text))) => {
                                    if matches!(
                                        handle_inbound(&client, &write, &text, &on_state).await,
                                        InboundOutcome::Rejected
                                    ) {
                                        // The rejection reason is already published; publishing
                                        // Disconnected here would immediately overwrite it.
                                        teardown(&client, &on_state, false, true).await;
                                        rejected = true;
                                        break;
                                    }
                                }
                                Some(Ok(Message::Ping(payload))) => {
                                    let _ = write.lock().await.send(Message::Pong(payload)).await;
                                }
                                Some(Ok(Message::Close(frame))) => {
                                    rejected = handle_close_frame(frame, &on_state);
                                    teardown(&client, &on_state, !rejected, rejected).await;
                                    break;
                                }
                                None => {
                                    teardown(&client, &on_state, true, false).await;
                                    break;
                                }
                                Some(Err(e)) => {
                                    warn!("WS read error: {e}");
                                    teardown(&client, &on_state, true, false).await;
                                    break;
                                }
                                _ => {}
                            }
                        }
                    }
                }

                if rejected {
                    // Python parks the WS task after a server rejection rather than
                    // reconnecting, so a bad key or an outdated client does not keep
                    // hitting the server's IP rate limiter and invalid-key audit log.
                    // The supervisor restarts this task via `restart_ws` when the user
                    // reconnects or changes the token/backend.
                    info!("SSO session rejected by server, parking until reconnect is requested");
                    return;
                }
            }
            Ok(Err(e)) => {
                warn!("WS connect failed: {e}");
                client.inner.connected.store(false, Ordering::Relaxed);
                notify_state(&on_state, WsStateEvent::Disconnected);
            }
            Err(_) => {
                warn!(
                    %url,
                    timeout_secs = CONNECT_TIMEOUT.as_secs(),
                    "WS connect timed out"
                );
                client.inner.connected.store(false, Ordering::Relaxed);
                notify_state(&on_state, WsStateEvent::Disconnected);
            }
        }

        sleep_backoff(&cancel, delay).await;
        delay = (delay * 2).min(RECONNECT_MAX);
    }
}

async fn sleep_backoff(cancel: &CancellationToken, delay: Duration) {
    tokio::select! {
        _ = cancel.cancelled() => {}
        _ = tokio::time::sleep(delay) => {}
    }
}

fn notify_state(tx: &Option<tokio::sync::mpsc::Sender<WsStateEvent>>, event: WsStateEvent) {
    if let Some(tx) = tx {
        let _ = tx.try_send(event);
    }
}

async fn cancel_pending(client: &SsoClient) {
    let mut pending = client.inner.pending.lock().await;
    for (_, tx) in pending.drain() {
        let _ = tx.send(LoginAuthResult {
            real_user: None,
            encrypted_credentials: None,
            error: Some("WebSocket disconnected".into()),
        });
    }
}

/// Drop all per-connection state. `notify_disconnected` is false when the caller
/// has already published a terminal state that must not be overwritten.
async fn teardown(
    client: &SsoClient,
    on_state: &Option<tokio::sync::mpsc::Sender<WsStateEvent>>,
    notify_disconnected: bool,
    clear_cache: bool,
) {
    client.set_write(None).await;
    client.inner.connected.store(false, Ordering::Relaxed);
    cancel_pending(client).await;
    client.inner.last_location.lock().await.clear();
    if clear_cache {
        *client.cache().write().await = AccountCache::default();
    }
    if notify_disconnected {
        notify_state(on_state, WsStateEvent::Disconnected);
    }
}

/// True when a close frame carries an application-level rejection.
///
/// The server sends `{"type": "error", ...}` immediately before closing, but the
/// close can win the race, so the close code is the fallback source of the reason.
/// `roboToald` uses 4001 (auth timeout), 4002 (expected auth), 4003 (invalid key /
/// revoked), 4004 (still initializing), 4010 (client too old) and 4011 (client
/// settings rejected); anything in the application range is treated the same way.
fn handle_close_frame(
    frame: Option<tokio_tungstenite::tungstenite::protocol::CloseFrame>,
    on_state: &Option<tokio::sync::mpsc::Sender<WsStateEvent>>,
) -> bool {
    let Some(frame) = frame else {
        return false;
    };
    let code = u16::from(frame.code);
    if !(4000..4100).contains(&code) {
        debug!(code, reason = %frame.reason, "WS closed by server");
        return false;
    }
    let reason = if frame.reason.is_empty() {
        format!("Server rejected the connection (code {code})")
    } else {
        frame.reason.to_string()
    };
    error!(code, %reason, "WS server rejected session");
    notify_state(on_state, WsStateEvent::AuthFailed { reason });
    true
}

/// Human-readable delta summary for debug logs (Python ``ws_client`` delta loop).
fn format_delta_summary(changes: &Value) -> String {
    let Some(changes) = changes.as_array() else {
        return String::new();
    };
    changes
        .iter()
        .map(|change| {
            let action = change.get("action").and_then(Value::as_str).unwrap_or("?");
            let account = change.get("account").and_then(Value::as_str).unwrap_or("?");
            if action == "update" {
                let fields = change
                    .get("fields")
                    .and_then(Value::as_object)
                    .map(|fields| fields.keys().cloned().collect::<Vec<_>>().join(", "))
                    .unwrap_or_default();
                format!("update {account} ({fields})")
            } else {
                format!("{action} {account}")
            }
        })
        .collect::<Vec<_>>()
        .join("; ")
}

/// What the connection loop should do after a message.
#[derive(Debug, PartialEq, Eq)]
enum InboundOutcome {
    /// Keep reading from this connection.
    Continue,
    /// The server rejected the session; park instead of reconnecting.
    Rejected,
}

async fn handle_inbound(
    client: &SsoClient,
    write: &Arc<Mutex<WsSender>>,
    text: &str,
    on_state: &Option<tokio::sync::mpsc::Sender<WsStateEvent>>,
) -> InboundOutcome {
    let inbound: WsInbound = match serde_json::from_str(text) {
        Ok(v) => v,
        Err(e) => {
            debug!(raw = %text, "WS undecodable message: {e}");
            return InboundOutcome::Continue;
        }
    };

    match inbound {
        WsInbound::FullState {
            account_tree,
            dynamic_tag_zones,
            dynamic_tag_classes,
        } => {
            let cache =
                AccountCache::from_parts(&account_tree, &dynamic_tag_zones, &dynamic_tag_classes);
            let count = cache.account_count;
            *client.cache().write().await = cache;
            client.inner.connected.store(true, Ordering::Relaxed);
            notify_state(
                on_state,
                WsStateEvent::Connected {
                    account_count: count,
                },
            );
            info!(accounts = count, "Received full_state ({count} accounts)");
        }
        WsInbound::Delta { changes } => {
            let cache = client.cache();
            let mut guard = cache.write().await;
            guard.apply_delta_changes(&changes);
            let count = guard.account_count;
            drop(guard);
            debug!(summary = %format_delta_summary(&changes), "Received delta");
            notify_state(
                on_state,
                WsStateEvent::Connected {
                    account_count: count,
                },
            );
        }
        WsInbound::LoginAuthResponse {
            request_id,
            real_user,
            encrypted_credentials,
            error,
        } => {
            resolve_login_auth_response(
                client,
                request_id,
                real_user,
                encrypted_credentials,
                error,
            )
            .await;
        }
        WsInbound::Ping => {
            if let Ok(text) = serde_json::to_string(&WsOutbound::Pong) {
                let _ = write.lock().await.send(Message::Text(text.into())).await;
            }
        }
        WsInbound::Pong => debug!("WS pong received"),
        WsInbound::Error { detail } => {
            let reason = detail.unwrap_or_else(|| "authentication failed".to_string());
            error!(%reason, raw = %text, "WS server error / auth rejected");
            notify_state(on_state, WsStateEvent::AuthFailed { reason });
            return InboundOutcome::Rejected;
        }
        WsInbound::Unknown => debug!(raw = %text, "WS unhandled message"),
    }
    InboundOutcome::Continue
}

async fn resolve_login_auth_response(
    client: &SsoClient,
    request_id: String,
    real_user: Option<String>,
    encrypted_credentials: Option<String>,
    error: Option<String>,
) {
    let tx = client.inner.pending.lock().await.remove(&request_id);
    let Some(tx) = tx else {
        return;
    };

    let result = if let Some(error) = error {
        LoginAuthResult {
            real_user: None,
            encrypted_credentials: None,
            error: Some(error),
        }
    } else {
        let encrypted = encrypted_credentials
            .filter(|b64| !b64.is_empty())
            .and_then(|b64| base64::engine::general_purpose::STANDARD.decode(b64).ok());
        LoginAuthResult {
            real_user,
            encrypted_credentials: encrypted,
            error: None,
        }
    };
    let _ = tx.send(result);
}

#[cfg(test)]
mod tests {
    use super::*;
    use secrecy::SecretString;
    use serde_json::json;
    use tokio_tungstenite::tungstenite::protocol::frame::coding::CloseCode;
    use tokio_tungstenite::tungstenite::protocol::CloseFrame;

    fn fields(value: Value) -> serde_json::Map<String, Value> {
        value.as_object().cloned().unwrap()
    }

    #[test]
    fn first_location_update_is_sent() {
        let prev = serde_json::Map::new();
        let next = next_location_state(&prev, &fields(json!({ "park_location": "Sebilis" })));
        assert_eq!(next, Some(fields(json!({ "park_location": "Sebilis" }))));
    }

    #[test]
    fn repeated_location_update_is_suppressed() {
        let prev = fields(json!({ "park_location": "Sebilis", "level": 60 }));
        assert_eq!(
            next_location_state(&prev, &fields(json!({ "park_location": "Sebilis" }))),
            None
        );
    }

    #[test]
    fn changed_location_field_is_sent() {
        let prev = fields(json!({ "park_location": "Sebilis", "level": 60 }));
        let next = next_location_state(&prev, &fields(json!({ "level": 61 })));
        assert_eq!(
            next,
            Some(fields(json!({ "park_location": "Sebilis", "level": 61 })))
        );
    }

    #[test]
    fn items_merge_instead_of_replacing() {
        let prev = fields(json!({ "items": { "seb": true, "vp": false } }));
        let next = next_location_state(&prev, &fields(json!({ "items": { "vp": true } })));
        assert_eq!(
            next,
            Some(fields(json!({ "items": { "seb": true, "vp": true } })))
        );
    }

    #[test]
    fn redundant_item_update_is_suppressed() {
        let prev = fields(json!({ "items": { "seb": true, "vp": false } }));
        assert_eq!(
            next_location_state(&prev, &fields(json!({ "items": { "seb": true } }))),
            None
        );
    }

    #[test]
    fn bare_location_update_is_always_sent() {
        let prev = fields(json!({ "level": 60 }));
        assert_eq!(
            next_location_state(&prev, &serde_json::Map::new()),
            Some(prev)
        );
    }

    fn close_frame(code: u16, reason: &str) -> Option<CloseFrame> {
        Some(CloseFrame {
            code: CloseCode::from(code),
            reason: reason.into(),
        })
    }

    #[test]
    fn application_close_codes_are_rejections() {
        let (tx, mut rx) = tokio::sync::mpsc::channel(4);
        assert!(handle_close_frame(
            close_frame(4010, "Client update required (minimum version: 2.0.0)"),
            &Some(tx)
        ));
        match rx.try_recv().expect("state event") {
            WsStateEvent::AuthFailed { reason } => {
                assert_eq!(reason, "Client update required (minimum version: 2.0.0)");
            }
            other => panic!("expected AuthFailed, got {other:?}"),
        }
    }

    #[test]
    fn application_close_without_reason_still_rejects() {
        let (tx, mut rx) = tokio::sync::mpsc::channel(4);
        assert!(handle_close_frame(close_frame(4003, ""), &Some(tx)));
        match rx.try_recv().expect("state event") {
            WsStateEvent::AuthFailed { reason } => assert!(reason.contains("4003")),
            other => panic!("expected AuthFailed, got {other:?}"),
        }
    }

    #[test]
    fn normal_close_is_not_a_rejection() {
        let (tx, mut rx) = tokio::sync::mpsc::channel(4);
        assert!(!handle_close_frame(close_frame(1000, "bye"), &Some(tx)));
        assert!(rx.try_recv().is_err());
    }

    #[test]
    fn missing_close_frame_is_not_a_rejection() {
        assert!(!handle_close_frame(None, &None));
    }

    #[test]
    fn build_ws_url_https() {
        assert_eq!(
            build_ws_url("https://proxy.p99loginproxy.net"),
            "wss://proxy.p99loginproxy.net/ws/accounts"
        );
    }

    #[test]
    fn build_ws_url_http() {
        assert_eq!(
            build_ws_url("http://localhost:5998"),
            "ws://localhost:5998/ws/accounts"
        );
    }

    #[test]
    fn formats_delta_summary_like_python() {
        let changes = serde_json::json!([
            {"action": "add", "account": "alice"},
            {
                "action": "update",
                "account": "bob",
                "fields": {"characters": {}, "tags": {}}
            },
            {"action": "remove", "account": "carol"}
        ]);
        assert_eq!(
            format_delta_summary(&changes),
            "add alice; update bob (characters, tags); remove carol"
        );
    }

    fn test_client_config() -> SsoClientConfig {
        SsoClientConfig {
            api_url: "http://localhost:5998".into(),
            backend_name: "Localhost".into(),
            client_version: "2.0.0".into(),
            verify_tls: false,
            ca_bundle: SsoCaBundleMode::System,
            timeout_secs: 5,
            client_settings: json!({}),
        }
    }

    #[tokio::test]
    async fn login_auth_blocked_before_full_state() {
        let client = SsoClient::new(test_client_config(), SecretString::from("token"));
        assert!(!client.is_connected());
        let result = client.request_login_auth("mytag").await;
        assert_eq!(result.error.as_deref(), Some("WebSocket not connected"));
    }
}
