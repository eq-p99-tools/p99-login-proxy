//! Parse and resolve upstream login server endpoints.

use std::net::{IpAddr, SocketAddr};

use proxy_core::split_host_port;

/// Normalize mapped IPv6 addresses so peer comparisons match Python's IPv4 `EQEMU_ADDR`.
pub fn normalize_addr(addr: SocketAddr) -> SocketAddr {
    match addr {
        SocketAddr::V6(v6) => v6
            .ip()
            .to_ipv4_mapped()
            .map(|v4| SocketAddr::new(IpAddr::V4(v4), v6.port()))
            .unwrap_or(addr),
        other => other,
    }
}

/// True when *peer* is the resolved upstream login server (IP + port).
pub fn is_upstream_peer(peer: SocketAddr, upstream: SocketAddr) -> bool {
    normalize_addr(peer) == normalize_addr(upstream)
}

pub async fn resolve_upstream(host: &str, port: u16) -> Result<SocketAddr, String> {
    let (host_only, port) = split_host_port(host, port);
    if host_only.is_empty() {
        return Err("upstream host is empty".into());
    }

    let target = format!("{host_only}:{port}");

    if let Ok(ip) = host_only.parse::<IpAddr>() {
        return Ok(SocketAddr::new(ip, port));
    }

    match tokio::net::lookup_host(&target).await {
        Ok(addrs) => {
            // Match Python `socket.gethostbyname`: prefer the first IPv4 answer.
            let mut fallback = None;
            for addr in addrs {
                match addr {
                    SocketAddr::V4(_) => return Ok(addr),
                    other if fallback.is_none() => fallback = Some(other),
                    _ => {}
                }
            }
            if let Some(addr) = fallback {
                return Ok(addr);
            }
        }
        Err(e) => {
            tracing::warn!(%target, error = %e, "upstream DNS lookup failed");
        }
    }

    Err(format!("could not resolve upstream {target}"))
}

#[cfg(test)]
mod tests {
    use std::net::{Ipv4Addr, Ipv6Addr, SocketAddr};

    use super::split_host_port;
    use super::{is_upstream_peer, normalize_addr};

    #[test]
    fn splits_host_and_port() {
        assert_eq!(
            split_host_port("login.eqemulator.net:5998", 6000),
            ("login.eqemulator.net".into(), 5998)
        );
    }

    #[test]
    fn uses_default_port_when_missing() {
        assert_eq!(
            split_host_port("login.eqemulator.net", 5998),
            ("login.eqemulator.net".into(), 5998)
        );
    }

    #[test]
    fn upstream_peer_matches_ipv4_mapped_ipv6() {
        let upstream = SocketAddr::from((Ipv4Addr::new(70, 35, 159, 39), 5998));
        let mapped = SocketAddr::from((Ipv6Addr::new(0, 0, 0, 0, 0, 0xffff, 0x4623, 0x9f27), 5998));
        assert!(is_upstream_peer(mapped, upstream));
        assert_eq!(normalize_addr(mapped), upstream);
    }
}
