use std::path::PathBuf;

use proxy_core::{
    discover_and_persist_eq_directory, list_sso_backend_options, load_local_accounts,
    load_local_characters, parse_proxyconfig_ini, resolve_sso_api_url, resolve_sso_ca_bundle,
    write_proxyconfig_ini, ConfigFileV1, SsoCaBundleMode,
};
use tempfile::TempDir;

fn fixture_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("tests")
        .join("fixtures")
        .join("v1_portable")
}

#[test]
fn loads_v1_portable_fixture_ini() {
    let ini_path = fixture_dir().join("proxyconfig.ini");
    let cfg = parse_proxyconfig_ini(&ini_path).expect("fixture INI should parse");

    assert_eq!(cfg.listen_port, 6790);
    assert_eq!(cfg.listen_host, "0.0.0.0");
    assert!(cfg.allow_non_loopback);
    assert_eq!(cfg.sso_backend, "Localhost");
    assert_eq!(cfg.sso_api_url.as_deref(), Some("http://localhost:5998"));
    assert_eq!(cfg.login_timeout_secs, 12);
    assert!(cfg.prerelease_updates);
    assert_eq!(cfg.encryption_key, [1, 2, 3, 4, 5, 6, 7, 8]);
    assert_eq!(cfg.encryption_iv, [8, 7, 6, 5, 4, 3, 2, 1]);
    assert_eq!(cfg.skip_sso_accounts, "foo, bar");
    assert_eq!(cfg.theme_mode, "dark");
    assert_eq!(cfg.sso_ca_bundle, "True");
    assert!(cfg
        .eq_directory
        .as_ref()
        .is_none_or(|value| value.trim().is_empty()));
    assert_eq!(
        cfg.api_tokens.get("Good Guys").map(String::as_str),
        Some("token_legacy_gg")
    );
    assert_eq!(
        cfg.sso_backends.get("Custom Backend").map(String::as_str),
        Some("https://custom.example.com")
    );
}

#[test]
fn fixture_csvs_load_in_python_format() {
    let dir = fixture_dir();
    let accounts = load_local_accounts(&dir.join("local_accounts.csv")).unwrap();
    assert!(accounts.resolve("main").is_some());
    assert!(accounts.resolve("alias1").is_some());

    let characters = load_local_characters(&dir.join("local_characters.csv")).unwrap();
    let names: Vec<_> = characters
        .list()
        .into_iter()
        .map(|character| character.name)
        .collect();
    assert_eq!(names, vec!["Alice".to_string(), "Bob".to_string()]);
}

#[test]
fn fixture_round_trip_preserves_unknown_ini_content() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("proxyconfig.ini");
    std::fs::copy(fixture_dir().join("proxyconfig.ini"), &path).unwrap();

    let mut cfg = parse_proxyconfig_ini(&path).unwrap();
    cfg.listen_port = 6800;
    write_proxyconfig_ini(&path, &cfg).unwrap();

    let written = std::fs::read_to_string(&path).unwrap();
    assert!(written.contains("custom_legacy_setting = keep_me"));
    assert!(written.contains("[sso_backends]"));
    assert!(written.contains("listen_port = 6800"));

    let round_trip = parse_proxyconfig_ini(&path).unwrap();
    assert_eq!(round_trip.listen_port, 6800);
    assert_eq!(
        round_trip
            .sso_backends
            .get("Custom Backend")
            .map(String::as_str),
        Some("https://custom.example.com")
    );
}

#[test]
fn custom_backend_resolves_api_url_and_dropdown() {
    let ini_path = fixture_dir().join("proxyconfig.ini");
    let mut cfg = parse_proxyconfig_ini(&ini_path).unwrap();
    cfg.sso_backend = "Custom Backend".to_string();
    cfg.sso_api_url = None;

    assert_eq!(
        resolve_sso_api_url(&cfg),
        "https://custom.example.com".to_string()
    );
    let options = list_sso_backend_options(&cfg);
    assert!(options
        .iter()
        .any(|(name, url)| name == "Custom Backend" && url == "https://custom.example.com"));
}

#[test]
fn discovers_eq_directory_when_blank_and_persists() {
    let dir = TempDir::new().unwrap();
    let eq_dir = dir.path().join("EverQuest");
    std::fs::create_dir(&eq_dir).unwrap();
    std::fs::write(eq_dir.join("eqgame.exe"), b"stub").unwrap();

    let config_path = dir.path().join("proxyconfig.ini");
    std::fs::write(&config_path, "[DEFAULT]\neq_directory = \n").unwrap();

    let mut file = ConfigFileV1::default();
    std::env::set_current_dir(&eq_dir).unwrap();
    let discovered = discover_and_persist_eq_directory(&mut file, &config_path).unwrap();
    assert_eq!(discovered, eq_dir);
    assert_eq!(file.eq_directory.as_deref(), Some(eq_dir.to_str().unwrap()));

    let persisted = std::fs::read_to_string(&config_path).unwrap();
    assert!(persisted.contains("eq_directory"));
}

#[test]
fn resolves_ca_bundle_modes() {
    assert_eq!(
        resolve_sso_ca_bundle("True").unwrap(),
        SsoCaBundleMode::WebpkiRoots
    );
    assert_eq!(
        resolve_sso_ca_bundle("system").unwrap(),
        SsoCaBundleMode::System
    );
    assert!(resolve_sso_ca_bundle("/missing/custom.pem").is_err());
}
