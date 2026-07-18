//! Bidirectional EQ login UDP proxy engine.

use std::net::SocketAddr;
use std::time::{Duration, Instant};

use protocol::soe::transport_opcode;
use protocol::{
    try_intercept_bad_password_combined, try_intercept_bad_password_packet, LoginPacket,
    ProxySessionState, RetryOutcome, SsoRetryNotice, SsoRetryState, TransportOp,
};
use proxy_core::decision::{CredentialDecision, CredentialRouter};
use secrecy::ExposeSecret;
use tracing::{debug, error, info, warn};

use crate::config::{ProxyLocalData, ProxyRuntimeConfig};
use crate::upstream::is_upstream_peer;
use crate::websocket::SsoClient;

pub struct LoginProxyEngine {
    config: ProxyRuntimeConfig,
    local: ProxyLocalData,
    session: ProxySessionState,
    retry: SsoRetryState,
    client: Option<SocketAddr>,
    in_session: bool,
    last_recv: Instant,
    auth_in_flight: bool,
    sso: Option<SsoClient>,
}

impl LoginProxyEngine {
    pub fn new(config: ProxyRuntimeConfig, local: ProxyLocalData) -> Self {
        Self::with_sso(config, local, None)
    }

    pub fn with_sso(
        config: ProxyRuntimeConfig,
        local: ProxyLocalData,
        sso: Option<SsoClient>,
    ) -> Self {
        Self {
            config,
            local,
            session: ProxySessionState::default(),
            retry: SsoRetryState::default(),
            client: None,
            in_session: false,
            last_recv: Instant::now(),
            auth_in_flight: false,
            sso,
        }
    }

    pub fn client_addr(&self) -> Option<SocketAddr> {
        self.client
    }

    fn session_free(&mut self) {
        self.session.reset();
        self.retry.clear();
    }

    fn maybe_reset_session(&mut self, now: Instant) -> bool {
        let idle =
            now.duration_since(self.last_recv) > Duration::from_secs(self.config.idle_timeout_secs);
        if self.in_session && !idle {
            return false;
        }
        let new_connection = !self.in_session;
        self.session_free();
        new_connection
    }

    /// Handle a datagram received on the proxy socket.
    pub fn on_datagram(
        &mut self,
        data: &[u8],
        from: SocketAddr,
        upstream: SocketAddr,
    ) -> ProxyActions {
        let now = Instant::now();
        if is_upstream_peer(from, upstream) {
            return self.handle_server_packet(data, 0, data.len());
        }

        // Python always updates client_addr on every non-upstream datagram.
        if self.client != Some(from) {
            if let Some(old) = self.client.replace(from) {
                info!(old = %old, new = %from, "EQ client address updated");
            } else {
                info!(%from, "EQ client connected");
            }
        }
        let connection_started = self.maybe_reset_session(now);
        let mut actions = self.handle_client_packet(data, from, now);
        actions.connection_started |= connection_started;
        actions
    }

    fn handle_client_packet(
        &mut self,
        data: &[u8],
        from: SocketAddr,
        now: Instant,
    ) -> ProxyActions {
        self.client = Some(from);
        let mut actions = ProxyActions::default();
        let mut outbound = data.to_vec();
        let opcode = transport_opcode(&outbound);
        debug!(%from, len = data.len(), opcode = %opcode_name(opcode), "client packet");

        if opcode == TransportOp::Combined as u16 {
            self.session.adjust_combined(&mut outbound);
            if let Some(login) = LoginPacket::parse(&outbound, self.config.des_key_iv) {
                outbound = self.rewrite_client_login(outbound, &login, &mut actions);
            }
        } else if opcode == TransportOp::SessionDisconnect as u16 {
            self.in_session = false;
            self.session_free();
            actions.client_disconnected = true;
            actions.connection_completed = true;
        } else if opcode == TransportOp::Ack as u16 {
            self.session.adjust_ack(&mut outbound, 0);
        } else if opcode == TransportOp::Packet as u16 {
            self.session.adjust_client_packet(&mut outbound, 0);
        }

        self.last_recv = now;
        if actions.sso_pending.is_none() && !outbound.is_empty() {
            actions.send_upstream.push(outbound);
        }
        actions
    }

