use tauri::AppHandle;
use tauri_plugin_notification::NotificationExt;
use tracing::debug;

pub fn login_method_label(method: &str) -> &str {
    match method {
        "sso" => "SSO",
        "local" => "Local Account",
        "local_char" => "Local Character",
        "proxy_only" => "Proxy Only",
        "skip_sso" => "SSO Skipped",
        "passthrough" => "Passthrough",
        other => other,
    }
}

pub fn format_login_body(alias: &str, account: &str, method: &str) -> String {
    let label = login_method_label(method);
    if alias != account {
        format!("{alias} → {account} ({label})")
    } else {
        format!("{account} ({label})")
    }
}

pub fn send_notification(app: &AppHandle, title: &str, body: &str) {
    if let Err(e) = app.notification().builder().title(title).body(body).show() {
        debug!(error = %e, "tray notification failed");
    }
}

pub fn notify_login_proxied(app: &AppHandle, alias: &str, account: &str, method: &str) {
    send_notification(
        app,
        "Login Proxied",
        &format_login_body(alias, account, method),
    );
}

pub fn notify_minimized_to_tray(app: &AppHandle) {
    send_notification(app, "Minimized to Tray", "Still running in the background.");
}
