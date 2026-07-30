import { useCallback, useEffect, useState } from "react";

import type { DesktopClient } from "../../ipc/Client";

export interface LogLine {
  timestamp: string;
  level: string;
  target: string;
  message: string;
}

export interface LogSnapshot {
  lines: LogLine[];
  file_path: string | null;
}

const POLL_MS = 1500;

export function useRecentLogs(client: DesktopClient, minLevel: string) {
  const [snapshot, setSnapshot] = useState<LogSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await client.getRecentLogs(5000, minLevel);
      setSnapshot(next);
      setError(null);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
    }
  }, [client, minLevel]);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => {
      void refresh();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  return { snapshot, error, refresh };
}
