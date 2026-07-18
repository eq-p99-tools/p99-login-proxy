// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    p99_login_proxy_native_lib::webview2_preflight::run_preflight_or_exit();
    p99_login_proxy_native_lib::run()
}
