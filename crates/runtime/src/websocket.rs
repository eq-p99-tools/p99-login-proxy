use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use base64::Engine;
use futures_util::{SinkExt, StreamExt};
use proxy_core::AccountCache;
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
        let msg = WsOutbound::UpdateLocation {
            character_name,
            park_location,
            bind_location,
            level,
            items: items.as_ref(),
        };
        let _ = self.send_json(&msg).await;
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

        let connect = tokio::select! {
            biased;
            _ = cancel.cancelled() => return,
            result = tokio::time::timeout(CONNECT_TIMEOUT, async {
                if url.starts_with("wss://") && !config.verify_tls {
                    let cfg = rustls::ClientConfig::builder()
                        .dangerous()
                        .with_custom_certificate_verifier(Arc::new(NoVerifier))
                        .with_no_client_auth();
                    let connector = tokio_tungstenite::Connector::Rustls(Arc::new(cfg));
                    tokio_tungstenite::connect_async_tls_with_config(&url, None, false, Some(connector))
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
                    client.set_write(None).await;
                    client.inner.connected.store(false, Ordering::Relaxed);
                    notify_state(&on_state, WsStateEvent::Disconnected);
                    sleep_backoff(&cancel, delay).await;
                    delay = (delay * 2).min(RECONNECT_MAX);
                    continue;
                }

                client.inner.connected.store(true, Ordering::Relaxed);
                debug!(
                    client_version = %config.client_version,
                    client_settings = %config.client_settings,
                    "WS auth message sent, awaiting server response"
                );

                loop {
                    tokio::select! {
                        _ = cancel.cancelled() => {
                            client.set_write(None).await;
                            client.inner.connected.store(false, Ordering::Relaxed);
                            cancel_pending(&client).await;
                            notify_state(&on_state, WsStateEvent::Disconnected);
                            return;
                        }
                        msg = read.next() => {
                            match msg {
                                Some(Ok(Message::Text(text))) => {
                                    if handle_inbound(&client, &write, &text, &on_state).await {
                                        client.set_write(None).await;
                                        client.inner.connected.store(false, Ordering::Relaxed);
                                        cancel_pending(&client).await;
                                        notify_state(&on_state, WsStateEvent::Disconnected);
                                        break;
                                    }
                                }
                                Some(Ok(Message::Ping(payload))) => {
                                    let _ = write.lock().await.send(Message::Pong(payload)).await;
                                }
                                Some(Ok(Message::Close(_))) | None => {
                                    client.set_write(None).await;
                                    client.inner.connected.store(false, Ordering::Relaxed);
                                    cancel_pending(&client).await;
                                    notify_state(&on_state, WsStateEvent::Disconnected);
                                    break;
                                }
                                Some(Err(e)) => {
                                    warn!("WS read error: {e}");
                                    client.set_write(None).await;
                                    client.inner.connected.store(false, Ordering::Relaxed);
                                    cancel_pending(&client).await;
                                    notify_state(&on_state, WsStateEvent::Disconnected);
                                    break;
                                }
                                _ => {}
                            }
                        }
                    }
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

/// Returns true when the connection should reconnect.
async fn handle_inbound(
    client: &SsoClient,
    write: &Arc<Mutex<WsSender>>,
    text: &str,
    on_state: &Option<tokio::sync::mpsc::Sender<WsStateEvent>>,
) -> bool {
    let inbound: WsInbound = match serde_json::from_str(text) {
        Ok(v) => v,
        Err(e) => {
            debug!(raw = %text, "WS undecodable message: {e}");
            return false;
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
            return true;
        }
        WsInbound::Unknown => debug!(raw = %text, "WS unhandled message"),
    }
    false
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

#[derive(Debug)]
struct NoVerifier;

impl rustls::client::danger::ServerCertVerifier for NoVerifier {
    fn verify_server_cert(
        &self,
        _end_entity: &rustls::pki_types::CertificateDer<'_>,
        _intermediates: &[rustls::pki_types::CertificateDer<'_>],
        _server_name: &rustls::pki_types::ServerName<'_>,
        _ocsp_response: &[u8],
        _now: rustls::pki_types::UnixTime,
    ) -> Result<rustls::client::danger::ServerCertVerified, rustls::Error> {
        Ok(rustls::client::danger::ServerCertVerified::assertion())
    }

    fn verify_tls12_signature(
        &self,
        _message: &[u8],
        _cert: &rustls::pki_types::CertificateDer<'_>,
        _dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
    }

    fn verify_tls13_signature(
        &self,
        _message: &[u8],
        _cert: &rustls::pki_types::CertificateDer<'_>,
        _dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
    }

    fn supported_verify_schemes(&self) -> Vec<rustls::SignatureScheme> {
        vec![
            rustls::SignatureScheme::RSA_PKCS1_SHA256,
            rustls::SignatureScheme::ECDSA_NISTP256_SHA256,
            rustls::SignatureScheme::ED25519,
        ]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
