import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MockClient } from "../../ipc/MockClient";
import type { LoginNotesEntry } from "../../ipc/schemas";
import { LoginNotesWindow } from "./LoginNotesWindow";

afterEach(() => cleanup());

function entry(overrides: Partial<LoginNotesEntry> = {}): LoginNotesEntry {
  return {
    id: 1,
    username: "zzzz",
    account: "realbot01",
    account_notes: "Shared bot; log out at bind",
    characters: [
      { name: "Zzzz", notes: "Kael factioned", typed: true },
      { name: "Alpha", notes: "Bound in Skyshrine", typed: false },
    ],
    received_at_ms: Date.UTC(2026, 10, 21, 18, 0, 0),
    ...overrides,
  };
}

describe("LoginNotesWindow", () => {
  it("shows account and character notes, flagging the typed character", async () => {
    const client = new MockClient();
    client.setMockLoginNotes([entry()]);
    render(<LoginNotesWindow client={client} />);

    expect(await screen.findByText("Shared bot; log out at bind")).toBeTruthy();
    expect(screen.getByText("Kael factioned")).toBeTruthy();
    expect(screen.getByText(/logged in as zzzz/)).toBeTruthy();
    expect(screen.getByText(/the name you logged in with/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeTruthy();
  });

  it("renders notes as plain text, never markup", async () => {
    const client = new MockClient();
    client.setMockLoginNotes([entry({ account_notes: "<img src=x onerror=alert(1)>", characters: [] })]);
    const { container } = render(<LoginNotesWindow client={client} />);

    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
  });

  it("acknowledges every pending login at once", async () => {
    const client = new MockClient();
    client.setMockLoginNotes([entry({ id: 2, account: "otherbot", username: "otherbot" }), entry()]);
    render(<LoginNotesWindow client={client} />);

    fireEvent.click(await screen.findByRole("button", { name: "Acknowledge all (2)" }));
    await waitFor(() => expect(screen.getByText("No unacknowledged login notes.")).toBeTruthy());
    expect(await client.getLoginNotes()).toEqual([]);
  });
});
