import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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

  it("sorts SSO accounts by every displayed column", async () => {
    const client = new MockClient();
    client.setMockAccounts({
      account_tree: {
        zeta: { aliases: ["Second"], tags: ["Alpha"], group_roles: ["Member"] },
        alpha: { aliases: ["First"], tags: ["Zulu"], group_roles: ["Officer"] },
      },
      account_count: 2,
    });
    render(
      <AppProviders client={client}>
        <SsoPanel />
      </AppProviders>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));
    const table = await screen.findByRole("table");
    const accountRows = () => within(table).getAllByRole("row").slice(1);

    expect(accountRows()[0].textContent).toContain("alpha");
    fireEvent.click(within(table).getByRole("button", { name: "Tags" }));
    expect(accountRows()[0].textContent).toContain("zeta");
    fireEvent.click(within(table).getByRole("button", { name: /Tags/ }));
    expect(accountRows()[0].textContent).toContain("alpha");

    for (const header of ["Account Name", "Aliases", "Access Roles"]) {
      expect(within(table).getByRole("button", { name: new RegExp(header) })).toBeTruthy();
    }
  });

  it("flags cached SSO data as stale, but not on the local subtabs", async () => {
    const client = new MockClient();
    client.setMockAccounts({
      account_tree: { alpha: { aliases: [], tags: [] } },
      account_count: 1,
      stale: true,
    });
    render(
      <AppProviders client={client}>
        <SsoPanel />
      </AppProviders>,
    );

    expect(await screen.findByText(/Not connected to the SSO service/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Local Accounts" }));
    expect(screen.queryByText(/Not connected to the SSO service/i)).toBeNull();
  });

  it("omits the stale notice while connected", async () => {
    const client = new MockClient();
    client.setMockAccounts({
      account_tree: { alpha: { aliases: [], tags: [] } },
      account_count: 1,
    });
    render(
      <AppProviders client={client}>
        <SsoPanel />
      </AppProviders>,
    );

    expect(await screen.findByText(/SSO Accounts:/i)).toBeTruthy();
    expect(screen.queryByText(/Not connected to the SSO service/i)).toBeNull();
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
