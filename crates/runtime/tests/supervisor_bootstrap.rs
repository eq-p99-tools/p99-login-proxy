//! Manual integration check against the real portable proxyconfig.ini (run with --ignored).

use runtime::AppSupervisor;

#[test]
#[ignore = "uses the real portable INI and OS keyring on this machine"]
fn supervisor_new_reflects_configured_api_token() {
    let (sup, snapshot_rx, _event_rx) = AppSupervisor::new();
    let snap = snapshot_rx.borrow();
    let backend = sup.sso_backend().to_string();
    let live = sup.secrets().has_token(&backend);
    eprintln!("sso_backend={backend}");
    eprintln!("snapshot.has_token={}", snap.bootstrap.has_token);
    eprintln!("live.has_token={live}");
    assert!(live, "expected token for configured backend {backend}");
    assert!(
        snap.bootstrap.has_token,
        "snapshot should match live token flag"
    );
}
