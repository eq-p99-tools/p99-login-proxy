import { describe, expect, it } from "vitest";

import { TOOLTIP_AFFIRMATIVE, TOOLTIP_NEGATIVE } from "../../components/tooltip";
import { eqConfigTooltip, proxyLifecycleTooltip } from "./proxyStatusTooltips";

describe("proxyLifecycleTooltip", () => {
  it("lists every lifecycle state and marks the current one", () => {
    const tip = proxyLifecycleTooltip("running");
    expect(tip).not.toContain("Proxy lifecycle");
    expect(tip).toContain("Stopped:");
    expect(tip).toContain("Starting:");
    expect(tip).toContain("Running:");
    expect(tip).toContain("Stopping:");
    expect(tip).toContain("(current)");
    expect(tip.match(/\(current\)/g)).toHaveLength(1);
    expect(tip).toContain("Running: Listening");
  });

  it("defaults missing lifecycle to stopped", () => {
    const tip = proxyLifecycleTooltip(undefined);
    expect(tip).toContain("Stopped: UDP proxy is off");
    expect(tip).toContain("(current)");
    expect(tip.match(/\(current\)/g)).toHaveLength(1);
  });

  it("orders states forward from the current state in the lifecycle cycle", () => {
    const stopped = proxyLifecycleTooltip("stopped");
    expect(stopped.indexOf("Stopped:")).toBeLessThan(stopped.indexOf("Starting:"));
    expect(stopped.indexOf("Starting:")).toBeLessThan(stopped.indexOf("Running:"));
    expect(stopped.indexOf("Running:")).toBeLessThan(stopped.indexOf("Stopping:"));

    const running = proxyLifecycleTooltip("running");
    expect(running.indexOf("Running:")).toBeLessThan(running.indexOf("Stopping:"));
    expect(running.indexOf("Stopping:")).toBeLessThan(running.indexOf("Stopped:"));
    expect(running.indexOf("Stopped:")).toBeLessThan(running.indexOf("Starting:"));
  });
});

describe("eqConfigTooltip", () => {
  it("lists both checks and marks overall enabled when both pass", () => {
    const tip = eqConfigTooltip(true, true, true);
    expect(tip).not.toContain("EQ Config");
    expect(tip.startsWith("eqhost.txt")).toBe(true);
    expect(tip).toContain(`eqclient.ini — [Defaults] Log\n${TOOLTIP_AFFIRMATIVE}`);
    expect(tip).toContain("Enabled: both checks pass. (current)");
    expect(tip.match(/\(current\)/g)).toHaveLength(1);
  });

  it("shows which check failed when overall disabled", () => {
    const eqhostOnly = eqConfigTooltip(false, true, false);
    expect(eqhostOnly).toContain(`eqhost.txt\n${TOOLTIP_AFFIRMATIVE}`);
    expect(eqhostOnly).toContain(`eqclient.ini — [Defaults] Log\n${TOOLTIP_NEGATIVE}`);
    expect(eqhostOnly).toContain("Disabled: one or more checks failed. (current)");

    const logOnly = eqConfigTooltip(false, false, true);
    expect(logOnly).toContain(`eqhost.txt\n${TOOLTIP_NEGATIVE}`);
    expect(logOnly).toContain(`eqclient.ini — [Defaults] Log\n${TOOLTIP_AFFIRMATIVE}`);
  });
});
