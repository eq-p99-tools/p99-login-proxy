import { create } from "zustand";

import type { RuntimeState } from "../../ipc/schemas";

interface RuntimeStore {
  runtime: RuntimeState | null;
  syncError: string | null;
  setRuntime: (runtime: RuntimeState) => void;
  setSyncError: (error: string | null) => void;
}

export const useRuntimeStore = create<RuntimeStore>((set) => ({
  runtime: null,
  syncError: null,
  setRuntime: (runtime) => set({ runtime }),
  setSyncError: (syncError) => set({ syncError }),
}));

export const selectLifecycle = (s: RuntimeStore) =>
  s.runtime?.bootstrap.proxy_lifecycle ?? "stopped";

export const selectStats = (s: RuntimeStore) => s.runtime?.stats ?? null;

export const selectWsState = (s: RuntimeStore) =>
  s.runtime?.bootstrap.ws_state ?? "disconnected";
