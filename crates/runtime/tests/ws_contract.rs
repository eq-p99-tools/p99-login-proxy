//! Contract tests pinning the typed WS enums to the shared fixtures.
//!
//! The fixtures under `schemas/fixtures/` are vendored from the canonical
//! copies in `roboToald/schemas/` (the server owns the contract). These tests
//! assert that every inbound fixture deserializes into the expected
//! `WsInbound` variant and every `WsOutbound` value serializes to the matching
//! outbound fixture, so a server-side shape change trips CI here.

use std::path::{Path, PathBuf};

use runtime::websocket::{WsInbound, WsOutbound};
use serde_json::{json, Value};

fn fixtures_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("schemas")
        .join("fixtures")
}

fn schemas_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("schemas")
}

fn load(rel: &str) -> (String, Value) {
    let path = fixtures_dir().join(rel);
    let text =
        std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    let value =
        serde_json::from_str(&text).unwrap_or_else(|e| panic!("parse {}: {e}", path.display()));
    (text, value)
}

fn read_value(path: &Path) -> Value {
    let text =
        std::fs::read_to_string(path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("parse {}: {e}", path.display()))
}

fn fixture_paths() -> Vec<PathBuf> {
    let base = fixtures_dir();
    let mut paths = Vec::new();
    for sub in ["inbound", "outbound"] {
        let dir = base.join(sub);
        let entries =
            std::fs::read_dir(&dir).unwrap_or_else(|e| panic!("read_dir {}: {e}", dir.display()));
        for entry in entries {
            let path = entry.expect("dir entry").path();
            if path.extension().and_then(|s| s.to_str()) == Some("json") {
                paths.push(path);
            }
        }
    }
    paths.sort();
    paths
}

fn vendored_schema() -> Value {
    read_value(&schemas_dir().join("ws-protocol.schema.json"))
}

fn parse_inbound(rel: &str) -> WsInbound {
    let (text, _) = load(rel);
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("deserialize {rel}: {e}"))
}

#[test]
fn full_state_fixture_deserializes() {
    match parse_inbound("inbound/full_state.json") {
        WsInbound::FullState {
            account_tree,
            dynamic_tag_zones,
            dynamic_tag_classes,
        } => {
            assert!(account_tree.get("myaccount").is_some());
            assert_eq!(dynamic_tag_zones, vec!["seb", "vp", "st"]);
            assert_eq!(dynamic_tag_classes, vec!["clr", "enc", "wiz"]);
        }
        other => panic!("expected FullState, got {other:?}"),
    }
}

#[test]
fn delta_fixture_deserializes() {
    match parse_inbound("inbound/delta.json") {
        WsInbound::Delta { changes } => {
            assert_eq!(changes.as_array().map(Vec::len), Some(3));
        }
        other => panic!("expected Delta, got {other:?}"),
    }
}

#[test]
fn login_auth_response_ok_fixture_deserializes() {
    match parse_inbound("inbound/login_auth_response_ok.json") {
        WsInbound::LoginAuthResponse {
            request_id,
            real_user,
            encrypted_credentials,
            error,
        } => {
            assert!(!request_id.is_empty());
            assert_eq!(real_user.as_deref(), Some("realbot01"));
            assert!(encrypted_credentials.is_some());
            assert!(error.is_none());
        }
        other => panic!("expected LoginAuthResponse, got {other:?}"),
    }
}

#[test]
fn login_auth_response_err_fixture_deserializes() {
    // The server's failure payload includes an extra `status` field, which must
    // be ignored (tolerance), and the error must be captured.
    match parse_inbound("inbound/login_auth_response_err.json") {
        WsInbound::LoginAuthResponse {
            real_user, error, ..
        } => {
            assert!(real_user.is_none());
            assert_eq!(error.as_deref(), Some("No access to that account"));
        }
        other => panic!("expected LoginAuthResponse, got {other:?}"),
    }
}

