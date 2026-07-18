//! Integration tests ported from Python `test_sso_retry.py`.

use protocol::crypto::{des_encrypt, DesKeyIv};
use protocol::retry::try_intercept_bad_password_combined;
use protocol::soe::get_sequence;
use protocol::{
    build_combined_ack_then_packet, build_login_accepted_combined, build_login_combined,
    is_bad_password_login_result, AppOp, CombinedPacket, LoginPacket, ProxySessionState,
    SsoRetryState, TransportOp, LOGIN_RESULT_FAILURE_STATUS,
};

const KEY_IV: DesKeyIv = DesKeyIv {
    key: [0; 8],
    iv: [0; 8],
};

#[test]
fn classifier_synthesized_failure() {
    let mut plaintext = Vec::new();
    plaintext.extend_from_slice(&12345u32.to_le_bytes());
    plaintext.extend_from_slice(&0u32.to_le_bytes());
    plaintext.extend_from_slice(&LOGIN_RESULT_FAILURE_STATUS.to_le_bytes());
    plaintext.extend_from_slice(&[0u8; 20]);
    let encrypted = des_encrypt(&plaintext, KEY_IV);
    let mut base = Vec::new();
    base.extend_from_slice(&3i32.to_le_bytes());
    base.push(0);
    base.push(2);
    base.extend_from_slice(&0u32.to_le_bytes());
    let mut payload = Vec::new();
    payload.extend_from_slice(&(AppOp::LoginAccepted as u16).to_le_bytes());
    payload.extend_from_slice(&base);
    payload.extend_from_slice(&encrypted);
    assert!(is_bad_password_login_result(&payload, KEY_IV));
}

#[test]
fn cs_offset_shifts_packet_subs() {
    let mut state = ProxySessionState::default();
    state.note_injected_client_packet();
    let mut buf = build_combined_ack_then_packet(0, 2, &[0x04, 0x00]);
    state.adjust_combined(&mut buf);
    let cp = CombinedPacket::parse(&buf, 0, None).unwrap();
    let packet_sub = cp
        .subs
        .iter()
        .find(|s| s.transport_op == TransportOp::Packet as u16)
        .unwrap();
    assert_eq!(get_sequence(&buf, packet_sub.offset), 3);
}

#[test]
fn note_suppressed_advances_seq_from_server_only() {
    let mut state = ProxySessionState::default();
    state.seq_to_client = 1;
    state.seq_from_server = 1;
    state.note_suppressed_server_packet(1);
    assert_eq!(state.seq_from_server, 2);
    assert_eq!(state.seq_to_client, 1);
}

#[test]
fn armed_bad_password_triggers_retry() {
    let mut session = ProxySessionState::default();
    session.seq_to_client = 1;
    session.seq_from_server = 1;
    let mut retry = SsoRetryState::default();
    retry.arm(build_login_combined("user", "userpass", KEY_IV));

    let bad = build_login_accepted_combined(27392, LOGIN_RESULT_FAILURE_STATUS, 1, KEY_IV);
    let outcome =
        try_intercept_bad_password_combined(&bad, 0, bad.len(), &mut retry, &mut session, KEY_IV)
            .expect("should intercept");

    assert!(outcome.suppress_original);
    assert_eq!(outcome.forward_subs.len(), 1);
    assert_eq!(outcome.server_messages.len(), 2);
    assert_eq!(
        outcome.notice,
        Some(protocol::SsoRetryNotice::Retried { server_seq: 1 })
    );
    assert!(!retry.armed);
    assert!(retry.fired);
    assert_eq!(session.cs_offset, 1);
}

#[test]
fn bad_password_without_original_login() {
    let mut session = ProxySessionState::default();
    let mut retry = SsoRetryState {
        armed: true,
        fired: false,
        original_login: None,
    };

    let bad = build_login_accepted_combined(27392, LOGIN_RESULT_FAILURE_STATUS, 1, KEY_IV);
    let outcome =
        try_intercept_bad_password_combined(&bad, 0, bad.len(), &mut retry, &mut session, KEY_IV)
            .expect("should report missing original login");

    assert!(!outcome.suppress_original);
    assert!(outcome.server_messages.is_empty());
    assert_eq!(
        outcome.notice,
        Some(protocol::SsoRetryNotice::MissingOriginalLogin { server_seq: 1 })
    );
}

#[test]
fn login_packet_roundtrip() {
    let combined = build_login_combined("user", "userpass", KEY_IV);
    let parsed = LoginPacket::parse(&combined, KEY_IV).expect("parse login");
    assert_eq!(parsed.username, "user");
    assert_eq!(parsed.password, "userpass");
}
