# Windows packaging notes

Windows distribution is portable-only. Build with:

```powershell
Invoke-WebRequest `
  -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" `
  -OutFile "src-tauri/resources/webview2/MicrosoftEdgeWebview2Setup.exe"
npm run tauri build -- --target x86_64-pc-windows-msvc --no-bundle
```

The result is `target/x86_64-pc-windows-msvc/release/P99LoginProxy.exe`. Keep
`proxyconfig.ini`, local CSVs, and `proxy.log` beside that executable.

The portable executable embeds Microsoft’s Evergreen WebView2 bootstrapper. On first
launch, if WebView2 is missing, the app installs it silently before opening the UI.
Internet access is required for that first install.

Tagged CI builds copy the binary to `P99LoginProxy-{version}.exe` and publish one Windows
asset: `P99LoginProxy-{version}.zip` with MIME type `application/zip`. Both Python 1.x
and native 2.x clients download that exact zip asset, back up the running stable
executable, extract the versioned member as `P99LoginProxy.exe`, and relaunch.

Linux AppImage assets are published beside the zip on the same GitHub release but are
ignored by legacy v1 updaters.

## Beta checklist

- [x] Portable zip updater and release workflow configured
- [x] Embedded WebView2 bootstrapper for missing-runtime installs
- [ ] RC migration matrix passed — see [`docs/RELEASE.md`](../docs/RELEASE.md)
- [ ] Smoke test on Windows 11
- [ ] Verify single-instance focuses existing window
- [ ] Verify close-to-tray when tray icon created
- [ ] Verify zip rename/extract/relaunch against a staging release
