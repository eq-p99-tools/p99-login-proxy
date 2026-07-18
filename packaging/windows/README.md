# Windows packaging notes

Windows distribution is portable-only. Build with:

```powershell
npm run tauri build -- --target x86_64-pc-windows-msvc --no-bundle
```

The result is `target/x86_64-pc-windows-msvc/release/P99LoginProxy.exe`. Keep
`proxyconfig.ini`, local CSVs, and `proxy.log` beside that executable. WebView2 is still
required (included with Windows 11 and current Windows 10).

Tagged CI builds copy the binary to `P99LoginProxy-{version}.exe` and publish one asset:
`P99LoginProxy-{version}.zip`. Both Python 1.x and Rust 2.x clients download the first zip
asset, back up the running stable executable, extract the versioned member as
`P99LoginProxy.exe`, and relaunch. There are no NSIS/MSI bundles, updater manifests,
signatures, or `latest.json`.

## Beta checklist

- [x] Portable zip updater and release workflow configured
- [ ] Smoke test on Windows 11
- [ ] Verify single-instance focuses existing window
- [ ] Verify close-to-tray when tray icon created
- [ ] Verify zip rename/extract/relaunch against a staging release
