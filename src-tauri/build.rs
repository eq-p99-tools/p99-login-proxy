fn main() {
    let manifest_dir =
        std::path::PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let source = manifest_dir.join("resources/webview2/MicrosoftEdgeWebview2Setup.exe");
    let out_dir = std::path::PathBuf::from(std::env::var("OUT_DIR").expect("OUT_DIR"));
    let embedded = out_dir.join("MicrosoftEdgeWebview2Setup.exe");

    if source.is_file() {
        std::fs::copy(&source, &embedded).expect("copy WebView2 bootstrapper to OUT_DIR");
    } else {
        std::fs::write(&embedded, []).expect("write empty WebView2 bootstrapper placeholder");
        println!(
            "cargo:warning=WebView2 bootstrapper missing at {}; release Windows builds must vendor it.",
            source.display()
        );
    }

    let generated = out_dir.join("webview2_bytes.rs");
    std::fs::write(
        &generated,
        format!(
            "pub const WEBVIEW2_BOOTSTRAPPER: &[u8] = include_bytes!(r\"{}\");",
            embedded.display()
        ),
    )
    .expect("write webview2_bytes.rs");

    tauri_build::build();
}
