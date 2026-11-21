# P99 Login Proxy (Native)

Rust + Tauri 2 + React rewrite of the P99 SSO Login Proxy.

## Stack

- **[eq-network](https://github.com/eq-p99-tools/eq-network)** — shared SOE
  transport and EQ login packet codecs
- **protocol** — proxy session rewriting and P99 server-list policy
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

## Login notes

SSO accounts and characters can carry notes (for example "kael factioned"). When an
SSO login resolves to an account with notes, the proxy logs you in as usual (the login
is never held) and opens a **Login Notes** window that stays on top of other windows
until you click **Acknowledge** or close it. It appears on every login to that account,
lists the account note and that account's character notes, and marks the character
whose name you typed. Notes are plain text and visible to everyone with access to the
account; edit them in Discord (`/sso_owner ... notes_set`) or the SSO dashboard.

The window cannot appear over EverQuest running in **exclusive fullscreen**. Run EQ in
windowed mode (`WindowedMode=TRUE` in `eqclient.ini`) to see it, or alt-tab after
logging in. On Linux the always-on-top behavior depends on the window manager.

## Portable configuration

`proxyconfig.ini`, `local_accounts.csv`, `local_characters.csv`, and `proxy.log` live
beside the executable. Existing Python INI settings are preserved. Plaintext API tokens
are migrated to the OS keyring on first launch and removed from the INI. The login DES
key and IV default to eight zero bytes, matching the game protocol.

## Migration

See [docs/parity.md](docs/parity.md) for intentional deviations from the Python app.
