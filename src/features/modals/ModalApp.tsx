import { useMemo } from "react";

import { ErrorBoundary } from "../../app/ErrorBoundary";
import type { DesktopClient } from "../../ipc/Client";
import { MockClient } from "../../ipc/MockClient";
import { TauriClient } from "../../ipc/TauriClient";
import { ModalWindow } from "./ModalWindow";

/** Root for the topmost popup window; skips the main window's runtime sync. */
export function ModalApp({ client: clientOverride }: { client?: DesktopClient }) {
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
      <ModalWindow client={client} />
    </ErrorBoundary>
  );
}
