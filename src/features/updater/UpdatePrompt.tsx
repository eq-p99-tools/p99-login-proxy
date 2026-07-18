import { listen } from "@tauri-apps/api/event";
import { useEffect } from "react";

import { Button, ModalDialog } from "../../components";
import { downloadAndInstallUpdate, isTauriRuntime } from "./installUpdate";
import { useUpdaterStore } from "./store";

/**
 * "Update Available" dialog with download progress. Triggered by the Rust
 * startup/scheduled check (``update-available`` event) or the Extras
 * "Check for updates" button via the updater store.
 */
export function UpdatePrompt() {
  const phase = useUpdaterStore((s) => s.phase);
  const title = useUpdaterStore((s) => s.title);
  const version = useUpdaterStore((s) => s.version);
  const message = useUpdaterStore((s) => s.message);
  const progress = useUpdaterStore((s) => s.progress);
  const error = useUpdaterStore((s) => s.error);
  const promptUpdate = useUpdaterStore((s) => s.promptUpdate);
  const showUpdateInfo = useUpdaterStore((s) => s.showUpdateInfo);
  const dismiss = useUpdaterStore((s) => s.dismiss);

  useEffect(() => {
    if (!isTauriRuntime()) {
      return;
    }
    let cancelled = false;
    const unlisteners: (() => void)[] = [];

    void listen<{ version: string | null; message: string }>("update-available", (event) => {
      if (!cancelled) {
        promptUpdate(event.payload.version, event.payload.message);
      }
    }).then((fn) => unlisteners.push(fn));

    void listen<{ title: string; message: string }>("update-check-info", (event) => {
      if (!cancelled) {
        showUpdateInfo(event.payload.title, event.payload.message);
      }
    }).then((fn) => unlisteners.push(fn));

    return () => {
      cancelled = true;
      unlisteners.forEach((fn) => fn());
    };
  }, [promptUpdate, showUpdateInfo]);

  if (phase === "idle") {
    return null;
  }

  const busy = phase === "downloading" || phase === "installing";
  const dialogTitle =
    phase === "error" ? "Update Error" : title || (version ? `Update Available (v${version})` : "Update Available");

  const progressText =
    phase === "installing"
      ? "Installing…"
      : phase === "downloading"
        ? progress != null
          ? `Downloading… ${Math.round(progress * 100)}%`
          : "Downloading…"
        : null;

  return (
    <ModalDialog
      title={dialogTitle}
      open
      onClose={busy ? () => {} : dismiss}
      footer={
        phase === "prompt" ? (
          <>
            <Button variant="secondary" onClick={dismiss}>
              Later
            </Button>
            <Button variant="primary" onClick={() => void downloadAndInstallUpdate()}>
              Update Now
            </Button>
          </>
        ) : phase === "info" || phase === "error" ? (
          <Button variant="secondary" onClick={dismiss}>
            OK
          </Button>
        ) : null
      }
    >
      {phase === "error" ? (
        <p className="tone-error modal-message-pre">{error}</p>
      ) : progressText ? (
        <p className="modal-message-pre">{progressText}</p>
      ) : (
        <p className="modal-message-pre">{message || "A new version is available."}</p>
      )}
    </ModalDialog>
  );
}
