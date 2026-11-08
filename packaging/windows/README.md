# Windows packaging notes

Windows distribution is portable-only. Build with:

```powershell
npm run tauri build -- --target x86_64-pc-windows-msvc --no-bundle
```

The result is `target/x86_64-pc-windows-msvc/release/P99LoginProxy.exe`. Keep
`proxyconfig.ini`, local CSVs, and `proxy.log` beside that executable.

The executable requires the Microsoft Edge WebView2 Runtime (preinstalled on Windows 11
and current Windows 10). If it is missing, the app shows an error and opens Microsoft's
download page; it does not embed or run the installer itself, because a binary that
drops and silently runs another executable trips antivirus heuristics.

Tagged CI builds copy the binary to `P99LoginProxy-{version}.exe` and publish one Windows
asset: `P99LoginProxy-{version}.zip` with MIME type `application/zip`. Both Python 1.x
and native 2.x clients download that exact zip asset, back up the running stable
executable, and relaunch. Native v2 verifies the zip against the release `SHA256SUMS`,
requires exactly one correctly named top-level executable, and waits for the old process
to exit before initializing the replacement.

Linux AppImage assets are published beside the zip on the same GitHub release but are
ignored by legacy v1 updaters.

## Beta checklist

- [x] Portable zip updater and release workflow configured
- [x] Missing WebView2 runtime directs the user to Microsoft's download page
- [ ] RC migration matrix passed — see [`docs/RELEASE.md`](../docs/RELEASE.md)
- [ ] Smoke test on Windows 11
- [ ] Verify single-instance focuses existing window
- [ ] Verify close-to-tray when tray icon created
- [ ] Verify zip rename/extract/relaunch against a staging release
