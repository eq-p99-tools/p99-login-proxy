# Release and migration runbook

This guide covers publishing native v2 releases on the shared GitHub repository and
helping users migrate from Python v1.x portable installs.

## Branch and tag ownership

| Branch | Owns | Release tags |
|--------|------|--------------|
| `master` | Python v1.x maintenance | `v1.*` only |
| `rust` | Native v2.x | `v2.*` only |

Tag v2 releases **only** from commits on `origin/rust`. The release workflow refuses
tags that are not contained in that branch so a Python-tree commit cannot accidentally
publish a native build.

Keep the Python release workflow on `master` unchanged during the RC period. Tags are
repository-wide, but each workflow runs from the tagged commit’s tree.

## Release assets

Each v2 draft release publishes exactly three downloadable assets:

| Asset | MIME type | Used by |
|-------|-----------|---------|
| `P99LoginProxy-{version}.zip` | `application/zip` | Windows portable updater (v1 + v2) |
| `P99LoginProxy-{version}-x86_64.AppImage` | `application/vnd.appimage` | Linux AppImage users/updater |
| `SHA256SUMS` | `text/plain` | Native v2 artifact verification |

The zip contains exactly one top-level member: `P99LoginProxy-{version}.exe`. Native
updates fail closed unless the selected artifact matches its `SHA256SUMS` entry.

Legacy v1 updaters ignore the AppImage because it is neither named `.zip` nor uploaded
with a zip-like MIME type. Native v2 updaters select assets by exact filename, so asset
order on the release no longer matters.

## Prerelease RCs before stable cutover

1. Push tested native history to `origin/rust`.
2. Create `v2.<minor>.<patch>-rc.N` (for example `v2.0.1-rc.1`) on a `rust` commit. The dot
   matters: semver compares `rc.10` above `rc.9` but `rc10` as text, below `rc9`, so the
   release workflow rejects identifiers that mix letters and digits. The old `v2.0.0-rcN`
   tags all sort below any 2.0.1 release.
3. CI creates a **draft** release with both assets. Inspect it before publishing.
4. Confirm:
   - GitHub marks the release **prerelease** (tag contains `-`).
   - Windows zip layout is valid.
   - AppImage MIME type is `application/vnd.appimage`.
   - `SHA256SUMS` contains and verifies both platform artifacts.
5. Publish the draft manually. Opted-in v1 clients (`opt_into_prereleases = True`) can
   then see the RC; ordinary v1.4.2 installs do not.

## Stable v2.0.0 cutover

Publish stable `v2.0.0` only after the RC migration matrix passes (see
[`docs/TESTING.md`](TESTING.md)). Stable publication offers the native executable to
**all** normal v1.x clients — there is no major-version guard in the updater.

After rollout is healthy, switch the GitHub default branch to `rust` and keep Python on
a clearly named maintenance branch. Raising roboToald `min_client_version` is optional
and not required for the updater migration itself.

## Draft inspection checklist

- [ ] Tag matches `v2.<minor>.<patch>[-prerelease]`, prerelease like `rc.N`
- [ ] Tagged commit is on `origin/rust`
- [ ] Draft is marked prerelease when the tag suffix is present
- [ ] Windows zip, Linux AppImage, and `SHA256SUMS` assets present with expected names
- [ ] `sha256sum --check SHA256SUMS` succeeds
- [ ] Release notes mention the WebView2 requirement, stable exe, token backup, and rollback

## Portable update contract

Both Windows clients use the same zip contract:

1. `GET /repos/eq-p99-tools/p99-login-proxy/releases?per_page=10`
2. Semver-sort tags; require a newer release in the current major and respect the
   prerelease flag unless opted in
3. Download `P99LoginProxy-{version}.zip` and `SHA256SUMS`
4. Verify SHA-256, then require exactly one top-level member named
   `P99LoginProxy-{version}.exe`
5. Rename to stable `P99LoginProxy.exe` and spawn it in wait-for-parent mode
6. Shut down the old process; the replacement starts after the single-instance lock is released

