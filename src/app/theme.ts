import { getCurrentWindow } from "@tauri-apps/api/window";

import type { ThemeMode } from "../ipc/schemas";

export type ResolvedTheme =
  | "dark"
  | "light"
  | "gnomish"
  | "iceclad"
  | "kelethin"
  | "lavastorm"
  | "erudin"
  | "paineel";

const DIRECT_THEMES: ThemeMode[] = [
  "gnomish",
  "iceclad",
  "kelethin",
  "lavastorm",
  "erudin",
  "paineel",
];

export const THEME_OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: "system", label: "System Default" },
  { value: "light", label: "Qeynos Harbor" },
  { value: "dark", label: "Nektulos Forest" },
  { value: "gnomish", label: "Gnomish Terminal" },
  { value: "iceclad", label: "Iceclad Ocean" },
  { value: "kelethin", label: "Kelethin Treetops" },
  { value: "lavastorm", label: "Lavastorm Mountains" },
  { value: "paineel", label: "Paineel Undercity" },
  { value: "erudin", label: "Erudin Library" },
];

let systemQuery: MediaQueryList | null = null;
let systemListener: ((event: MediaQueryListEvent) => void) | null = null;

function setResolvedTheme(theme: ResolvedTheme): void {
  document.documentElement.dataset.theme = theme;
  delete document.body.dataset.theme;
}

export function resolveTheme(mode: ThemeMode): ResolvedTheme {
  if (mode === "light") {
    return "light";
  }
  if (DIRECT_THEMES.includes(mode)) {
    return mode as ResolvedTheme;
  }
  if (mode === "system") {
    if (typeof window.matchMedia !== "function") {
      return "dark";
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return "dark";
}

/** True when the selected theme uses a dark palette (for legacy ``dark_mode`` INI field). */
export function themeUsesDarkPalette(mode: ThemeMode, systemDark = false): boolean {
  if (mode === "light" || mode === "erudin") {
    return false;
  }
  if (mode === "system") {
    return systemDark;
  }
  return true;
}

export function nativeWindowThemeForMode(mode: ThemeMode): "dark" | "light" | null {
  if (mode === "system") {
    return null;
  }
  return themeUsesDarkPalette(mode) ? "dark" : "light";
}

function applyNativeWindowTheme(mode: ThemeMode): void {
  if (!(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__) {
    return;
  }
  void getCurrentWindow()
    .setTheme(nativeWindowThemeForMode(mode))
    .catch((error: unknown) => {
      console.warn("Unable to apply native window theme", error);
    });
}

/** Apply theme tokens and follow OS changes while System Default is selected. */
export function applyAppTheme(mode: ThemeMode): void {
  applyNativeWindowTheme(mode);

  if (systemQuery && systemListener) {
    systemQuery.removeEventListener("change", systemListener);
  }
  systemQuery = null;
  systemListener = null;

  if (mode !== "system" || typeof window.matchMedia !== "function") {
    setResolvedTheme(resolveTheme(mode));
    return;
  }

  systemQuery = window.matchMedia("(prefers-color-scheme: dark)");
  setResolvedTheme(systemQuery.matches ? "dark" : "light");
  systemListener = (event) => setResolvedTheme(event.matches ? "dark" : "light");
  systemQuery.addEventListener("change", systemListener);
}