    /// Apply SSO auth result and queue the (possibly rewritten) login packet for upstream.
    pub fn complete_sso_auth(
        &mut self,
        pending: SsoAuthPending,
        real_user: Option<String>,
        encrypted: Option<Vec<u8>>,
        error: Option<String>,
        actions: &mut ProxyActions,
    ) {
        self.auth_in_flight = false;
        let username = pending.username.clone();
        let mut outbound = pending.packet;

        if let Some(detail) = error {
            warn!(username = %username, %detail, "SSO login rejected");
            actions.login_method = Some("sso_rejected".into());
            actions.send_upstream.push(outbound);
            return;
        }

        if let (Some(real_user), Some(enc)) = (real_user, encrypted) {
            info!(username = %username, rewrite_as = %real_user, "SSO auth rewrite");
            match pending.login.splice_encrypted_credentials(&enc) {
                Ok(buf) => {
                    self.retry.arm(pending.original_packet);
                    outbound = buf;
                    actions.login_method = Some("sso".into());
                    actions.login_proxied =
                        Some((username.clone(), real_user.clone(), "sso".into()));
                }
                Err(e) => {
                    warn!(username = %username, "SSO credential splice failed: {e}");
                    actions.login_method = Some("sso_splice_failed".into());
                }
            }
        }

        actions.sso_username = Some(username);
        actions.send_upstream.push(outbound);
    }

    fn rewrite_client_login(
        &mut self,
        packet: Vec<u8>,
        login: &LoginPacket,
        actions: &mut ProxyActions,
    ) -> Vec<u8> {
        let cache = self
            .sso
            .as_ref()
            .map(|s| s.cache())
            .and_then(|c| c.try_read().ok().map(|g| g.clone()))
            .unwrap_or_default();
        let has_token = self
            .sso
            .as_ref()
            .is_some_and(|s| s.has_credentials() && s.is_connected());
        let router = CredentialRouter {
            proxy_only: self.config.proxy_only,
            skip_sso_accounts: &self.config.skip_sso_accounts,
            has_token,
            accounts: &self.local.accounts,
            characters: &self.local.characters,
            cached_names: &cache,
        };
        let decision = router.decide(&login.username, &login.password, None);
        info!(
            username = %login.username,
            proxy_only = self.config.proxy_only,
            "login combined packet"
        );
        match decision {
            CredentialDecision::Passthrough if self.config.proxy_only => {
                info!(username = %login.username, "credentials passthrough (proxy only)");
                actions.login_method = Some("proxy_only".into());
                let alias = login.username.clone();
                actions.login_proxied = Some((alias.clone(), alias, "proxy_only".into()));
                packet
            }
            CredentialDecision::SkipSsoPassthrough => {
                info!(username = %login.username, "credentials passthrough (skip SSO list)");
                actions.login_method = Some("skip_sso".into());
                let alias = login.username.clone();
                actions.login_proxied = Some((alias.clone(), alias, "skip_sso".into()));
                packet
            }
            CredentialDecision::Passthrough => {
                info!(username = %login.username, "credentials passthrough");
                actions.login_method = Some("passthrough".into());
                let alias = login.username.clone();
                actions.login_proxied = Some((alias.clone(), alias, "passthrough".into()));
                packet
            }
            CredentialDecision::LocalRewrite { username, password } => {
                info!(username = %login.username, rewrite_as = %username, "local account rewrite");
                let alias = login.username.clone();
                let method = if self.local.characters.contains_name(&alias)
                    && alias.to_lowercase() != username.to_lowercase()
                {
                    "local_char"
                } else {
                    "local"
                };
                actions.login_method = Some(method.into());
                actions.login_proxied = Some((alias, username.clone(), method.into()));
                match login.rewrite_credentials(
                    &username,
                    password.expose_secret(),
                    self.config.des_key_iv,
                ) {
                    Ok(buf) => buf,
                    Err(e) => {
                        warn!("credential rewrite failed: {e}");
                        packet
                    }
                }
            }
            CredentialDecision::SsoAuth { username } => {
                if self.auth_in_flight {
                    info!(username = %username, "SSO auth already in flight; dropping login packet");
                    actions.login_method = Some("sso_busy".into());
                    return Vec::new();
                }
                self.auth_in_flight = true;
                actions.login_method = Some("sso_pending".into());
                actions.sso_username = Some(username.clone());
                let original_packet = packet.clone();
                actions.sso_pending = Some(SsoAuthPending {
                    username,
                    packet,
                    original_packet,
                    login: login.clone(),
                });
                Vec::new()
            }
        }
    }

