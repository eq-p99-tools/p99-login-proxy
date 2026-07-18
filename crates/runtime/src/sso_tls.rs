//! SSO WebSocket TLS connector construction.

use std::fs;
use std::io::BufReader;
use std::path::Path;
use std::sync::Arc;

use proxy_core::SsoCaBundleMode;
use rustls::RootCertStore;
use tokio_tungstenite::Connector;

pub fn build_tls_connector(
    verify_tls: bool,
    ca_bundle: &SsoCaBundleMode,
) -> Result<Connector, String> {
    if !verify_tls {
        let cfg = rustls::ClientConfig::builder()
            .dangerous()
            .with_custom_certificate_verifier(Arc::new(NoVerifier))
            .with_no_client_auth();
        return Ok(Connector::Rustls(Arc::new(cfg)));
    }

    let roots = build_root_store(ca_bundle)?;
    let cfg = rustls::ClientConfig::builder()
        .with_root_certificates(roots)
        .with_no_client_auth();
    Ok(Connector::Rustls(Arc::new(cfg)))
}

fn build_root_store(ca_bundle: &SsoCaBundleMode) -> Result<RootCertStore, String> {
    match ca_bundle {
        SsoCaBundleMode::WebpkiRoots => {
            let mut store = RootCertStore::empty();
            store.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
            Ok(store)
        }
        SsoCaBundleMode::System => load_system_roots(),
        SsoCaBundleMode::Custom(path) => load_custom_roots(path),
    }
}

fn load_system_roots() -> Result<RootCertStore, String> {
    let mut store = RootCertStore::empty();
    let loaded = rustls_native_certs::load_native_certs();
    for cert in loaded.certs {
        store
            .add(cert)
            .map_err(|error| format!("failed to add system root certificate: {error}"))?;
    }
    if store.is_empty() {
        if let Some(error) = loaded.errors.first() {
            return Err(format!("failed to load system trust store: {error}"));
        }
        store.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    }
    Ok(store)
}

fn load_custom_roots(path: &Path) -> Result<RootCertStore, String> {
    let pem = fs::read(path)
        .map_err(|error| format!("SSO CA bundle not readable ({}): {error}", path.display()))?;
    let mut reader = BufReader::new(pem.as_slice());
    let certs = rustls_pemfile::certs(&mut reader)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| format!("invalid SSO CA bundle ({}): {error}", path.display()))?;
    if certs.is_empty() {
        return Err(format!(
            "SSO CA bundle contains no certificates: {}",
            path.display()
        ));
    }
    let mut store = RootCertStore::empty();
    for cert in certs {
        store
            .add(cert)
            .map_err(|error| format!("failed to add custom root certificate: {error}"))?;
    }
    Ok(store)
}

#[derive(Debug)]
struct NoVerifier;

impl rustls::client::danger::ServerCertVerifier for NoVerifier {
    fn verify_server_cert(
        &self,
        _end_entity: &rustls::pki_types::CertificateDer<'_>,
        _intermediates: &[rustls::pki_types::CertificateDer<'_>],
        _server_name: &rustls::pki_types::ServerName<'_>,
        _ocsp_response: &[u8],
        _now: rustls::pki_types::UnixTime,
    ) -> Result<rustls::client::danger::ServerCertVerified, rustls::Error> {
        Ok(rustls::client::danger::ServerCertVerified::assertion())
    }

    fn verify_tls12_signature(
        &self,
        _message: &[u8],
        _cert: &rustls::pki_types::CertificateDer<'_>,
        _dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
    }

    fn verify_tls13_signature(
        &self,
        _message: &[u8],
        _cert: &rustls::pki_types::CertificateDer<'_>,
        _dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
    }

    fn supported_verify_schemes(&self) -> Vec<rustls::SignatureScheme> {
        vec![
            rustls::SignatureScheme::RSA_PKCS1_SHA256,
            rustls::SignatureScheme::ECDSA_NISTP256_SHA256,
            rustls::SignatureScheme::ED25519,
        ]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_disabled_verifier_connector() {
        build_tls_connector(false, &SsoCaBundleMode::WebpkiRoots).unwrap();
    }
}
