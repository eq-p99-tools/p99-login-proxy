import { useMemo } from "react";

import { ErrorBoundary } from "../../app/ErrorBoundary";
import type { DesktopClient } from "../../ipc/Client";
import { MockClient } from "../../ipc/MockClient";
import { TauriClient } from "../../ipc/TauriClient";
import { LoginNotesWindow } from "./LoginNotesWindow";

/** Root for the login notes window; skips the main window's runtime sync. */
export function LoginNotesApp({ client: clientOverride }: { client?: DesktopClient }) {
  const client = useMemo<DesktopClient>(
    () =>
      clientOverride ??
      (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window
        ? new TauriClient()
        : new MockClient()),
    [clientOverride],
  );
  return (
    <ErrorBoundary>
      <LoginNotesWindow client={client} />
    </ErrorBoundary>
  );
}
