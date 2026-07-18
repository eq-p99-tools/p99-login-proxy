//! Install WebView2 from an embedded Evergreen bootstrapper when missing.
#![allow(unsafe_code)]

#[cfg(windows)]
mod embedded {
    include!(concat!(env!("OUT_DIR"), "/webview2_bytes.rs"));
    pub use WEBVIEW2_BOOTSTRAPPER as BOOTSTRAPPER_BYTES;
}

#[cfg(windows)]
use embedded::BOOTSTRAPPER_BYTES;

/// True when the WebView2 runtime is available to Tauri.
#[cfg(windows)]
pub fn webview_runtime_available() -> bool {
    tauri::webview_version().is_ok()
}

/// Install WebView2 when absent, using the embedded Microsoft bootstrapper.
#[cfg(windows)]
pub fn ensure_webview2_runtime() -> Result<(), String> {
    if webview_runtime_available() {
        return Ok(());
    }
    if BOOTSTRAPPER_BYTES.is_empty() {
        return Err(
            "WebView2 bootstrapper was not embedded in this build. Rebuild with \
             src-tauri/resources/webview2/MicrosoftEdgeWebview2Setup.exe present."
                .into(),
        );
    }
    run_embedded_bootstrapper()?;
    if webview_runtime_available() {
        Ok(())
    } else {
        Err(
            "WebView2 Runtime is required but could not be installed automatically. \
             Install the Evergreen WebView2 Runtime from Microsoft, then restart the app."
                .into(),
        )
    }
}

#[cfg(windows)]
fn run_embedded_bootstrapper() -> Result<(), String> {
    use std::io::Write;
    use std::os::windows::process::CommandExt;
    use std::process::Command;

    const CREATE_NO_WINDOW: u32 = 0x0800_0000;

    let temp_dir = std::env::temp_dir().join("P99LoginProxy-webview2");
    std::fs::create_dir_all(&temp_dir)
        .map_err(|error| format!("Could not create WebView2 install temp dir: {error}"))?;
    let installer = temp_dir.join("MicrosoftEdgeWebview2Setup.exe");
    {
        let mut file = std::fs::File::create(&installer)
            .map_err(|error| format!("Could not write WebView2 bootstrapper: {error}"))?;
        file.write_all(BOOTSTRAPPER_BYTES)
            .map_err(|error| format!("Could not write WebView2 bootstrapper: {error}"))?;
    }

    let status = Command::new(&installer)
        .arg("/silent")
        .arg("/install")
        .creation_flags(CREATE_NO_WINDOW)
        .status()
        .map_err(|error| format!("Failed to launch WebView2 bootstrapper: {error}"))?;
    if !status.success() {
        return Err(format!(
            "WebView2 bootstrapper exited with status {}",
            status
        ));
    }
    Ok(())
}

#[cfg(windows)]
pub fn show_startup_error(message: &str) {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use std::ptr;

    let title: Vec<u16> = OsStr::new("P99 Login Proxy")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let body: Vec<u16> = OsStr::new(message)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    unsafe {
        windows_sys::Win32::UI::WindowsAndMessaging::MessageBoxW(
            ptr::null_mut(),
            body.as_ptr(),
            title.as_ptr(),
            windows_sys::Win32::UI::WindowsAndMessaging::MB_OK
                | windows_sys::Win32::UI::WindowsAndMessaging::MB_ICONERROR,
        );
    }
}

#[cfg(windows)]
pub fn run_preflight_or_exit() {
    if let Err(error) = ensure_webview2_runtime() {
        show_startup_error(&error);
        std::process::exit(1);
    }
}

#[cfg(not(windows))]
pub fn run_preflight_or_exit() {}

#[cfg(test)]
mod tests {
    #[test]
    #[cfg(windows)]
    fn bootstrapper_is_embedded_on_release_builds() {
        if option_env!("PROFILE") == Some("release") {
            assert!(
                !super::BOOTSTRAPPER_BYTES.is_empty(),
                "Release Windows builds must embed the WebView2 bootstrapper"
            );
        }
    }
}