Linux AppImage auto-update uses the same release list but downloads
`P99LoginProxy-{version}-x86_64.AppImage`, backs up the current AppImage, atomically
replaces the file referenced by `$APPIMAGE`, and relaunches.

There is no bridge Python release. Users must launch the stable `P99LoginProxy.exe`
after migration — old Start Menu/desktop shortcuts may still point at
`P99LoginProxy-1.4.2.exe`.

## User migration notes (include in release announcements)

### WebView2 (Windows 10)

Native v2 requires the Microsoft Edge WebView2 Runtime. Windows 11 and current Windows 10
already have it. If it is missing, the app shows an error and opens Microsoft's
download page; install the Evergreen Bootstrapper from there and start the app again.
Windows 10 1809+ is required.

### Config and CSV files

Place `proxyconfig.ini`, `local_accounts.csv`, and `local_characters.csv` beside
`P99LoginProxy.exe` on Windows or beside the launched `$APPIMAGE` on Linux. v1 sometimes
used CWD-relative paths.

On first start v2:

- Imports legacy INI keys, comments, and unknown settings
- Migrates plaintext `[api_tokens]` into the OS keyring, then scrubs them from the INI
- Auto-detects EverQuest when `eq_directory` is blank (same legacy search paths as v1)
- Loads custom `[sso_backends]` and `sso_ca_bundle` settings

**Back up** `proxyconfig.ini` and CSVs before testing an RC on live data.

### Token migration is one-way in the INI

After a successful keyring migration, tokens are removed from `proxyconfig.ini`. To run
Python v1 again, restore the backed-up INI or re-enter tokens manually.

### Manual rollback

1. Stop the native app and restore your saved `proxyconfig.ini` / CSV copies.
2. Launch the versioned Python backup if you kept one (e.g. `P99LoginProxy-1.4.2.exe`).
3. Use the stable `P99LoginProxy.exe` shortcut after a successful native update — do not
   rely on stale shortcuts to the old versioned Python binary.

## Rollback for operators

- Unpublish or mark bad releases as prerelease on GitHub if needed.
- Users can restore the previous stable `P99LoginProxy.exe` from the versioned backup
  the updater creates beside the portable folder.
- Do not add secondary zip assets to “fix” a release; publish a new tag instead.

## Local validation before tagging

```powershell
cd p99-login-proxy-native
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
npm ci
npm run build
npm test
```

Windows portable build:

```powershell
npm run tauri build -- --target x86_64-pc-windows-msvc --no-bundle
```

Linux AppImage build:

```bash
npm run tauri build -- --target x86_64-unknown-linux-gnu --config src-tauri/tauri.linux.bundle.json
```

Package and inspect the Windows zip locally:

```powershell
$version = (Select-String -Path Cargo.toml -Pattern '^\s*version\s*=' | Select-Object -First 1).Line.Split('"')[1]
$exe = "P99LoginProxy-$version.exe"
Copy-Item target/x86_64-pc-windows-msvc/release/P99LoginProxy.exe $exe
Compress-Archive -Path $exe -DestinationPath "P99LoginProxy-$version.zip" -Force
```

Automated archive and checksum checks live in the native updater tests. Tagged packaging
is gated on Rust format/tests/Clippy plus frontend tests/build before either platform is built.

## RC migration matrix (manual)

Run on clean Windows 10 and Windows 11 before stable `v2.0.0`:

1. Fresh v1.4.2 portable folder still running `P99LoginProxy-1.4.2.exe`
2. Previously updated install running stable `P99LoginProxy.exe`
3. Relaunch, INI/CSV import, tokens/keyring, EQ auto-detect, eqhost, `eqclient.ini` logging
4. All supported SSO backends (built-in and custom), local accounts, full exit/restore
5. RC-to-next-RC native self-update on Windows zip and Linux AppImage
6. Documented manual rollback, INI/token restoration, stale shortcut handling

Until this matrix passes, treat migration as **unverified** in support communications.
