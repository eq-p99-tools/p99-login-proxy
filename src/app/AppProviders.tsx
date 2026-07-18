import { createContext, useContext, useMemo, type ReactNode } from "react";

import { TooltipProvider } from "../components/TooltipProvider";

import type { DesktopClient } from "../ipc/Client";
import { MockClient } from "../ipc/MockClient";
import { TauriClient } from "../ipc/TauriClient";
import { useRuntimeSync } from "../hooks/useRuntimeSync";

const ClientContext = createContext<DesktopClient | null>(null);

function createDefaultClient(): DesktopClient {
  if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
    return new TauriClient();
  }
  return new MockClient();
}

function RuntimeSync({ client }: { client: DesktopClient }) {
  useRuntimeSync(client);
  return null;
}

export function AppProviders({
  children,
  client: clientOverride,
}: {
  children: ReactNode;
  client?: DesktopClient;
}) {
  const client = useMemo(() => clientOverride ?? createDefaultClient(), [clientOverride]);
  return (
    <ClientContext.Provider value={client}>
      <TooltipProvider>
        <RuntimeSync client={client} />
        {children}
      </TooltipProvider>
    </ClientContext.Provider>
  );
}

export function useDesktopClient(): DesktopClient {
  const client = useContext(ClientContext);
  if (!client) {
    throw new Error("DesktopClient not available");
  }
  return client;
}
