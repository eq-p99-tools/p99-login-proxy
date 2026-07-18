import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef, useState } from "react";

import { Button, ModalDialog } from "../components";
import { useRuntimeStore } from "../features/runtime/store";

interface AlertState {
  title: string;
  message: string;
}

/**
 * App-level message boxes matching the Python QMessageBox popups:
 * "SSO Login Rejected", "SSO Connection Error", and "Rustle UI Detected".
 */
export function SystemDialogs() {
  const [alert, setAlert] = useState<AlertState | null>(null);
  const wsState = useRuntimeStore((s) => s.runtime?.bootstrap.ws_state);
  const wsError = useRuntimeStore((s) => s.runtime?.bootstrap.ws_error);
  const connectionErrorShownRef = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) {
      return;
    }
    let cancelled = false;
    const unlisteners: (() => void)[] = [];

    void listen<{ username: string; reason: string }>("login-rejected", (event) => {
      if (cancelled) return;
      setAlert({
        title: "SSO Login Rejected",
        message: event.payload.reason || "Authentication rejected by server",
      });
    }).then((fn) => unlisteners.push(fn));

    void listen<{ message: string }>("rustle-warning", (event) => {
      if (cancelled) return;
      setAlert({ title: "Rustle UI Detected", message: event.payload.message });
    }).then((fn) => unlisteners.push(fn));

    return () => {
      cancelled = true;
      unlisteners.forEach((fn) => fn());
    };
  }, []);

  useEffect(() => {
    if (wsState !== "auth_failed") {
      connectionErrorShownRef.current = false;
      return;
    }
    if (!connectionErrorShownRef.current) {
      connectionErrorShownRef.current = true;
      setAlert({
        title: "SSO Connection Error",
        message: wsError || "Authentication failed",
      });
    }
  }, [wsState, wsError]);

  return (
    <ModalDialog
      title={alert?.title ?? ""}
      open={alert != null}
      onClose={() => setAlert(null)}
      footer={
        <Button variant="secondary" onClick={() => setAlert(null)}>
          OK
        </Button>
      }
    >
      <p className="modal-message-pre">{alert?.message}</p>
    </ModalDialog>
  );
}
