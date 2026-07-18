import { useEffect } from "react";

import { useBootstrapStore } from "../features/proxy/store";
import { AppProviders, useDesktopClient } from "./AppProviders";
import { AppShell } from "./AppShell";
import { ErrorBoundary } from "./ErrorBoundary";

function BootstrapLoader() {
  const client = useDesktopClient();
  const setBootstrap = useBootstrapStore((s) => s.setBootstrap);

  useEffect(() => {
    void client.getBootstrapState().then(setBootstrap);
  }, [client, setBootstrap]);

  return <AppShell />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <AppProviders>
        <BootstrapLoader />
      </AppProviders>
    </ErrorBoundary>
  );
}
