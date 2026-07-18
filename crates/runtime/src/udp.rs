use std::net::SocketAddr;
use std::sync::Arc;

use tokio::net::UdpSocket;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

use crate::config::{effective_bind_host, ProxyLocalData, ProxyRuntimeConfig};
use crate::events::{AppEvent, ProxyStatus};
use crate::proxy::LoginProxyEngine;
use crate::upstream::{is_upstream_peer, resolve_upstream};
use crate::websocket::SsoClient;

pub struct UdpProxyHandle {
    pub listen_addr: SocketAddr,
    cancel: CancellationToken,
    task: tokio::task::JoinHandle<()>,
}

impl UdpProxyHandle {
    pub async fn start(
        config: ProxyRuntimeConfig,
        local: ProxyLocalData,
        cancel: CancellationToken,
        event_tx: tokio::sync::mpsc::Sender<AppEvent>,
        sso: Option<SsoClient>,
    ) -> Result<Self, String> {
        let upstream = resolve_upstream(&config.upstream_host, config.upstream_port).await?;

        let bind_host = effective_bind_host(&config.listen_host, upstream);
        if bind_host != config.listen_host {
            warn!(
                configured = %config.listen_host,
                effective = %bind_host,
                %upstream,
                "loopback bind cannot reach external upstream; using effective bind address"
            );
        }
        let bind_addr = format!("{bind_host}:{}", config.listen_port);
        let socket = UdpSocket::bind(&bind_addr)
            .await
            .map_err(|e| format!("bind {bind_addr}: {e}"))?;

        let local_addr = socket.local_addr().map_err(|e| e.to_string())?;
        info!(
            listen = %local_addr,
            upstream = %upstream,
            proxy_only = config.proxy_only,
            "UDP login proxy started"
        );

        let stats = Arc::new(Mutex::new(ProxyStatus {
            listen_address: local_addr.to_string(),
            lifecycle: proxy_core::model::ProxyLifecycle::Running,
            ..Default::default()
        }));
        let stats_task = stats.clone();
        let child = cancel.child_token();

        let task = tokio::spawn(async move {
            let mut engine = LoginProxyEngine::with_sso(config, local, sso.clone());
            let mut buf = vec![0u8; 65535];
            loop {
                tokio::select! {
                    _ = child.cancelled() => break,
                    recv = socket.recv_from(&mut buf) => {
                        match recv {
                            Ok((len, peer)) => {
                                let packet = &buf[..len];
                                let mut actions = engine.on_datagram(packet, peer, upstream);

                                if let Some(pending) = actions.sso_pending.take() {
                                    if let Some(ref client) = sso {
                                        let auth = client.request_login_auth(&pending.username).await;
                                        if let Some(ref reason) = auth.error {
                                            let _ = event_tx
                                                .send(AppEvent::AuthRejected {
                                                    username: pending.username.clone(),
                                                    reason: reason.clone(),
                                                })
                                                .await;
                                        }
                                        engine.complete_sso_auth(
                                            pending,
                                            auth.real_user,
                                            auth.encrypted_credentials,
                                            auth.error,
                                            &mut actions,
                                        );
                                    } else {
                                        engine.complete_sso_auth(
                                            pending,
                                            None,
                                            None,
                                            Some("SSO client not configured".into()),
                                            &mut actions,
                                        );
                                    }
                                }

                                if let Some(client) = engine.client_addr() {
                                    for out in actions.send_client {
                                        if let Err(e) = socket.send_to(&out, client).await {
                                            error!(%e, "send to client failed");
                                        }
                                    }
                                } else if !actions.send_client.is_empty() {
                                    warn!(
                                        count = actions.send_client.len(),
                                        "dropping server packet(s): no EQ client bound"
                                    );
                                }
                                for out in actions.send_upstream {
                                    if let Err(e) = socket.send_to(&out, upstream).await {
                                        error!(%e, "send to upstream failed");
                                    }
                                }
                                if actions.client_disconnected {
                                    let _ = event_tx.send(AppEvent::ProxyStatus {
                                        status: ProxyStatus {
                                            client_connected: false,
                                            ..Default::default()
                                        },
                                    }).await;
                                }
                                if !is_upstream_peer(peer, upstream) && engine.client_addr() == Some(peer) {
                                    let mut s = stats_task.lock().await;
                                    s.packets_forwarded += 1;
                                    s.client_connected = true;
                                    let _ = event_tx.send(AppEvent::UserConnected {
                                        endpoint: peer.to_string(),
                                    }).await;
                                }
                                if actions.connection_started {
                                    let _ = event_tx.send(AppEvent::ConnectionStarted).await;
                                }
                                if actions.connection_completed {
                                    let _ = event_tx.send(AppEvent::ConnectionCompleted).await;
                                }
                                if let Some((alias, account, method)) = actions.login_proxied.take() {
                                    let _ = event_tx
                                        .send(AppEvent::LoginProxied {
                                            alias,
                                            account,
                                            method,
                                        })
                                        .await;
                                } else if let Some(method) = actions.login_method {
                                    let user = actions.sso_username.unwrap_or_default();
                                    let _ = event_tx
                                        .send(AppEvent::Activity {
                                            message: format!("login method={method} user={user}"),
                                        })
                                        .await;
                                }
                            }
                            Err(e) => error!("udp recv error: {e}"),
                        }
                    }
                }
            }
            info!("UDP proxy stopped");
        });

        Ok(Self {
            listen_addr: local_addr,
            cancel,
            task,
        })
    }

    pub async fn stop(self) {
        self.cancel.cancel();
        let _ = self.task.await;
    }
}
