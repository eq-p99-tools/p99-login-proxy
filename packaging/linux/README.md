# Linux packaging notes

- Tagged releases publish `P99LoginProxy-{version}-x86_64.AppImage` beside the Windows zip.
- The AppImage is uploaded with MIME type `application/vnd.appimage`, so legacy v1 Windows
  updaters ignore it even on mixed releases.
- Native v2 Linux auto-update requires launching the AppImage so `$APPIMAGE` is set.
- A fully static musl binary is not feasible because Tauri links system WebKitGTK.
- **Validation targets:** Ubuntu 24.04 LTS (GNOME Wayland/X11), current Fedora KDE

Build the AppImage with:

```bash
npm run tauri build -- --target x86_64-unknown-linux-gnu --config src-tauri/tauri.linux.bundle.json
```

The bundle lands under `src-tauri/target/x86_64-unknown-linux-gnu/release/bundle/appimage/`.

## Constraints

- The app does not install or manage a Wine/Proton prefix. When the user clicks
  **Launch EverQuest**, it invokes `wine eqgame.exe patchme` (requires `wine` on PATH);
  otherwise users may launch EverQuest externally.
- App may read user-selected EQ directories (including paths inside external prefixes)

## Beta checklist

- [ ] Native AppImage launches on Ubuntu 24.04 Wayland
- [ ] AppImage self-update replaces the current `$APPIMAGE` path and relaunches
- [ ] eqhost.txt read/write on user-selected prefix path
- [ ] Launch EverQuest spawns `wine eqgame.exe patchme` when Wine is installed
