//! Check for the WebView2 runtime before Tauri starts.
//!
//! The app deliberately does not embed or run Microsoft's installer itself: an
//! executable that drops and silently runs another executable looks like a
//! dropper to antivirus heuristics. When WebView2 is missing, the user is sent
//! to Microsoft's download page instead.
#![allow(unsafe_code)]

#[cfg(windows)]
const WEBVIEW2_DOWNLOAD_URL: &str = "https://developer.microsoft.com/microsoft-edge/webview2/";

#[cfg(windows)]
pub fn run_preflight_or_exit() {
    if tauri::webview_version().is_ok() {
        return;
    }
    show_startup_error(&format!(
        "P99 Login Proxy needs the Microsoft Edge WebView2 Runtime, which is not installed.\n\n\
         After you click OK, Microsoft's download page will open. Install the \
         \"Evergreen Bootstrapper\", then start P99 Login Proxy again.\n\n\
         {WEBVIEW2_DOWNLOAD_URL}"
    ));
    open_in_browser(WEBVIEW2_DOWNLOAD_URL);
    std::process::exit(1);
}

#[cfg(not(windows))]
pub fn run_preflight_or_exit() {}

#[cfg(windows)]
fn to_wide(value: &str) -> Vec<u16> {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;

    OsStr::new(value)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}

#[cfg(windows)]
fn open_in_browser(url: &str) {
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

    let verb = to_wide("open");
    let target = to_wide(url);
    unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            verb.as_ptr(),
            target.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            SW_SHOWNORMAL,
        );
    }
}

#[cfg(windows)]
pub fn show_startup_error(message: &str) {
    use windows_sys::Win32::UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR, MB_OK};

    let title = to_wide("P99 Login Proxy");
    let body = to_wide(message);
    unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            body.as_ptr(),
            title.as_ptr(),
            MB_OK | MB_ICONERROR,
        );
    }
}

#[cfg(not(windows))]
pub fn show_startup_error(message: &str) {
    eprintln!("{message}");
}
