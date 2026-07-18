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

    const apply = (raw: unknown) => {
      try {
        setRuntime(parseRuntimeState(raw));
        setSyncError(null);
      } catch (e) {
        setSyncError(e instanceof Error ? e.message : String(e));
      }
    };

    const bootstrap = async () => {
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

    void bootstrap();

    if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
      void listen("runtime-state", (event) => {
        if (!cancelled) {
          apply(event.payload);
        }
      }).then((fn) => {
        unlisten = fn;
      });
    }

    const pollId = window.setInterval(() => {
      void bootstrap();
    }, FALLBACK_POLL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(pollId);
      unlisten?.();
    };
  }, [client, setRuntime, setSyncError]);
}
