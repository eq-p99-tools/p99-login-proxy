import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AppProviders } from "../../app/AppProviders";
import { AdvancedPanel } from "../advanced/AdvancedPanel";
import { ChangelogPanel } from "../changelog/ChangelogPanel";
import { LogsPanel } from "../logs/LogsPanel";

afterEach(() => cleanup());

describe("AdvancedPanel layout", () => {
  it("renders EverQuest Configuration group", async () => {
    render(
      <AppProviders>
        <AdvancedPanel />
      </AppProviders>,
    );
    expect(await screen.findByText("EverQuest Configuration")).toBeTruthy();
    expect(screen.getByText("EverQuest Path:")).toBeTruthy();
    expect(screen.getByText("eqhost.txt Path:")).toBeTruthy();
    expect(screen.getByText("eqhost.txt (current):")).toBeTruthy();
  });
});

describe("LogsPanel layout", () => {
  it("renders log toolbar controls", async () => {
    render(
      <AppProviders>
        <LogsPanel />
      </AppProviders>,
    );
    expect(screen.getByLabelText(/auto-scroll/i)).toBeTruthy();
    expect(screen.getByLabelText(/word wrap/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Clear" })).toBeTruthy();
  });
});

describe("ChangelogPanel layout", () => {
  it("renders Version History group", async () => {
    render(
      <AppProviders>
        <ChangelogPanel />
      </AppProviders>,
    );
    expect(await screen.findByText("Version History")).toBeTruthy();
  });
});