#[test]
fn error_ping_pong_fixtures_deserialize() {
    assert!(matches!(
        parse_inbound("inbound/error.json"),
        WsInbound::Error { detail } if detail.as_deref() == Some("Access revoked")
    ));
    assert!(matches!(
        parse_inbound("inbound/ping.json"),
        WsInbound::Ping
    ));
    assert!(matches!(
        parse_inbound("inbound/pong.json"),
        WsInbound::Pong
    ));
}

#[test]
fn tolerates_unknown_type_and_extra_fields() {
    // Unknown message type degrades to Unknown instead of failing the connection.
    let unknown: WsInbound =
        serde_json::from_str(r#"{"type":"some_future_message","payload":{"x":1}}"#).unwrap();
    assert!(matches!(unknown, WsInbound::Unknown));

    // Extra unknown fields on a known type are ignored.
    let extra: WsInbound =
        serde_json::from_str(r#"{"type":"ping","server_time":123,"nonce":"abc"}"#).unwrap();
    assert!(matches!(extra, WsInbound::Ping));
}

#[test]
fn tolerates_error_aliases() {
    for raw in [
        r#"{"type":"error","message":"boom"}"#,
        r#"{"type":"auth_failed","reason":"revoked"}"#,
        r#"{"type":"close","detail":"bye"}"#,
    ] {
        assert!(
            matches!(serde_json::from_str::<WsInbound>(raw).unwrap(), WsInbound::Error { detail } if detail.is_some()),
            "expected Error with detail from {raw}"
        );
    }
}

fn assert_outbound_matches(msg: &WsOutbound, rel: &str) {
    let (_, expected) = load(rel);
    let actual = serde_json::to_value(msg).unwrap();
    assert_eq!(actual, expected, "outbound {rel} mismatch");
}

#[test]
fn outbound_values_match_fixtures() {
    let settings = json!({ "auto_add_local_characters": true });
    assert_outbound_matches(
        &WsOutbound::Auth {
            access_key: "AccessKeyExample1234",
            client_version: "2.0.0",
            client_settings: &settings,
        },
        "outbound/auth.json",
    );

    assert_outbound_matches(
        &WsOutbound::LoginAuth {
            request_id: "6f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f",
            username: "mytag",
        },
        "outbound/login_auth.json",
    );

    assert_outbound_matches(
        &WsOutbound::Heartbeat {
            character_name: "Zzzz",
        },
        "outbound/heartbeat.json",
    );

    let items = json!({ "seb": true, "vp": false });
    assert_outbound_matches(
        &WsOutbound::UpdateLocation {
            character_name: "Zzzz",
            park_location: Some("Plane of Knowledge"),
            bind_location: Some("Toxxulia Forest"),
            level: Some(60),
            items: items.as_object(),
        },
        "outbound/update_location.json",
    );

    assert_outbound_matches(
        &WsOutbound::Fte {
            mob: "Lord Nagafen",
            player: "Zzzz",
            character_name: "Zzzz",
            eq_log_time: "Wed Jul 15 22:14:05 2026",
        },
        "outbound/fte.json",
    );

    assert_outbound_matches(
        &WsOutbound::MobDeath {
            mob: "Lord Nagafen",
            eq_log_time: "Wed Jul 15 22:19:41 2026",
            character_name: "Zzzz",
        },
        "outbound/mob_death.json",
    );

    assert_outbound_matches(&WsOutbound::Pong, "outbound/pong.json");
}

#[test]
fn update_location_omits_absent_optionals() {
    // Optional fields use skip_serializing_if so a minimal update carries only
    // the character name (matches the Python client's conditional payload).
    let msg = WsOutbound::UpdateLocation {
        character_name: "Zzzz",
        park_location: None,
        bind_location: None,
        level: None,
        items: None,
    };
    let value = serde_json::to_value(&msg).unwrap();
    assert_eq!(
        value,
        json!({ "type": "update_location", "character_name": "Zzzz" })
    );
}

#[test]
fn all_fixtures_validate_against_vendored_schema() {
    let schema = vendored_schema();
    let validator = jsonschema::validator_for(&schema).expect("compile vendored schema");
    for path in fixture_paths() {
        let value = read_value(&path);
        if let Err(err) = validator.validate(&value) {
            panic!("fixture {} failed schema validation: {err}", path.display());
        }
    }
}

#[test]
fn serialized_outbound_validates_against_schema() {
    let schema = vendored_schema();
    let validator = jsonschema::validator_for(&schema).expect("compile vendored schema");

    let settings = json!({ "auto_add_local_characters": true });
    let items = json!({ "seb": true, "vp": false });
    let messages = [
        serde_json::to_value(WsOutbound::Auth {
            access_key: "AccessKeyExample1234",
            client_version: "2.0.0",
            client_settings: &settings,
        })
        .unwrap(),
        serde_json::to_value(WsOutbound::LoginAuth {
            request_id: "abc",
            username: "mytag",
        })
        .unwrap(),
        serde_json::to_value(WsOutbound::Heartbeat {
            character_name: "Zzzz",
        })
        .unwrap(),
        serde_json::to_value(WsOutbound::UpdateLocation {
            character_name: "Zzzz",
            park_location: Some("Plane of Knowledge"),
            bind_location: Some("Toxxulia Forest"),
            level: Some(60),
            items: items.as_object(),
        })
        .unwrap(),
        serde_json::to_value(WsOutbound::UpdateLocation {
            character_name: "Zzzz",
            park_location: None,
            bind_location: None,
            level: None,
            items: None,
        })
        .unwrap(),
        serde_json::to_value(WsOutbound::Fte {
            mob: "Lord Nagafen",
            player: "Zzzz",
            character_name: "Zzzz",
            eq_log_time: "Wed Jul 15 22:14:05 2026",
        })
        .unwrap(),
        serde_json::to_value(WsOutbound::MobDeath {
            mob: "Lord Nagafen",
            eq_log_time: "Wed Jul 15 22:19:41 2026",
            character_name: "Zzzz",
        })
        .unwrap(),
        serde_json::to_value(WsOutbound::Pong).unwrap(),
    ];

    for msg in &messages {
        if let Err(err) = validator.validate(msg) {
            panic!("serialized outbound {msg} failed schema validation: {err}");
        }
    }
}

/// Cross-repo drift guard: when the sibling `roboToald` repo is checked out
/// alongside this one, the vendored schema and fixtures must be byte-identical
/// to the canonical copies the server owns. Skipped (not failed) when the
/// sibling repo is absent, so CI that clones only this repo stays green.
#[test]
fn vendored_copies_match_canonical_when_sibling_present() {
    let canonical_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("roboToald")
        .join("schemas");
    if !canonical_root.exists() {
        eprintln!(
            "roboToald sibling repo not found at {}; skipping drift check",
            canonical_root.display()
        );
        return;
    }

    let vendored_schema = std::fs::read(schemas_dir().join("ws-protocol.schema.json")).unwrap();
    let canonical_schema = std::fs::read(canonical_root.join("ws-protocol.schema.json")).unwrap();
    assert_eq!(
        vendored_schema, canonical_schema,
        "vendored ws-protocol.schema.json drifted from canonical roboToald copy; re-vendor it"
    );

    let base = fixtures_dir();
    for path in fixture_paths() {
        let rel = path.strip_prefix(&base).unwrap();
        let canonical = canonical_root.join("fixtures").join(rel);
        assert!(
            canonical.exists(),
            "canonical fixture missing: {}",
            canonical.display()
        );
        assert_eq!(
            std::fs::read(&path).unwrap(),
            std::fs::read(&canonical).unwrap(),
            "fixture {} drifted from canonical copy; re-vendor it",
            rel.display()
        );
    }
}
