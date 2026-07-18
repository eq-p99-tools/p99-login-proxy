import { create } from "zustand";

import type { BootstrapState } from "../../ipc/schemas";

interface BootstrapStore {
  bootstrap: BootstrapState | null;
  setBootstrap: (bootstrap: BootstrapState) => void;
}

export const useBootstrapStore = create<BootstrapStore>((set) => ({
  bootstrap: null,
  setBootstrap: (bootstrap) => set({ bootstrap }),
}));
