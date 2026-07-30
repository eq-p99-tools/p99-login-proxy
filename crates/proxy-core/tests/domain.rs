use std::collections::HashSet;

use proxy_core::accounts::LocalAccountStore;
use proxy_core::accounts_cache::AccountCache;
use proxy_core::config::{ConfigFileV1, ValidatedConfig};
use proxy_core::decision::{CredentialDecision, CredentialRouter};
use proxy_core::eqhost::EqHostWriter;
use secrecy::SecretString;
use tempfile::TempDir;

#[test]
fn validated_config_defaults_loopback() {
    let file = ConfigFileV1::default();
    let cfg = ValidatedConfig::from_file(&file).unwrap();
    assert_eq!(cfg.listen_host, "127.0.0.1");
    assert_eq!(cfg.listen_port, 6998);
}

#[test]
fn non_loopback_requires_opt_in() {
    let file = ConfigFileV1 {
        listen_host: "0.0.0.0".into(),
        ..Default::default()
    };
    assert!(ValidatedConfig::from_file(&file).is_err());
}

#[test]
fn upstream_host_with_embedded_port_splits() {
    let file = ConfigFileV1 {
        upstream_host: "login.eqemulator.net:5998".into(),
        upstream_port: 6000,
        ..Default::default()
    };
    let cfg = ValidatedConfig::from_file(&file).unwrap();
    assert_eq!(cfg.upstream_host, "login.eqemulator.net");
    assert_eq!(cfg.upstream_port, 5998);
}

#[test]
fn credential_router_local_alias() {
    let accounts = LocalAccountStore::from_rows([(
        "main".into(),
        "realuser".into(),
        SecretString::from("secret".to_string()),
    )]);
    let router = CredentialRouter {
        proxy_only: false,
        skip_sso_accounts: &HashSet::new(),
        has_token: false,
        accounts: &accounts,
        characters: &Default::default(),
        cached_names: &AccountCache::default(),
    };
    match router.decide("main", "", None) {
        CredentialDecision::LocalRewrite { username, .. } => assert_eq!(username, "realuser"),
        other => panic!("expected local rewrite, got {other:?}"),
    }
}

#[test]
fn credential_router_local_character_unknown_account() {
    use proxy_core::characters::LocalCharacterStore;
    use proxy_core::model::LocalCharacter;

    let mut characters = LocalCharacterStore::default();
    characters
        .upsert(LocalCharacter {
            name: "hero".into(),
            account_alias: "missing".into(),
            server: String::new(),
            class: None,
            level: None,
            bind: None,
            park: None,
            items: Default::default(),
        })
        .unwrap();
    let router = CredentialRouter {
        proxy_only: false,
        skip_sso_accounts: &HashSet::new(),
        has_token: false,
        accounts: &LocalAccountStore::default(),
        characters: &characters,
        cached_names: &AccountCache::default(),
    };
    assert!(matches!(
        router.decide("hero", "pass", None),
        CredentialDecision::Passthrough
    ));
}

#[test]
fn eqhost_roundtrip() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("eqgame.exe"), b"").unwrap();
    EqHostWriter::enable_proxy(dir.path(), "127.0.0.1", 5998, "login.eqemulator.net", 5998)
        .unwrap();
    let text = EqHostWriter::read_eqhost(dir.path()).unwrap();
    assert!(text.contains("[LoginServer]"));
    assert!(EqHostWriter::has_active_proxy_line(
        &text,
        "127.0.0.1",
        5998
    ));
    EqHostWriter::disable_proxy(dir.path(), "login.eqemulator.net", 5998).unwrap();
}

#[test]
fn eqhost_manual_write() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("eqgame.exe"), b"").unwrap();
    let custom = "[LoginServer]\nHost=127.0.0.1:5999\n";
    EqHostWriter::write_eqhost(dir.path(), custom).unwrap();
    let text = EqHostWriter::read_eqhost(dir.path()).unwrap();
    assert_eq!(text, custom);
}

#[test]
fn eqhost_directory_proxy_detection() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("eqgame.exe"), b"").unwrap();
    assert!(!EqHostWriter::is_proxy_enabled_in_directory(
        dir.path(),
        "127.0.0.1",
        5998
    ));
    EqHostWriter::enable_proxy(dir.path(), "127.0.0.1", 5998, "login.eqemulator.net", 5998)
        .unwrap();
    assert!(EqHostWriter::is_proxy_enabled_in_directory(
        dir.path(),
        "127.0.0.1",
        5998
    ));
}

#[test]
fn eqhost_proxy_detection_maps_bind_all_to_loopback() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("eqgame.exe"), b"").unwrap();
    EqHostWriter::enable_proxy(dir.path(), "127.0.0.1", 6790, "login.eqemulator.net", 5998)
        .unwrap();
    assert!(EqHostWriter::is_proxy_enabled_in_directory(
        dir.path(),
        "0.0.0.0",
        6790
    ));
}

#[test]
fn eqhost_reset_backup_writes_default_login_server() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("eqgame.exe"), b"").unwrap();
    EqHostWriter::reset_eqhost_backup(dir.path(), "login.eqemulator.net", 5998).unwrap();
    let backup = std::fs::read_to_string(dir.path().join("eqhost.txt.bak")).unwrap();
    assert_eq!(backup, "[LoginServer]\nHost=login.eqemulator.net:5998\n");
}

#[test]
fn eqhost_reset_backup_overwrites_existing() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("eqgame.exe"), b"").unwrap();
    std::fs::write(
        dir.path().join("eqhost.txt.bak"),
        "[LoginServer]\nHost=custom.example.com:6000\n",
    )
    .unwrap();
    EqHostWriter::reset_eqhost_backup(dir.path(), "login.eqemulator.net", 5998).unwrap();
    let backup = std::fs::read_to_string(dir.path().join("eqhost.txt.bak")).unwrap();
    assert_eq!(backup, "[LoginServer]\nHost=login.eqemulator.net:5998\n");
}

#[test]
fn eqhost_proxy_detection_accepts_localhost_line() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("eqgame.exe"), b"").unwrap();
    EqHostWriter::write_eqhost(dir.path(), "[LoginServer]\nHost=localhost:6790\n").unwrap();
    assert!(EqHostWriter::is_proxy_enabled_in_directory(
        dir.path(),
        "0.0.0.0",
        6790
    ));
}
