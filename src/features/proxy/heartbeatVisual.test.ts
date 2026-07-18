import { describe, expect, it } from "vitest";

import {
  HEARTBEAT_DEAD_MS,
  HEARTBEAT_INTERVAL_MS,
  heartbeatVisualState,
} from "./heartbeatVisual";

describe("heartbeatVisualState", () => {
  const now = 1_000_000;

  it("is idle when websocket is disconnected and no heartbeat yet", () => {
    const state = heartbeatVisualState(null, now, "disconnected", "Alice");
    expect(state.phase).toBe("idle");
    expect(state.opacity).toBeLessThan(0.35);
  });

  it("animates from recent heartbeat even if ws state is stale", () => {
    const state = heartbeatVisualState(now, now, "disconnected", "Alice");
    expect(state.phase).toBe("alive");
    expect(state.brightness).toBeCloseTo(1, 2);
    expect(state.opacity).toBe(1);
  });

  it("starts bright and fades toward 25% brightness over the interval", () => {
    const atSend = heartbeatVisualState(now, now, "connected", "Alice");
    expect(atSend.phase).toBe("alive");
    expect(atSend.brightness).toBeCloseTo(1, 2);

    const midCycle = heartbeatVisualState(
      now - HEARTBEAT_INTERVAL_MS / 2,
      now,
      "connected",
      "Alice",
    );
    expect(midCycle.brightness).toBeCloseTo(0.625, 1);

    const endCycle = heartbeatVisualState(now - HEARTBEAT_INTERVAL_MS, now, "connected", "Alice");
    expect(endCycle.brightness).toBeCloseTo(0.25, 2);
  });

  it("marks dead after the idle window", () => {
    const state = heartbeatVisualState(now - HEARTBEAT_DEAD_MS - 1, now, "connected", "Alice");
    expect(state.phase).toBe("dead");
    expect(state.opacity).toBeLessThan(0.35);
  });
});
