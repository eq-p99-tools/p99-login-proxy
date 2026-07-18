use crate::combined::CombinedPacket;
use crate::crypto::DesKeyIv;
use crate::login::{app_opcode, is_bad_password_login_result, AppOp};
use crate::session::ProxySessionState;
use crate::soe::{build_ack, get_sequence, TransportOp};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LoginAcceptedClass {
    Good,
    Bad,
}

pub fn classify_login_accepted(
    data: &[u8],
    start: usize,
    length: usize,
    key_iv: DesKeyIv,
) -> Option<LoginAcceptedClass> {
    if length < 6 {
        return None;
    }
    let app_payload = &data[start + 4..start + length];
    if app_payload.len() < 2 || app_opcode(app_payload) != AppOp::LoginAccepted as u16 {
        return None;
    }
    if is_bad_password_login_result(app_payload, key_iv) {
        Some(LoginAcceptedClass::Bad)
    } else {
        Some(LoginAcceptedClass::Good)
    }
}

#[derive(Debug, Default)]
pub struct SsoRetryState {
    pub original_login: Option<Vec<u8>>,
    pub armed: bool,
    pub fired: bool,
}

impl SsoRetryState {
    pub fn arm(&mut self, original: Vec<u8>) {
        self.original_login = Some(original);
        self.armed = true;
        self.fired = false;
    }

    pub fn disarm(&mut self) {
        self.armed = false;
    }

    pub fn clear(&mut self) {
        self.original_login = None;
        self.armed = false;
        self.fired = false;
    }
}

pub struct RetryOutcome {
    pub suppress_original: bool,
    pub forward_subs: Vec<Vec<u8>>,
    pub server_messages: Vec<Vec<u8>>,
}

pub fn try_intercept_bad_password_combined(
    data: &[u8],
    start: usize,
    length: usize,
    retry: &mut SsoRetryState,
    session: &mut ProxySessionState,
    key_iv: DesKeyIv,
) -> Option<RetryOutcome> {
    if !retry.armed || retry.fired {
        return None;
    }
    let combined = CombinedPacket::parse(data, start, Some(length)).ok()?;
    let mut bad_sub = None;
    for sub in &combined.subs {
        if sub.transport_op != TransportOp::Packet as u16 {
            continue;
        }
        match classify_login_accepted(data, sub.offset, sub.length, key_iv) {
            Some(LoginAcceptedClass::Good) => {
                retry.disarm();
                return None;
            }
            Some(LoginAcceptedClass::Bad) => {
                bad_sub = Some(sub.clone());
                break;
            }
            None => {}
        }
    }
    let bad = bad_sub?;
    retry.disarm();
    let mut forward_subs = Vec::new();
    for sub in &combined.subs {
        if sub.offset == bad.offset {
            continue;
        }
        let mut sub_buf = data[sub.offset..sub.offset + sub.length].to_vec();
        if sub.transport_op == TransportOp::Ack as u16 {
            session.adjust_server_ack(&mut sub_buf, 0);
        } else if sub.transport_op == TransportOp::Packet as u16 {
            session.recv_packet(&mut sub_buf, 0, None);
        }
        forward_subs.push(sub_buf);
    }
    let bad_seq = get_sequence(data, bad.offset);
    let server_messages = fire_sso_retry(bad_seq, retry, session)?;
    Some(RetryOutcome {
        suppress_original: true,
        forward_subs,
        server_messages,
    })
}

pub fn try_intercept_bad_password_packet(
    data: &[u8],
    start: usize,
    length: usize,
    retry: &mut SsoRetryState,
    session: &mut ProxySessionState,
    key_iv: DesKeyIv,
) -> Option<RetryOutcome> {
    if !retry.armed || retry.fired {
        return None;
    }
    match classify_login_accepted(data, start, length, key_iv) {
        None => None,
        Some(LoginAcceptedClass::Good) => {
            retry.disarm();
            None
        }
        Some(LoginAcceptedClass::Bad) => {
            retry.disarm();
            let server_seq = get_sequence(data, start);
            let server_messages = fire_sso_retry(server_seq, retry, session)?;
            Some(RetryOutcome {
                suppress_original: true,
                forward_subs: Vec::new(),
                server_messages,
            })
        }
    }
}

pub fn fire_sso_retry(
    server_seq_to_ack: u16,
    retry: &mut SsoRetryState,
    session: &mut ProxySessionState,
) -> Option<Vec<Vec<u8>>> {
    let original = retry.original_login.clone()?;
    let mut messages = Vec::new();
    messages.push(build_ack(server_seq_to_ack).to_vec());
    session.note_suppressed_server_packet(server_seq_to_ack);
    session.note_injected_client_packet();
    let mut replay = original;
    session.adjust_combined(&mut replay);
    retry.fired = true;
    messages.push(replay);
    Some(messages)
}
