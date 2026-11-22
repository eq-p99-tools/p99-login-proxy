import { getCurrentWindow } from "@tauri-apps/api/window";

export const MODAL_WINDOW_LABEL = "modal";
/** Tells the topmost window to reload its queue. */
export const MODALS_UPDATED_EVENT = "modals-updated";
/** Carries one popup to the main window's in-app dialog. */
export const SHOW_MODAL_EVENT = "show-modal";

/**
 * True when this webview is the topmost popup window. In Tauri the window label
 * decides; in a plain browser (dev preview) `?view=modal` does.
 */
export function isModalWindow(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  if ("__TAURI_INTERNALS__" in window) {
    try {
      return getCurrentWindow().label === MODAL_WINDOW_LABEL;
    } catch {
      return false;
    }
  }
  return new URLSearchParams(window.location.search).get("view") === MODAL_WINDOW_LABEL;
}
