import { create } from "zustand";

export type UpdatePhase = "idle" | "prompt" | "info" | "downloading" | "installing" | "error";

interface UpdaterState {
  phase: UpdatePhase;
  version: string | null;
  title: string;
  message: string;
  progress: number | null;
  error: string | null;
  promptUpdate: (version: string | null, message: string) => void;
  showUpdateInfo: (title: string, message: string) => void;
  dismiss: () => void;
  setPhase: (phase: UpdatePhase) => void;
  setProgress: (progress: number | null) => void;
  setError: (error: string) => void;
}

export const useUpdaterStore = create<UpdaterState>((set) => ({
  phase: "idle",
  version: null,
  title: "",
  message: "",
  progress: null,
  error: null,
  promptUpdate: (version, message) =>
    set({
      phase: "prompt",
      version,
      title: version ? `Update Available (v${version})` : "Update Available",
      message,
      progress: null,
      error: null,
    }),
  showUpdateInfo: (title, message) =>
    set({ phase: "info", version: null, title, message, progress: null, error: null }),
  dismiss: () => set({ phase: "idle", progress: null, error: null }),
  setPhase: (phase) => set({ phase }),
  setProgress: (progress) => set({ progress }),
  setError: (error) => set({ phase: "error", error }),
}));
