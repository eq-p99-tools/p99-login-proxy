import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button, ModalDialog } from "../components";
import { ModalContent, ModalLevelIcon, SHOW_MODAL_EVENT } from "../features/modals";
import { ModalEntrySchema, type ModalEntry, type ModalLevel } from "../ipc/schemas";
import { useDesktopClient } from "./AppProviders";
import { useRuntimeStore } from "../features/runtime/store";

type QueuedModal = ModalEntry & { exitOnClose?: boolean };

/** In-app popups raised by the UI itself; ids count down so they never collide with backend ids. */
let nextLocalId = -1;

function localModal(title: string, message: string, level: ModalLevel, exitOnClose = false): QueuedModal {
  return {
    id: nextLocalId--,
    title,
    level,
    always_on_top: false,
    dedupe_id: null,
    body: { kind: "text", message },
    received_at_ms: Date.now(),
    exitOnClose,
  };
}

/**
 * The main window's in-app popup queue. Every non-topmost popup lands here
 * through `showModal`: backend popups (server `show_modal`, "SSO Login
 * Rejected", "Rustle UI Detected") arrive on the `show-modal` event, and the
 * UI adds "SSO Connection Error" and startup failures from runtime state.
 */
export function SystemDialogs() {
  const client = useDesktopClient();
  const [queue, setQueue] = useState<QueuedModal[]>([]);
  const wsState = useRuntimeStore((s) => s.runtime?.bootstrap.ws_state);
  const wsError = useRuntimeStore((s) => s.runtime?.bootstrap.ws_error);
  const startupError = useRuntimeStore((s) => s.runtime?.bootstrap.startup_error);
  const connectionErrorShownRef = useRef(false);
  const startupErrorShownRef = useRef(false);

  const showModal = useCallback((modal: QueuedModal) => {
    setQueue((current) =>
      modal.dedupe_id != null && current.some((m) => m.dedupe_id === modal.dedupe_id)
        ? current
        : [...current, modal],
    );
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) {
      return;
    }
    let cancelled = false;
    let unlisten: (() => void) | null = null;
    void listen<unknown>(SHOW_MODAL_EVENT, (event) => {
      if (cancelled) return;
      const parsed = ModalEntrySchema.safeParse(event.payload);
      if (parsed.success) showModal(parsed.data);
    }).then((fn) => (cancelled ? fn() : (unlisten = fn)));
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [showModal]);

  useEffect(() => {
    if (wsState !== "auth_failed") {
      connectionErrorShownRef.current = false;
      return;
    }
    if (!connectionErrorShownRef.current) {
      connectionErrorShownRef.current = true;
      showModal(localModal("SSO Connection Error", wsError || "Authentication failed", "error"));
    }
  }, [wsState, wsError, showModal]);

  useEffect(() => {
    if (!startupError) {
      startupErrorShownRef.current = false;
      return;
    }
    if (!startupErrorShownRef.current) {
      startupErrorShownRef.current = true;
      showModal(localModal("Error", startupError, "error", true));
    }
  }, [startupError, showModal]);

  const current = queue[0] ?? null;

  const handleClose = () => {
    const shouldExit = current?.exitOnClose ?? false;
    setQueue((q) => q.slice(1));
    if (shouldExit) {
      void client.requestShutdown();
    }
  };

  return (
    <ModalDialog
      title={current?.title ?? ""}
      open={current != null}
      onClose={handleClose}
      footer={
        <Button variant="secondary" onClick={handleClose}>
          OK
        </Button>
      }
    >
      {current ? (
        <div className={`modal-with-level modal-level-${current.level}`}>
          <ModalLevelIcon level={current.level} />
          <ModalContent body={current.body} />
        </div>
      ) : null}
    </ModalDialog>
  );
}