    fn handle_server_packet(&mut self, data: &[u8], start: usize, len: usize) -> ProxyActions {
        let mut actions = ProxyActions::default();
        let slice = &data[start..start + len];
        let opcode = transport_opcode(slice);

        if opcode != TransportOp::Fragment as u16 {
            debug!(len, opcode = %opcode_name(opcode), "server packet");
        }

        match opcode {
            x if x == TransportOp::SessionResponse as u16 => {
                info!("session established with login server");
                self.in_session = true;
                self.session_free();
                actions.send_client.push(data.to_vec());
            }
            x if x == TransportOp::Combined as u16 => {
                if let Some(outcome) = try_intercept_bad_password_combined(
                    data,
                    start,
                    len,
                    &mut self.retry,
                    &mut self.session,
                    self.config.des_key_iv,
                ) {
                    if apply_sso_retry_outcome(outcome, &mut actions) {
                        return actions;
                    }
                }
                let mut buf = data.to_vec();
                let forward = self.session.recv_combined(&mut buf, start, Some(len));
                actions.send_client.push(forward);
            }
            x if x == TransportOp::Packet as u16 => {
                if let Some(outcome) = try_intercept_bad_password_packet(
                    data,
                    start,
                    len,
                    &mut self.retry,
                    &mut self.session,
                    self.config.des_key_iv,
                ) {
                    if apply_sso_retry_outcome(outcome, &mut actions) {
                        return actions;
                    }
                }
                let mut buf = data.to_vec();
                self.session.recv_packet(&mut buf, start, None);
                actions.send_client.push(slice_forward(buf, start, len));
            }
            x if x == TransportOp::Fragment as u16 => {
                if let Some(filtered) = self.session.recv_fragment(data, start, Some(len)) {
                    actions.send_client.push(filtered);
                }
            }
            x if x == TransportOp::Ack as u16 => {
                let mut buf = data.to_vec();
                self.session.adjust_server_ack(&mut buf, start);
                actions.send_client.push(slice_forward(buf, start, len));
            }
            _ => {
                actions
                    .send_client
                    .push(slice_forward(data.to_vec(), start, len));
            }
        }
        actions
    }
}

/// Forward `buf` to the client, slicing to the sub-range `[start, start + len)`
/// only when it is not already the whole buffer (avoids a copy for standalone
/// datagrams that were extracted from a Combined container).
fn slice_forward(buf: Vec<u8>, start: usize, len: usize) -> Vec<u8> {
    if start == 0 && len == buf.len() {
        buf
    } else {
        buf[start..start + len].to_vec()
    }
}

fn opcode_name(op: u16) -> &'static str {
    TransportOp::from_u16(op)
        .map(|t| t.name())
        .unwrap_or("unknown")
}

/// Apply SSO bad-password intercept. Returns ``true`` when the caller should stop processing.
fn apply_sso_retry_outcome(outcome: RetryOutcome, actions: &mut ProxyActions) -> bool {
    let RetryOutcome {
        forward_subs,
        server_messages,
        notice,
        ..
    } = outcome;

    if let Some(SsoRetryNotice::MissingOriginalLogin { server_seq }) = notice {
        error!(
            server_seq,
            "SSO bad-password detected but no original Login captured; cannot retry, forwarding instead"
        );
        return false;
    }

    if let Some(SsoRetryNotice::Retried { server_seq }) = notice {
        warn!(
            server_seq,
            "SSO password rejected by server; retrying with original client credentials"
        );
    }

    actions.send_client.extend(forward_subs);
    actions.send_upstream.extend(server_messages);
    actions.sso_retry_fired = true;
    true
}

/// Pending async SSO credential resolution.
#[derive(Debug, Clone)]
pub struct SsoAuthPending {
    pub username: String,
    pub packet: Vec<u8>,
    pub original_packet: Vec<u8>,
    pub login: LoginPacket,
}

/// Side effects produced by processing one datagram.
#[derive(Debug, Default)]
pub struct ProxyActions {
    pub send_client: Vec<Vec<u8>>,
    pub send_upstream: Vec<Vec<u8>>,
    pub client_disconnected: bool,
    pub login_method: Option<String>,
    pub login_proxied: Option<(String, String, String)>,
    pub sso_username: Option<String>,
    pub sso_retry_fired: bool,
    pub sso_pending: Option<SsoAuthPending>,
    pub connection_started: bool,
    pub connection_completed: bool,
}

