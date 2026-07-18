/** Matches `HEARTBEAT_INTERVAL` in `log_watcher.rs` (20s). */
export const HEARTBEAT_INTERVAL_MS = 20_000;

/** Log idle window before heartbeats stop (`LOG_IDLE_SECS` + small grace). */
export const HEARTBEAT_DEAD_MS = 35_000;

export type HeartbeatPhase = "alive" | "dead" | "idle";

export interface HeartbeatVisualState {
  phase: HeartbeatPhase;
  /** Opacity for idle/dead states; alive uses full opacity + brightness. */
  opacity: number;
  brightness: number;
  tooltip: string;
}

export function heartbeatVisualState(
  lastHeartbeatAtMs: number | null | undefined,
  nowMs: number,
  wsState: string | null | undefined,
  character: string | null | undefined,
): HeartbeatVisualState {
  const charLabel = character?.trim() ? character : "character";
  const wsLive = wsState === "connected" || wsState === "connecting";

  if (lastHeartbeatAtMs) {
    const elapsed = Math.max(0, nowMs - lastHeartbeatAtMs);
    const elapsedSecs = Math.round(elapsed / 1000);

    if (elapsed > HEARTBEAT_DEAD_MS) {
      return {
        phase: "dead",
        opacity: 0.28,
        brightness: 1,
        tooltip:
          `Heartbeat inactive (${elapsedSecs}s since last).\n` +
          `Last sent for ${charLabel} — character may be logged out or the EQ log is idle.`,
      };
    }

    const cycle = Math.min(1, elapsed / HEARTBEAT_INTERVAL_MS);
    const brightness = 0.25 + 0.75 * (1 - cycle);
    const nextSecs = Math.max(0, Math.round((HEARTBEAT_INTERVAL_MS - elapsed) / 1000));

    return {
      phase: "alive",
      opacity: 1,
      brightness,
      tooltip:
        `Character heartbeat for ${charLabel}.\n` +
        `Last sent ${elapsedSecs}s ago; next expected in ~${nextSecs}s.\n` +
        "Brightest right after each send, fading until the next heartbeat.",
    };
  }

  if (!wsLive) {
    return {
      phase: "idle",
      opacity: 0.28,
      brightness: 1,
      tooltip: "WebSocket not connected — character heartbeats are not being sent.",
    };
  }

  return {
    phase: "idle",
    opacity: 0.28,
    brightness: 1,
    tooltip:
      "Waiting for the first heartbeat. Sent every 20s while logged into EQ and the character log is updating.",
  };
}
