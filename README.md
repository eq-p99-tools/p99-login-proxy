# P99 Login Proxy (Native)

Rust + Tauri 2 + React rewrite of the P99 SSO Login Proxy.

## Stack

- **protocol** — pure SOE/EQ wire parsing (no I/O)
- **proxy-core** — config, credential routing, EQ files, log patterns
- **runtime** — UDP proxy, WebSocket, watchers, `AppSupervisor`
- **src-tauri** — desktop shell, tray, single-instance, updater
- **src/** — modular React UI (`src/features/*`, `src/ipc/*`)

## Development

```powershell
cd p99-login-proxy-native
npm install
npm run tauri dev
```

```powershell
cargo test -p protocol -p proxy-core
```

Regenerate protocol oracle fixtures:

```powershell
..\.venv\Scripts\python.exe tools\generate_oracle.py
```

## Platforms

- Windows 10/11 (portable `P99LoginProxy.exe` zip + Python-compatible self-update)
- Linux x86_64 (manual native build; WebKitGTK required)

Linux can launch `wine eqgame.exe patchme` when Wine is on `PATH`.

## Portable configuration

`proxyconfig.ini`, `local_accounts.csv`, `local_characters.csv`, and `proxy.log` live
beside the executable. Existing Python INI settings are preserved. Plaintext API tokens
are migrated to the OS keyring on first launch and removed from the INI. The login DES
key and IV default to eight zero bytes, matching the game protocol.

## Migration

See [docs/parity.md](docs/parity.md) for intentional deviations from the Python app.
