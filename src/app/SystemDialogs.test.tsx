import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MockClient } from "../ipc/MockClient";
import type { ModalEntry } from "../ipc/schemas";
import { AppProviders } from "./AppProviders";
import { SystemDialogs } from "./SystemDialogs";

const listeners = new Map<string, (event: { payload: unknown }) => void>();

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async (name: string, handler: (event: { payload: unknown }) => void) => {
    listeners.set(name, handler);
    return () => listeners.delete(name);
  }),
}));

function emit(name: string, payload: unknown) {
  act(() => listeners.get(name)?.({ payload }));
}

function entry(overrides: Partial<ModalEntry> = {}): ModalEntry {
  return {
    id: 1,
    title: "SSO Login Rejected",
    level: "error",
    always_on_top: false,
    dedupe_id: null,
    body: { kind: "text", message: "Authentication failed" },
    received_at_ms: 0,
    ...overrides,
  };
}

beforeEach(() => {
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
});

afterEach(() => {
  cleanup();
  listeners.clear();
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
});

function renderDialogs() {
  render(
    <AppProviders client={new MockClient()}>
      <SystemDialogs />
    </AppProviders>,
  );
}

describe("SystemDialogs", () => {
  it("shows backend popups one at a time with their level", async () => {
    renderDialogs();
    await waitFor(() => expect(listeners.has("show-modal")).toBe(true));

    emit("show-modal", entry());
    emit(
      "show-modal",
      entry({ id: 2, title: "Rustle UI Detected", level: "warning", body: { kind: "text", message: "Skin found" } }),
    );

    expect(await screen.findByText("SSO Login Rejected")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Error" })).toBeTruthy();
    expect(screen.queryByText("Skin found")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(await screen.findByText("Skin found")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Warning" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("drops a repeat of a pending popup with the same dedupe id", async () => {
    renderDialogs();
    await waitFor(() => expect(listeners.has("show-modal")).toBe(true));

    const repeated = entry({ title: "Maintenance", level: "info", dedupe_id: "m1" });
    emit("show-modal", repeated);
    emit("show-modal", { ...repeated, id: 2 });

    expect(await screen.findByText("Maintenance")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("ignores malformed payloads", async () => {
    renderDialogs();
    await waitFor(() => expect(listeners.has("show-modal")).toBe(true));

    emit("show-modal", { title: "no body" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
