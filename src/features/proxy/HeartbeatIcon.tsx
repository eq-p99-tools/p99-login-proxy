import { useEffect, useMemo, useState } from "react";

import { tooltipProps } from "../../components/tooltip";
import { heartbeatVisualState } from "./heartbeatVisual";

interface HeartbeatIconProps {
  lastHeartbeatAtMs: number | null | undefined;
  character: string | null | undefined;
  wsState: string | null | undefined;
}

export function HeartbeatIcon({
  lastHeartbeatAtMs,
  character,
  wsState,
}: HeartbeatIconProps) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [tooltipNowMs, setTooltipNowMs] = useState(() => Date.now());

  useEffect(() => {
    const fast = window.setInterval(() => setNowMs(Date.now()), 100);
    const slow = window.setInterval(() => setTooltipNowMs(Date.now()), 1000);
    return () => {
      window.clearInterval(fast);
      window.clearInterval(slow);
    };
  }, []);

  useEffect(() => {
    if (lastHeartbeatAtMs) {
      const ts = Date.now();
      setNowMs(ts);
      setTooltipNowMs(ts);
    }
  }, [lastHeartbeatAtMs]);

  const visual = useMemo(
    () => heartbeatVisualState(lastHeartbeatAtMs, nowMs, wsState, character),
    [lastHeartbeatAtMs, nowMs, wsState, character],
  );

  const tooltipVisual = useMemo(
    () => heartbeatVisualState(lastHeartbeatAtMs, tooltipNowMs, wsState, character),
    [lastHeartbeatAtMs, tooltipNowMs, wsState, character],
  );

  return (
    <span
      className="heartbeat-icon-wrap"
      aria-label={tooltipVisual.tooltip}
      {...tooltipProps(tooltipVisual.tooltip)}
    >
      <span
        className={`heartbeat-icon heartbeat-${visual.phase}`}
        style={{
          opacity: visual.opacity,
          filter: visual.phase === "alive" ? `brightness(${visual.brightness})` : undefined,
        }}
        aria-hidden
      >
        <svg viewBox="0 0 16 16" width="14" height="14" focusable="false" aria-hidden>
          <path
            fill="currentColor"
            d="M8 13.5 2.2 7.7a3.1 3.1 0 0 1 0-4.4 3.1 3.1 0 0 1 4.4 0L8 4.7l1.4-1.4a3.1 3.1 0 0 1 4.4 0 3.1 3.1 0 0 1 0 4.4L8 13.5Z"
          />
        </svg>
      </span>
    </span>
  );
}
