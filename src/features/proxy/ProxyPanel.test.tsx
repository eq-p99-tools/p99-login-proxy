import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AppProviders } from "../../app/AppProviders";
import { AppShell } from "../../app/AppShell";
import { ProxyPanel } from "./ProxyPanel";
import { MockClient } from "../../ipc/MockClient";

afterEach(() => cleanup());

describe("ProxyPanel", () => {
  it("renders listen endpoint from mock client", async () => {
    const client = new MockClient();
    render(
      <AppProviders client={client}>
        <ProxyPanel />
      </AppProviders>,
    );
    expect(await screen.findByText("127.0.0.1:6998")).toBeTruthy();
  });

  it("allows editing the listen port on double-click", async () => {
    const client = new MockClient();
    render(
      <AppProviders client={client}>
        <ProxyPanel />
      </AppProviders>,
    );
    await screen.findByText("127.0.0.1:6998");
    fireEvent.doubleClick(screen.getByText("127.0.0.1:6998"));
    const input = screen.getByLabelText("Listen port") as HTMLInputElement;
    expect(input.value).toBe("6998");
    fireEvent.change(input, { target: { value: "6790" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => {
      expect(screen.getByText("127.0.0.1:6790")).toBeTruthy();
    });
  });

  it("uses three-state proxy mode selector", async () => {
    const client = new MockClient();
    render(
      <AppProviders client={client}>
        <ProxyPanel />
      </AppProviders>,
    );
    await screen.findByText("127.0.0.1:6998");
    const select = screen.getByLabelText("Proxy Mode");
    fireEvent.change(select, { target: { value: "enabled_sso" } });
    await waitFor(() => {
      expect((select as HTMLSelectElement).value).toBe("enabled_sso");
    });
  });

  it("offers dark, light, system, and EverQuest theme modes", async () => {
    const client = new MockClient();
    render(
      <AppProviders client={client}>
        <ProxyPanel />
      </AppProviders>,
    );
    await screen.findByText("127.0.0.1:6998");
    const select = screen.getByLabelText("Theme") as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.text)).toEqual([
      "System Default",
      "Qeynos Harbor",
      "Nektulos Forest",
      "Gnomish Terminal",
      "Iceclad Ocean",
      "Kelethin Treetops",
      "Lavastorm Mountains",
      "Paineel Undercity",
      "Erudin Library",
    ]);
    expect(select.value).toBe("system");
    fireEvent.change(select, { target: { value: "iceclad" } });
    await waitFor(() => expect(select.value).toBe("iceclad"));
  });

  it("uses Python-style form labels", async () => {
    const client = new MockClient();
    render(
      <AppProviders client={client}>
        <ProxyPanel />
      </AppProviders>,
    );
    await screen.findByText("127.0.0.1:6998");
    expect(screen.getByText("Total Connections:")).toBeTruthy();
    expect(screen.getByText("SSO API:")).toBeTruthy();
    expect(screen.getByText("API Token:")).toBeTruthy();
    expect(screen.getByLabelText("Launch on system login")).toBeTruthy();
  });

  it("toggles launch on system login through the desktop client", async () => {
    const client = new MockClient();
    render(
      <AppProviders client={client}>
        <ProxyPanel />
      </AppProviders>,
    );
    await screen.findByText("127.0.0.1:6998");
    const checkbox = screen.getByLabelText("Launch on system login") as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
    fireEvent.click(checkbox);
    await waitFor(() => expect(checkbox.checked).toBe(true));
    expect(await client.getLaunchAtLogin()).toBe(true);
    fireEvent.click(checkbox);
    await waitFor(() => expect(checkbox.checked).toBe(false));
    expect(await client.getLaunchAtLogin()).toBe(false);
  });

  it("shows SSO accounts summary from account tree", async () => {
    const client = new MockClient();
    client.setMockAccounts({
      account_tree: {
        main: {
          aliases: ["alt1"],
          tags: ["tag1"],
          characters: { CharOne: {}, CharTwo: {} },
        },
      },
      account_count: 1,
    });
    render(
      <AppProviders client={client}>
        <ProxyPanel />
      </AppProviders>,
    );
    expect(await screen.findByText("1 accounts, 2 characters, 2 aliases/tags")).toBeTruthy();
  });

  it("shows SSO logged-in count from recent account activity", async () => {
    const client = new MockClient();
    client.setMockAccounts({
      account_tree: {
        main: {
          characters: { CharOne: {} },
          last_login: new Date().toISOString(),
          last_login_by: "alice",
          active_character: "CharOne",
        },
        idle: {
          characters: { CharTwo: {} },
          last_login: "2020-01-01T00:00:00Z",
        },
      },
      account_count: 2,
    });
    render(
      <AppProviders client={client}>
        <ProxyPanel />
      </AppProviders>,
    );
    expect(await screen.findByText("1 character")).toBeTruthy();
  });
});

describe("AppShell smoke", () => {
  it("renders default top-level tabs without error", async () => {
    render(
      <AppProviders>
        <AppShell />
      </AppProviders>,
    );
    for (const label of ["Proxy", "SSO", "Advanced", "Log", "Changelog"]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(screen.getByRole("navigation", { name: /main/i })).toBeTruthy();
    }
    expect(screen.queryByRole("button", { name: "Debug" })).toBeNull();
    expect(screen.getByRole("button", { name: /launch everquest/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /exit/i })).toBeTruthy();
  });

  it("reveals Debug tab after the Advanced-tab easter egg", async () => {
    render(
      <AppProviders>
        <AppShell />
      </AppProviders>,
    );
    const advanced = screen.getByRole("button", { name: "Advanced" });
    for (let i = 0; i < 7; i += 1) {
      fireEvent.click(advanced);
    }
    const debug = await screen.findByRole("button", { name: "Debug" });
    fireEvent.click(debug);
    expect(screen.getByRole("navigation", { name: /main/i })).toBeTruthy();
  });

  it("spans footer Launch and Exit across the row like the Qt app", () => {
    const { container } = render(
      <AppProviders>
        <AppShell />
      </AppProviders>,
    );
    const actions = container.querySelector(".footer-actions");
    expect(actions).toBeTruthy();
    const buttons = actions?.querySelectorAll("button");
    expect(buttons?.length).toBe(2);
    expect(buttons?.[0]?.textContent).toMatch(/Launch EverQuest/i);
    expect(buttons?.[1]?.textContent).toMatch(/Exit/i);
  });

  it("sets document title from bootstrap version", async () => {
    render(
      <AppProviders>
        <AppShell />
      </AppProviders>,
    );
    await waitFor(() => {
      expect(document.title).toBe("P99 Login Proxy v0.1.0-mock");
    });
  });
});
