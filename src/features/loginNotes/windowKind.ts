import { getCurrentWindow } from "@tauri-apps/api/window";

export const LOGIN_NOTES_WINDOW_LABEL = "login-notes";
export const LOGIN_NOTES_UPDATED_EVENT = "login-notes-updated";

/**
 * True when this webview is the login notes window. In Tauri the window label
 * decides; in a plain browser (dev preview) `?view=login-notes` does.
 */
export function isLoginNotesWindow(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  if ("__TAURI_INTERNALS__" in window) {
    try {
      return getCurrentWindow().label === LOGIN_NOTES_WINDOW_LABEL;
    } catch {
      return false;
    }
  }
  return new URLSearchParams(window.location.search).get("view") === LOGIN_NOTES_WINDOW_LABEL;
}
