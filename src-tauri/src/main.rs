// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Err(error) = p99_login_proxy_native_lib::wait_for_update_parent_if_requested() {
        p99_login_proxy_native_lib::webview2_preflight::show_startup_error(&error);
        std::process::exit(1);
    }
    p99_login_proxy_native_lib::normalize_release_working_directory();
    p99_login_proxy_native_lib::webview2_preflight::run_preflight_or_exit();
    p99_login_proxy_native_lib::run();
}
