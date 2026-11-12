#!/usr/bin/env bash
# Build the Linux AppImage without the Ubuntu runner's display libraries.
# Plasma 6 and Ubuntu 24.04 each need the Wayland and X11 client libraries
# that match that machine's Mesa. Copies from the build image abort startup
# with "Could not create default EGL display: EGL_BAD_PARAMETER".
set -euo pipefail

cd "$(dirname "$0")/.."

# Globs are matched against the library file name. Semicolon-separated.
export LINUXDEPLOY_EXCLUDED_LIBRARIES="${LINUXDEPLOY_EXCLUDED_LIBRARIES:-libwayland-*;libxkbcommon*;libxcb*;libXau*;libXdmcp*}"

npm run tauri build -- --target x86_64-unknown-linux-gnu --config src-tauri/tauri.linux.bundle.json "$@"

appimage_dir="target/x86_64-unknown-linux-gnu/release/bundle/appimage"
shopt -s nullglob
appdirs=("$appimage_dir"/*.AppDir)
if [ "${#appdirs[@]}" -ne 1 ]; then
  echo "Expected one AppDir under $appimage_dir, found ${#appdirs[@]}" >&2
  ls -la "$appimage_dir" >&2 || true
  exit 1
fi
appdir="${appdirs[0]}"

found="$(find "$appdir" \( -type f -o -type l \) -printf '%f\n' | grep -E '^(libwayland-|libxkbcommon|libxcb|libXau|libXdmcp)' || true)"
if [ -n "$found" ]; then
  echo "AppImage still bundles host display libraries:" >&2
  printf '%s\n' "$found" >&2
  exit 1
fi
