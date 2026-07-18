export type ThemeMode = "dark" | "light" | "system";

let systemQuery: MediaQueryList | null = null;
let systemListener: ((event: MediaQueryListEvent) => void) | null = null;

function setResolvedTheme(theme: "dark" | "light"): void {
  document.documentElement.dataset.theme = theme;
  delete document.body.dataset.theme;
}

/** Apply theme tokens and follow OS changes while System Default is selected. */
export function applyAppTheme(mode: ThemeMode): void {
  if (systemQuery && systemListener) {
    systemQuery.removeEventListener("change", systemListener);
  }
  systemQuery = null;
  systemListener = null;

  if (mode !== "system" || typeof window.matchMedia !== "function") {
    setResolvedTheme(mode === "light" ? "light" : "dark");
    return;
  }

  systemQuery = window.matchMedia("(prefers-color-scheme: dark)");
  setResolvedTheme(systemQuery.matches ? "dark" : "light");
  systemListener = (event) => setResolvedTheme(event.matches ? "dark" : "light");
  systemQuery.addEventListener("change", systemListener);
}
