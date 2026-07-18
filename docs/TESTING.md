# Testing the native proxy

## Automated tests

```powershell
cd p99-login-proxy-native
npm test
cargo test -p protocol -p proxy-core -p runtime
npm run build
cargo build -p p99-login-proxy-native
```

Frontend tests cover layout parity, SSO roster/search/sort, local character roster, and IPC schema validation.

The `runtime` crate includes a **loopback integration test** that verifies:
client → proxy → fake upstream → proxy → client forwarding.

## Manual parity checklist (708×550 window)

Run `npm run tauri dev` and verify:

1. **Proxy tab** — mode tooltips, dark mode + always-on-top persistence, API token eye icon, 1.5s token save debounce, SSO/local account summaries, Force Reconnect
2. **SSO tab** — six subtabs, character legend/colors, local accounts CRUD, local characters 13-column grid + full edit dialog
3. **Advanced tab** — Browse eqgame.exe, Launch on Start / as Admin persistence, eqhost panels, Restore/Open Folder
4. **Log tab** — Clear (not Refresh), auto-scroll, word wrap, level filter, log file path shown
5. **Changelog tab** — GitHub release HTML from `eq-p99-tools/p99-login-proxy`
6. **Extras tab** — skip SSO accounts, secondary EQ path, prerelease updates, update check
7. **Tray** — Show/Hide label, Launch EQ, Check Updates, dynamic tooltip, double-click toggle, minimize notification
8. **Icons** — tray/window icon changes with proxy mode (blue/orange/red) and Kingdom backend
9. **Persistence** — restart app: proxy mode, token, dark mode, always-on-top, launch settings restored
10. **Exit** — tray Exit restores eqhost.txt from backup when proxy was enabled
11. **Portable files** — settings update exe-adjacent `proxyconfig.ini`; token values migrate to the keyring and disappear from the INI; CSVs and `proxy.log` use the configured/exe-adjacent paths
12. **Updater** — Windows: `P99LoginProxy-{version}.zip` replaces `P99LoginProxy.exe`, keeps a versioned backup, and relaunches. Linux AppImage: `P99LoginProxy-{version}-x86_64.AppImage` replaces the current `$APPIMAGE` path and relaunches.

Automated migration coverage lives in `tests/fixtures/v1_portable/` and Rust tests for INI,
CSV, token migration, EQ discovery, custom SSO backends, and CA bundle parsing. **Full
v1→v2 migration is not verified for production until the RC matrix in
[`docs/RELEASE.md`](RELEASE.md) passes.**

## Manual test with real EverQuest (proxy-only / passthrough)

### 1. Start the native app

```powershell
cd p99-login-proxy-native
npm run tauri dev
```

### 2. Configure proxy

In the **Proxy** tab:

| Setting | Notes |
|---------|-------|
| Listen | `127.0.0.1:5998` |
| Upstream | `login.eqemulator.net:5998` |
| Proxy Mode | **Enabled (Proxy Only)** |

### 3. Point EQ at the proxy

Set `eqhost.txt` in your EQ directory:

```text
Host=127.0.0.1:5998
```

Or use **Advanced → Browse** to select `eqgame.exe` and enable proxy mode.

### 4. Log in with EQ

Launch EverQuest via footer **Launch EverQuest** or your launcher.
With **Proxy Only** mode, credentials pass through unchanged.

### 5. Stop

Set Proxy Mode to **Disabled** or use tray **Exit** (restores eqhost backup).

## Logs & debugging

- **Log** tab shows recent runtime lines (polls every 1.5s); **Clear** resets the in-app buffer
- Logs append to `proxy.log` beside `P99LoginProxy.exe`
- For packet-level detail:

```powershell
$env:RUST_LOG = "debug"
npm run tauri dev
```

## SSO login test

1. **Proxy** tab → select SSO backend → paste access key (auto-saves after 1.5s)
2. Wait for WebSocket **Connected (Live)** and accounts cached
3. **Advanced** tab → Browse to EQ directory
4. **Proxy** tab → **Enabled (SSO)** mode
5. Log in with an SSO alias
6. Check `proxy.log` for `login method=sso` and credential rewrite; tray notification on proxied login

## Headless test (no GUI)

```powershell
cargo test -p runtime proxy_forwards_client -- --nocapture
```

## Troubleshooting

| Symptom | Check |
|---------|-------|
| EQ can't connect | Proxy running? `eqhost.txt` has correct Host line? |
| Immediate disconnect | Upstream DNS — can you resolve `login.eqemulator.net`? |
| Nothing in proxy UI | Use `tauri dev` not `npm run dev` alone |
| Token not loading | Check the OS keyring entry `com.p99loginproxy` / `sso:{backend}`; tokens are intentionally removed from INI |
| Tray icon wrong color | Proxy mode: blue=SSO, orange=proxy-only, red=disabled |
