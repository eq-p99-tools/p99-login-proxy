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

appdir="target/x86_64-unknown-linux-gnu/release/bundle/appimage/P99 Login Proxy.AppDir"
if [ ! -d "$appdir" ]; then
  echo "AppDir not found: $appdir" >&2
  exit 1
fi

found="$(find "$appdir" \( -type f -o -type l \) -printf '%f\n' | grep -E '^(libwayland-|libxkbcommon|libxcb|libXau|libXdmcp)' || true)"
if [ -n "$found" ]; then
  echo "AppImage still bundles host display libraries:" >&2
  printf '%s\n' "$found" >&2
  exit 1
fi
