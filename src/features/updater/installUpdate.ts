import { useUpdaterStore } from "./store";

export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Download, replace, and relaunch the portable executable. */
export async function downloadAndInstallUpdate(): Promise<void> {
  const store = useUpdaterStore.getState();
  if (!isTauriRuntime()) {
    store.setError("Updates are only available in the desktop app.");
    return;
  }

  try {
    if (!store.version) {
      store.setError("The update version is missing.");
      return;
    }

    store.setPhase("downloading");
    const [{ invoke }, { listen }] = await Promise.all([
      import("@tauri-apps/api/core"),
      import("@tauri-apps/api/event"),
    ]);
    const unlisten = await listen<{ downloaded: number; total: number | null }>(
      "update-progress",
      ({ payload }) => {
        useUpdaterStore
          .getState()
          .setProgress(payload.total && payload.total > 0 ? payload.downloaded / payload.total : null);
      },
    );
    try {
      await invoke("install_update", { version: store.version });
      useUpdaterStore.getState().setPhase("installing");
    } finally {
      unlisten();
    }
  } catch (e) {
    store.setError(e instanceof Error ? e.message : String(e));
  }
}
