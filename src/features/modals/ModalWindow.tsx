import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useState } from "react";

import { applyAppTheme } from "../../app/theme";
import { Button } from "../../components";
import type { DesktopClient, ModalEntry } from "../../ipc/Client";
import { ModalContent, ModalLevelIcon } from "./ModalContent";
import { MODALS_UPDATED_EVENT } from "./windowKind";

function formatTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function Entry({ entry }: { entry: ModalEntry }) {
  return (
    <section className={`modal-window-entry modal-level-${entry.level}`} aria-label={entry.title}>
      <header className="modal-window-entry-header">
        <ModalLevelIcon level={entry.level} />
        <strong>{entry.title}</strong>
        <span className="login-notes-muted modal-window-time">{formatTime(entry.received_at_ms)}</span>
      </header>
      <ModalContent body={entry.body} />
    </section>
  );
}

/**
 * Contents of the always-on-top popup window: every topmost popup (login notes,
 * server `show_modal` with `always_on_top`) since the last acknowledgement.
 */
export function ModalWindow({ client }: { client: DesktopClient }) {
  const [entries, setEntries] = useState<ModalEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    client
      .getModals()
      .then((next) => {
        setEntries(next);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)));
  }, [client]);

  useEffect(() => {
    load();
    void client
      .getAppConfig()
      .then((cfg) => applyAppTheme(cfg.theme_mode))
      .catch(() => applyAppTheme("system"));
  }, [client, load]);

  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) {
      return;
    }
    let cancelled = false;
    let unlisten: (() => void) | null = null;
    void listen(MODALS_UPDATED_EVENT, () => {
      if (!cancelled) load();
    }).then((fn) => (cancelled ? fn() : (unlisten = fn)));
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [load]);

  const acknowledge = () => {
    void client
      .acknowledgeModals()
      .then(() => setEntries([]))
      .catch((e: unknown) => setError(String(e)));
  };

  const count = entries?.length ?? 0;
  const hasLoginNotes = entries?.some((e) => e.body.kind === "login_notes") ?? false;

  return (
    <div className="modal-window">
      <main className="modal-window-body">
        {hasLoginNotes ? (
          <p className="login-notes-muted">Your login went through as usual. Read these notes before you play.</p>
        ) : null}
        {error ? <p role="alert">{error}</p> : null}
        {entries == null ? <p className="login-notes-muted">Loading…</p> : null}
        {entries != null && count === 0 ? <p className="login-notes-muted">Nothing to acknowledge.</p> : null}
        {entries?.map((entry) => <Entry key={entry.id} entry={entry} />)}
      </main>
      <footer className="modal-window-footer">
        <Button variant="primary" autoFocus onClick={acknowledge}>
          {count > 1 ? `Acknowledge all (${count})` : "Acknowledge"}
        </Button>
      </footer>
    </div>
  );
}
