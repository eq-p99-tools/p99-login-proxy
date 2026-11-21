import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useState } from "react";

import { applyAppTheme } from "../../app/theme";
import { Button } from "../../components";
import type { DesktopClient, LoginNotesEntry } from "../../ipc/Client";
import { LOGIN_NOTES_UPDATED_EVENT } from "./windowKind";

function formatTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function NotesEntry({ entry }: { entry: LoginNotesEntry }) {
  return (
    <section className="login-notes-entry" aria-label={`Notes for ${entry.account}`}>
      <header className="login-notes-entry-header">
        <strong>{entry.account}</strong>
        {entry.username.toLowerCase() !== entry.account.toLowerCase() ? (
          <span className="login-notes-muted"> logged in as {entry.username}</span>
        ) : null}
        <span className="login-notes-muted login-notes-time">{formatTime(entry.received_at_ms)}</span>
      </header>
      {entry.account_notes ? <p className="login-notes-text">{entry.account_notes}</p> : null}
      {entry.characters.length > 0 ? (
        <ul className="login-notes-characters">
          {entry.characters.map((c) => (
            <li key={c.name} className={c.typed ? "login-notes-typed" : undefined}>
              <strong>{c.name}</strong>
              {c.typed ? <span className="login-notes-muted"> (the name you logged in with)</span> : null}
              <p className="login-notes-text">{c.notes}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/**
 * Contents of the always-on-top login notes window. Lists every SSO login with
 * notes since the last acknowledgement; the login itself was never held.
 */
export function LoginNotesWindow({ client }: { client: DesktopClient }) {
  const [entries, setEntries] = useState<LoginNotesEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    client
      .getLoginNotes()
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
    void listen(LOGIN_NOTES_UPDATED_EVENT, () => {
      if (!cancelled) load();
    }).then((fn) => (cancelled ? fn() : (unlisten = fn)));
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [load]);

  const acknowledge = () => {
    void client
      .acknowledgeLoginNotes()
      .then(() => setEntries([]))
      .catch((e: unknown) => setError(String(e)));
  };

  const count = entries?.length ?? 0;

  return (
    <div className="login-notes-window">
      <header className="login-notes-header">
        <h1>Login Notes</h1>
        <p className="login-notes-muted">
          Your login went through as usual. Read these notes before you play.
        </p>
      </header>
      <main className="login-notes-body">
        {error ? <p role="alert">{error}</p> : null}
        {entries == null ? <p className="login-notes-muted">Loading…</p> : null}
        {entries != null && count === 0 ? (
          <p className="login-notes-muted">No unacknowledged login notes.</p>
        ) : null}
        {entries?.map((entry) => <NotesEntry key={entry.id} entry={entry} />)}
      </main>
      <footer className="login-notes-footer">
        <Button variant="primary" autoFocus onClick={acknowledge}>
          {count > 1 ? `Acknowledge all (${count})` : "Acknowledge"}
        </Button>
      </footer>
    </div>
  );
}
