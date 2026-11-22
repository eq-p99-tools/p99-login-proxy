import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MockClient } from "../../ipc/MockClient";
import type { ModalEntry } from "../../ipc/schemas";
import { ModalWindow } from "./ModalWindow";

afterEach(() => cleanup());

function notesEntry(overrides: Partial<ModalEntry> = {}): ModalEntry {
  return {
    id: 1,
    title: "Login notes: realbot01",
    level: "info",
    always_on_top: true,
    dedupe_id: null,
    body: {
      kind: "login_notes",
      username: "zzzz",
      account: "realbot01",
      account_notes: "Shared bot; log out at bind",
      characters: [
        { name: "Zzzz", notes: "Kael factioned", typed: true },
        { name: "Alpha", notes: "Bound in Skyshrine", typed: false },
      ],
    },
    received_at_ms: Date.UTC(2026, 10, 21, 18, 0, 0),
    ...overrides,
  };
}

function textEntry(overrides: Partial<ModalEntry> = {}): ModalEntry {
  return {
    id: 2,
    title: "Server maintenance",
    level: "warning",
    always_on_top: true,
    dedupe_id: "maint",
    body: { kind: "text", message: "Restarting at 9pm" },
    received_at_ms: Date.UTC(2026, 10, 21, 18, 1, 0),
    ...overrides,
  };
}

describe("ModalWindow", () => {
  it("shows login notes, flagging the typed character", async () => {
    const client = new MockClient();
    client.setMockModals([notesEntry()]);
    render(<ModalWindow client={client} />);

    expect(await screen.findByText("Shared bot; log out at bind")).toBeTruthy();
    expect(screen.getByText("Kael factioned")).toBeTruthy();
    expect(screen.getByText(/Logged in as zzzz/)).toBeTruthy();
    expect(screen.getByText(/the name you logged in with/)).toBeTruthy();
    expect(screen.getByText(/Your login went through as usual/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeTruthy();
  });

  it("shows a server popup with its title and level icon", async () => {
    const client = new MockClient();
    client.setMockModals([textEntry()]);
    render(<ModalWindow client={client} />);

    expect(await screen.findByText("Restarting at 9pm")).toBeTruthy();
    expect(screen.getByText("Server maintenance")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Warning" })).toBeTruthy();
    expect(screen.queryByText(/Your login went through as usual/)).toBeNull();
  });

  it("renders text as plain text, never markup", async () => {
    const client = new MockClient();
    client.setMockModals([
      textEntry({ body: { kind: "text", message: "<img src=x onerror=alert(1)>" } }),
      notesEntry({
        id: 3,
        body: {
          kind: "login_notes",
          username: "a",
          account: "a",
          account_notes: "<b>bold</b>",
          characters: [],
        },
      }),
    ]);
    const { container } = render(<ModalWindow client={client} />);

    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeTruthy();
    expect(screen.getByText("<b>bold</b>")).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("acknowledges every pending popup at once", async () => {
    const client = new MockClient();
    client.setMockModals([textEntry(), notesEntry()]);
    render(<ModalWindow client={client} />);

    fireEvent.click(await screen.findByRole("button", { name: "Acknowledge all (2)" }));
    await waitFor(() => expect(screen.getByText("Nothing to acknowledge.")).toBeTruthy());
    expect(await client.getModals()).toEqual([]);
  });
});