#[cfg(test)]
mod tests {
    use super::*;
    use protocol::soe::{
        build_disconnect, build_keepalive, build_session_request, build_session_response,
    };

    #[test]
    fn client_keepalive_forwards_upstream() {
        let upstream: SocketAddr = "127.0.0.1:6001".parse().unwrap();
        let client: SocketAddr = "127.0.0.1:50000".parse().unwrap();
        let mut engine =
            LoginProxyEngine::new(ProxyRuntimeConfig::default(), ProxyLocalData::default());
        let ka = build_keepalive().to_vec();
        let actions = engine.on_datagram(&ka, client, upstream);
        assert_eq!(actions.send_upstream.len(), 1);
        assert_eq!(actions.send_upstream[0], ka);
        assert!(actions.send_client.is_empty());
    }

    #[test]
    fn session_request_forwards_and_response_returns_to_client() {
        let upstream: SocketAddr = "127.0.0.1:5998".parse().unwrap();
        let client: SocketAddr = "127.0.0.1:50000".parse().unwrap();
        let mut engine =
            LoginProxyEngine::new(ProxyRuntimeConfig::default(), ProxyLocalData::default());

        let req = build_session_request().to_vec();
        let client_actions = engine.on_datagram(&req, client, upstream);
        assert_eq!(client_actions.send_upstream, vec![req]);
        assert!(client_actions.send_client.is_empty());

        let resp = build_session_response();
        let server_actions = engine.on_datagram(&resp, upstream, upstream);
        assert_eq!(server_actions.send_client, vec![resp]);
        assert!(server_actions.send_upstream.is_empty());
    }

    #[test]
    fn first_client_packet_counts_connection_started() {
        let upstream: SocketAddr = "127.0.0.1:5998".parse().unwrap();
        let client: SocketAddr = "127.0.0.1:50000".parse().unwrap();
        let mut engine =
            LoginProxyEngine::new(ProxyRuntimeConfig::default(), ProxyLocalData::default());
        let ka = build_keepalive().to_vec();
        let actions = engine.on_datagram(&ka, client, upstream);
        assert!(actions.connection_started);
        assert_eq!(actions.send_upstream.len(), 1);
    }

    #[test]
    fn session_disconnect_counts_connection_completed() {
        let upstream: SocketAddr = "127.0.0.1:5998".parse().unwrap();
        let client: SocketAddr = "127.0.0.1:50000".parse().unwrap();
        let mut engine =
            LoginProxyEngine::new(ProxyRuntimeConfig::default(), ProxyLocalData::default());
        engine.on_datagram(build_keepalive().as_ref(), client, upstream);
        let actions = engine.on_datagram(build_disconnect().as_ref(), client, upstream);
        assert!(actions.connection_completed);
        assert_eq!(actions.send_upstream.len(), 1);
    }

    #[test]
    fn short_seq_bearing_datagrams_do_not_panic() {
        let upstream: SocketAddr = "127.0.0.1:5998".parse().unwrap();
        let client: SocketAddr = "127.0.0.1:50000".parse().unwrap();
        let mut engine =
            LoginProxyEngine::new(ProxyRuntimeConfig::default(), ProxyLocalData::default());

        // 2-byte Ack, Packet, and Fragment opcodes are too short to carry a
        // sequence field; they must not panic the seq rewrite helpers.
        for opcode in [TransportOp::Ack, TransportOp::Packet, TransportOp::Fragment] {
            let short = (opcode as u16).to_be_bytes().to_vec();
            let client_actions = engine.on_datagram(&short, client, upstream);
            assert!(client_actions.send_client.is_empty());
            let server_actions = engine.on_datagram(&short, upstream, upstream);
            assert!(server_actions.send_upstream.is_empty());
        }
    }

    #[test]
    fn non_upstream_datagram_updates_client_address() {
        let upstream: SocketAddr = "127.0.0.1:5998".parse().unwrap();
        let client_a: SocketAddr = "127.0.0.1:50000".parse().unwrap();
        let client_b: SocketAddr = "127.0.0.1:50001".parse().unwrap();
        let mut engine =
            LoginProxyEngine::new(ProxyRuntimeConfig::default(), ProxyLocalData::default());
        let ka = build_keepalive().to_vec();

        engine.on_datagram(&ka, client_a, upstream);
        let actions = engine.on_datagram(&ka, client_b, upstream);
        assert_eq!(engine.client_addr(), Some(client_b));
        assert_eq!(actions.send_upstream.len(), 1);
    }
}
