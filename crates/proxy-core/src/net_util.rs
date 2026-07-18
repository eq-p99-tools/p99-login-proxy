//! Host/port parsing helpers.

/// Split `host`, `host:port`, or `[ipv6]:port` into hostname/IP and port.
pub fn split_host_port(host: &str, default_port: u16) -> (String, u16) {
    let host = host.trim();
    if host.is_empty() {
        return (String::new(), default_port);
    }

    if let Some(stripped) = host.strip_prefix('[') {
        if let Some((inner, port_str)) = stripped.split_once("]:") {
            if let Ok(port) = port_str.parse::<u16>() {
                return (inner.to_string(), port);
            }
        }
    }

    if host.parse::<std::net::IpAddr>().is_ok() {
        return (host.to_string(), default_port);
    }

    if let Some((name, port_str)) = host.rsplit_once(':') {
        if !name.is_empty() {
            if let Ok(port) = port_str.parse::<u16>() {
                return (name.to_string(), port);
            }
        }
    }

    (host.to_string(), default_port)
}

#[cfg(test)]
mod tests {
    use super::split_host_port;

    #[test]
    fn splits_embedded_port() {
        assert_eq!(
            split_host_port("login.eqemulator.net:5998", 6000),
            ("login.eqemulator.net".into(), 5998)
        );
    }
}
