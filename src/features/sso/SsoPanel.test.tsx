import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AppProviders } from "../../app/AppProviders";
import { SsoPanel } from "./SsoPanel";
import { MockClient } from "../../ipc/MockClient";

afterEach(() => cleanup());

describe("SsoPanel", () => {
  it("handles null account_tree without crashing", async () => {
    const client = new MockClient();
    client.setMockAccounts({ account_tree: null as unknown as Record<string, unknown>, account_count: 0 });
    render(
      <AppProviders client={client}>
        <SsoPanel />
      </AppProviders>,
    );
    expect(await screen.findByText(/SSO Accounts:/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Characters" })).toBeTruthy();
  });

  it("shows search on accounts subtab", async () => {
    const client = new MockClient();
    render(
      <AppProviders client={client}>
        <SsoPanel />
      </AppProviders>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));
    expect(await screen.findByPlaceholderText("Type to filter...")).toBeTruthy();
  });

  it("shows local account CRUD buttons on local accounts subtab", async () => {
    const client = new MockClient();
    render(
      <AppProviders client={client}>
        <SsoPanel />
      </AppProviders>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Local Accounts" }));
    expect(await screen.findByRole("button", { name: "Add Account" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit Account" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete Account" })).toBeTruthy();
  });
});
