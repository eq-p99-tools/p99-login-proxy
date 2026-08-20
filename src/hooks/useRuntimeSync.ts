import { listen } from "@tauri-apps/api/event";
import { useEffect } from "react";

import type { DesktopClient } from "../ipc/Client";
import { parseRuntimeState } from "../ipc/schemas";
import { useRuntimeStore } from "../features/runtime/store";

const FALLBACK_POLL_MS = 5000;

export function useRuntimeSync(client: DesktopClient) {
  const setRuntime = useRuntimeStore((s) => s.setRuntime);
  const setSyncError = useRuntimeStore((s) => s.setSyncError);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    let pollId: number | undefined;

    const apply = (raw: unknown) => {
      try {
        setRuntime(parseRuntimeState(raw));
        setSyncError(null);
      } catch (e) {
        setSyncError(e instanceof Error ? e.message : String(e));
      }
    };

    const refresh = async () => {
      try {
        const state = await client.getRuntimeState();
        if (!cancelled) {
          setRuntime(state);
          setSyncError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setSyncError(e instanceof Error ? e.message : String(e));
        }
      }
    };

    const startFallbackPolling = () => {
      if (pollId == null) {
        pollId = window.setInterval(() => void refresh(), FALLBACK_POLL_MS);
      }
    };

    const setup = async () => {
      if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
        try {
          const stop = await listen("runtime-state", (event) => {
            if (!cancelled) {
              apply(event.payload);
            }
          });
          if (cancelled) {
            stop();
            return;
          }
          unlisten = stop;
        } catch (e) {
          if (!cancelled) {
            setSyncError(e instanceof Error ? e.message : String(e));
            startFallbackPolling();
          }
        }
      } else {
        startFallbackPolling();
      }
      await refresh();
    };
    void setup();

    return () => {
      cancelled = true;
      if (pollId != null) {
        window.clearInterval(pollId);
      }
      unlisten?.();
    };
  }, [client, setRuntime, setSyncError]);
}
