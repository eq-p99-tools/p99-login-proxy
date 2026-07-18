# Linux packaging notes

- Linux remains manually buildable, but tagged releases publish only the Windows portable
  zip so Python 1.x updaters cannot select an incompatible asset.
- A fully static musl binary is not feasible because Tauri links system WebKitGTK.
- The Python-style automatic installer is Windows-only. Linux users replace their binary
  manually.
- **Validation targets:** Ubuntu 24.04 LTS (GNOME Wayland/X11), current Fedora KDE

Build with `npm run tauri build -- --target x86_64-unknown-linux-gnu --no-bundle`.

## Constraints

- The app does not install or manage a Wine/Proton prefix. When the user clicks
  **Launch EverQuest**, it invokes `wine eqgame.exe patchme` (requires `wine` on PATH);
  otherwise users may launch EverQuest externally.
- App may read user-selected EQ directories (including paths inside external prefixes)

## Beta checklist

- [ ] Native executable launches on Ubuntu 24.04 Wayland
- [ ] eqhost.txt read/write on user-selected prefix path
- [ ] Launch EverQuest spawns `wine eqgame.exe patchme` when Wine is installed
