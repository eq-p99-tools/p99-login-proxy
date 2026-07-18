//! Fixture parity tests against Python oracle outputs.

use protocol::crypto::DesKeyIv;
use protocol::{
    build_login_combined, is_bad_password_login_result, CombinedPacket, ProxySessionState,
};

const KEY_IV: DesKeyIv = DesKeyIv {
    key: [0; 8],
    iv: [0; 8],
};

fn read_fixture(name: &str) -> Vec<u8> {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name);
    let hex: String = std::fs::read_to_string(path).expect("fixture");
    hex::decode(hex.trim()).expect("hex decode")
}

#[test]
fn oracle_combined_ack_login_matches_rust_builder() {
    let oracle = read_fixture("combined_ack_login.hex");
    let built = build_login_combined("user", "pass", KEY_IV);
    assert_eq!(oracle, built, "login combined must match Python oracle");
}

#[test]
fn oracle_cs_offset_matches_session_adjust() {
    let combined = read_fixture("combined_ack_login.hex");
    let expected = read_fixture("combined_ack_login_cs_offset.hex");
    let mut state = ProxySessionState::default();
    state.note_injected_client_packet();
    let mut buf = combined;
    state.adjust_combined(&mut buf);
    assert_eq!(expected, buf);
}

#[test]
fn oracle_bad_password_classifier() {
    let payload = read_fixture("bad_password_login_accepted.hex");
    assert!(is_bad_password_login_result(&payload, KEY_IV));
}

#[test]
fn combined_extended_length_subpacket() {
    let big = vec![0u8; 300];
    let subs = [&big[..], &[0x00, 0x15, 0x00, 0x01][..]];
    let combined = protocol::build_combined(&subs);
    let parsed = CombinedPacket::parse(&combined, 0, None).unwrap();
    assert_eq!(parsed.subs.len(), 2);
    assert_eq!(parsed.subs[0].length, 300);
}
