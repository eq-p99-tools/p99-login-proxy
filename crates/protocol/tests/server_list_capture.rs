//! Server-list reassembly parity against Python oracle on capture fragments.

use protocol::login::AppOp;
use protocol::server_list::{parse_server_list, P99_SERVER_PREFIXES};
use protocol::soe::transport_opcode;
use protocol::{ProxySessionState, TransportOp};

fn read_fragments() -> Vec<Vec<u8>> {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/server_list_fragments.hexlist");
    std::fs::read_to_string(path)
        .expect("fixture")
        .lines()
        .filter(|l| !l.is_empty())
        .map(|line| hex::decode(line).expect("hex"))
        .collect()
}

#[test]
fn capture_fragments_filter_to_p99_servers() {
    let frags = read_fragments();
    assert!(frags.len() > 10, "expected many fragments from capture");

    let mut state = ProxySessionState::default();
    let mut filtered_packet = None;
    for raw in &frags {
        if let Some(out) = state.recv_fragment(raw, 0, None) {
            filtered_packet = Some(out);
            break;
        }
    }

    let packet = filtered_packet.expect("server list should complete");
    assert_eq!(transport_opcode(&packet), TransportOp::Packet as u16);
    assert!(
        packet.len() > 100,
        "filtered server list packet too small: {}",
        packet.len()
    );

    let app = &packet[4..];
    let (servers, _) = parse_server_list(app).expect("reassembled server list should parse");
    let p99: Vec<_> = servers
        .iter()
        .filter(|s| {
            let lower = s.name.to_lowercase();
            P99_SERVER_PREFIXES.iter().any(|p| lower.starts_with(p))
        })
        .collect();

    assert_eq!(
        p99.len(),
        4,
        "expected four P99 servers: {:?}",
        p99.iter().map(|s| &s.name).collect::<Vec<_>>()
    );
    assert!(
        p99.iter().any(|s| s.name.contains("Project 1999: Blue")),
        "missing Blue server"
    );
    assert!(
        p99.iter().any(|s| s.name.starts_with("An Interesting")),
        "missing Interesting Hole server"
    );
    assert_eq!(
        u16::from_le_bytes([app[0], app[1]]),
        AppOp::ServerListResponse as u16
    );
}
