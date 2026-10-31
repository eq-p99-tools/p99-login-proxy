//! Sequence numbers are 16-bit and wrap at 65,536, with a half window, as the
//! Titanium client compares them (from the program: titanium-login-l1-part1,
//! T-d). These tests cross 65,535 in both directions.

use protocol::soe::get_sequence;
use protocol::{build_ack, wrap_app_packet, ProxySessionState};

#[test]
fn server_packets_and_client_acks_cross_the_wrap() {
    let mut state = ProxySessionState::default();
    state.seq_to_client = 65_535;
    state.seq_from_server = 65_535;

    let mut last = wrap_app_packet(65_535, &[0x16, 0x00]);
    state.recv_packet(&mut last, 0, None);
    assert_eq!(get_sequence(&last, 0), 65_535);
    assert_eq!(state.seq_from_server, 0);

    let mut first = wrap_app_packet(0, &[0x16, 0x00]);
    state.recv_packet(&mut first, 0, None);
    assert_eq!(get_sequence(&first, 0), 0);
    assert_eq!(state.seq_to_client, 1);
    assert_eq!(state.seq_from_server, 1);

    let mut ack = build_ack(0);
    state.adjust_ack(&mut ack, 0);
    assert_eq!(get_sequence(&ack, 0), 0);
}

#[test]
fn client_packets_and_server_acks_cross_the_wrap() {
    let mut state = ProxySessionState::default();
    state.note_injected_client_packet();

    let mut packet = wrap_app_packet(65_535, &[0x04, 0x00]);
    state.adjust_client_packet(&mut packet, 0);
    assert_eq!(get_sequence(&packet, 0), 0);

    let mut ack = build_ack(0);
    state.adjust_server_ack(&mut ack, 0);
    assert_eq!(get_sequence(&ack, 0), 65_535);
}

#[test]
fn a_suppressed_packet_from_before_the_wrap_does_not_move_the_ack_back() {
    let mut state = ProxySessionState::default();
    state.seq_from_server = 3;
    state.note_suppressed_server_packet(65_535);
    assert_eq!(state.seq_from_server, 3);

    state.note_suppressed_server_packet(3);
    assert_eq!(state.seq_from_server, 4);

    let mut wrapping = ProxySessionState::default();
    wrapping.seq_from_server = 65_535;
    wrapping.note_suppressed_server_packet(65_535);
    assert_eq!(wrapping.seq_from_server, 0);
}

#[test]
fn an_ack_before_any_server_packet_names_the_one_before_zero() {
    let state = ProxySessionState::default();
    let mut ack = build_ack(0);
    state.adjust_ack(&mut ack, 0);
    assert_eq!(get_sequence(&ack, 0), 65_535);
}
