use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr};
use std::sync::Arc;

use tokio::net::UdpSocket;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

use crate::config::{ProxyLocalData, ProxyRuntimeConfig};
use crate::events::{AppEvent, ProxyStatus};
use crate::proxy::LoginProxyEngine;
use crate::upstream::{is_upstream_peer, resolve_upstream};
use crate::websocket::SsoClient;

pub struct UdpProxyHandle {
    pub listen_addr: SocketAddr,
    cancel: CancellationToken,
    update_tx: tokio::sync::mpsc::UnboundedSender<ProxyRuntimeUpdate>,
    task: tokio::task::JoinHandle<()>,
}

enum ProxyRuntimeUpdate {
    LocalData(ProxyLocalData),
    SsoClient(Option<SsoClient>),
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

        // EQ talks to `socket` on the configured (normally loopback) address. The login
        // server talks to `upstream_socket`, an ephemeral socket connected to it: a socket
        // bound to loopback cannot reach an external host on Windows (WSAENETUNREACH), and
        // connecting makes the OS drop datagrams from anyone but the login server.
        let bind_addr = format!("{}:{}", config.listen_host, config.listen_port);
        let socket = UdpSocket::bind(&bind_addr)
            .await
            .map_err(|e| format!("bind {bind_addr}: {e}"))?;
        let upstream_socket = UdpSocket::bind(upstream_bind_addr(upstream))
            .await
            .map_err(|e| format!("bind upstream socket: {e}"))?;
        upstream_socket
            .connect(upstream)
            .await
            .map_err(|e| format!("connect upstream {upstream}: {e}"))?;

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
        let (update_tx, mut update_rx) = tokio::sync::mpsc::unbounded_channel();

        let task = tokio::spawn(async move {
            let mut active_sso = sso;
            let mut engine = LoginProxyEngine::with_sso(config, local, active_sso.clone());
            let mut client_buf = vec![0u8; 65535];
            let mut upstream_buf = vec![0u8; 65535];
            loop {
                let recv = tokio::select! {
                    _ = child.cancelled() => break,
                    Some(update) = update_rx.recv() => {
                        match update {
                            ProxyRuntimeUpdate::LocalData(local) => engine.set_local_data(local),
                            ProxyRuntimeUpdate::SsoClient(sso) => {
                                engine.set_sso_client(sso.clone());
                                active_sso = sso;
                            }
                        }
                        continue;
                    }
                    recv = socket.recv_from(&mut client_buf) => {
                        recv.map(|(len, peer)| (&client_buf[..len], peer))
                    }
                    recv = upstream_socket.recv(&mut upstream_buf) => {
                        recv.map(|len| (&upstream_buf[..len], upstream))
                    }
                };
                let (packet, peer) = match recv {
                    Ok(received) => received,
                    Err(e) => {
                        error!("udp recv error: {e}");
                        continue;
                    }
                };
                let mut actions = engine.on_datagram(packet, peer, upstream);

                if let Some(pending) = actions.sso_pending.take() {
                    if let Some(ref client) = active_sso {
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

                engine.finalize_actions(&mut actions);

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
                    if let Err(e) = upstream_socket.send(&out).await {
                        error!(%e, "send to upstream failed");
                    }
                }
                if actions.client_disconnected {
                    let _ = event_tx
                        .send(AppEvent::ProxyStatus {
                            status: ProxyStatus {
                                client_connected: false,
                                ..Default::default()
                            },
                        })
                        .await;
                }
                if !is_upstream_peer(peer, upstream) && engine.client_addr() == Some(peer) {
                    let mut s = stats_task.lock().await;
                    s.packets_forwarded += 1;
                    s.client_connected = true;
                    let _ = event_tx
                        .send(AppEvent::UserConnected {
                            endpoint: peer.to_string(),
                        })
                        .await;
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
            info!("UDP proxy stopped");
        });

        Ok(Self {
            listen_addr: local_addr,
            cancel,
            update_tx,
            task,
        })
    }

    pub fn update_local_data(&self, local: ProxyLocalData) {
        let _ = self.update_tx.send(ProxyRuntimeUpdate::LocalData(local));
    }

    pub fn update_sso_client(&self, sso: Option<SsoClient>) {
        let _ = self.update_tx.send(ProxyRuntimeUpdate::SsoClient(sso));
    }

    pub async fn stop(self) {
        self.cancel.cancel();
        let _ = self.task.await;
    }
}

/// Ephemeral wildcard address in the upstream's family, so the OS picks the route.
fn upstream_bind_addr(upstream: SocketAddr) -> SocketAddr {
    let ip = match upstream {
        SocketAddr::V4(_) => IpAddr::V4(Ipv4Addr::UNSPECIFIED),
        SocketAddr::V6(_) => IpAddr::V6(Ipv6Addr::UNSPECIFIED),
    };
    SocketAddr::new(ip, 0)
}
