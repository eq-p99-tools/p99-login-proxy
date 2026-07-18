//! Loopback integration test: client -> proxy -> fake upstream -> proxy -> client.

use std::time::Duration;

use protocol::soe::{
    build_keepalive, build_session_request, build_session_response, transport_opcode, TransportOp,
};
use runtime::{ProxyLocalData, ProxyRuntimeConfig};
use tokio::net::UdpSocket;
use tokio::time::timeout;

#[tokio::test]
async fn proxy_forwards_client_to_upstream_and_back() {
    let upstream_sock = UdpSocket::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = upstream_sock.local_addr().unwrap();
    let upstream_task = tokio::spawn(async move {
        let mut buf = [0u8; 512];
        let (len, peer) = upstream_sock.recv_from(&mut buf).await.unwrap();
        upstream_sock.send_to(&buf[..len], peer).await.unwrap();
    });

    let mut config = ProxyRuntimeConfig::loopback_test(upstream_addr.port(), 0);
    config.listen_port = 0;

    let cancel = tokio_util::sync::CancellationToken::new();
    let (event_tx, _event_rx) = tokio::sync::mpsc::channel(8);
    let handle = runtime::udp::UdpProxyHandle::start(
        config,
        ProxyLocalData::default(),
        cancel.child_token(),
        event_tx,
        None,
    )
    .await
    .expect("start proxy");

    let proxy_addr = handle.listen_addr;
    let client_sock = UdpSocket::bind("127.0.0.1:0").await.unwrap();
    let ka = build_keepalive().to_vec();
    client_sock.send_to(&ka, proxy_addr).await.unwrap();

    let mut buf = [0u8; 512];
    let recv = timeout(Duration::from_secs(2), client_sock.recv_from(&mut buf))
        .await
        .expect("timed out waiting for echo")
        .expect("recv failed");

    assert_eq!(recv.0, ka.len());
    assert_eq!(&buf[..recv.0], &ka);

    handle.stop().await;
    upstream_task.await.unwrap();
}

#[tokio::test]
async fn proxy_relays_session_handshake() {
    let upstream_sock = UdpSocket::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = upstream_sock.local_addr().unwrap();
    let upstream_task = tokio::spawn(async move {
        let mut buf = [0u8; 512];
        let (len, peer) = upstream_sock.recv_from(&mut buf).await.unwrap();
        assert_eq!(
            transport_opcode(&buf[..len]),
            TransportOp::SessionRequest as u16,
            "proxy should forward SessionRequest upstream"
        );
        let resp = build_session_response();
        upstream_sock.send_to(&resp, peer).await.unwrap();
    });

    let mut config = ProxyRuntimeConfig::loopback_test(upstream_addr.port(), 0);
    config.listen_port = 0;

    let cancel = tokio_util::sync::CancellationToken::new();
    let (event_tx, _event_rx) = tokio::sync::mpsc::channel(8);
    let handle = runtime::udp::UdpProxyHandle::start(
        config,
        ProxyLocalData::default(),
        cancel.child_token(),
        event_tx,
        None,
    )
    .await
    .expect("start proxy");

    let proxy_addr = handle.listen_addr;
    let client_sock = UdpSocket::bind("127.0.0.1:0").await.unwrap();
    let req = build_session_request().to_vec();
    client_sock.send_to(&req, proxy_addr).await.unwrap();

    let mut buf = [0u8; 512];
    let recv = timeout(Duration::from_secs(2), client_sock.recv_from(&mut buf))
        .await
        .expect("timed out waiting for SessionResponse")
        .expect("recv failed");

    assert_eq!(
        transport_opcode(&buf[..recv.0]),
        TransportOp::SessionResponse as u16
    );

    handle.stop().await;
    upstream_task.await.unwrap();
}
