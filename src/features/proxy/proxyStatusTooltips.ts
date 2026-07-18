import type { ProxyLifecycle } from "../../ipc/schemas";
import { TOOLTIP_AFFIRMATIVE, TOOLTIP_NEGATIVE } from "../../components/tooltip";

const PROXY_LIFECYCLE_STATES: Record<ProxyLifecycle, string> = {
  stopped: "Stopped: UDP proxy is off; no login packets are intercepted.",
  starting: "Starting: Binding the listen socket and bringing the proxy online.",
  running: "Running: Listening on the configured UDP port and forwarding login traffic.",
  stopping: "Stopping: Shutting down the listener; new connections are not accepted.",
};

/** Forward lifecycle cycle: off → boot → active → shutdown → off. */
const PROXY_LIFECYCLE_ORDER: ProxyLifecycle[] = ["stopped", "starting", "running", "stopping"];

function proxyLifecycleOrderFrom(current: ProxyLifecycle): ProxyLifecycle[] {
  const start = PROXY_LIFECYCLE_ORDER.indexOf(current);
  return [...PROXY_LIFECYCLE_ORDER.slice(start), ...PROXY_LIFECYCLE_ORDER.slice(0, start)];
}

function eqCheckBlock(
  title: string,
  pass: boolean,
  passDetail: string,
  failDetail: string,
): string[] {
  const mark = pass ? TOOLTIP_AFFIRMATIVE : TOOLTIP_NEGATIVE;
  return [title, `${mark} ${pass ? passDetail : failDetail}`];
}

/** Multiline tooltip for the Proxy lifecycle badge (current state + all possibilities). */
export function proxyLifecycleTooltip(lifecycle: ProxyLifecycle | null | undefined): string {
  const state = lifecycle ?? "stopped";
  const lines = proxyLifecycleOrderFrom(state).map(
    (key) => `• ${PROXY_LIFECYCLE_STATES[key]}${key === state ? " (current)" : ""}`,
  );
  return lines.join("\n");
}

/** Multiline tooltip for the EQ Config badge (eqhost + eqclient.ini checks). */
export function eqConfigTooltip(
  enabled: boolean,
  eqhostProxyEnabled: boolean,
  eqclientLogEnabled: boolean,
): string {
  return [
    ...eqCheckBlock(
      "eqhost.txt",
      eqhostProxyEnabled,
      "Points at this proxy (localhost matches when the proxy binds 0.0.0.0).",
      "Points elsewhere, is missing, or no EverQuest directory is configured.",
    ),
    "",
    ...eqCheckBlock(
      "eqclient.ini — [Defaults] Log",
      eqclientLogEnabled,
      "Log=TRUE (character logging for heartbeat/location).",
      "Log is not TRUE or eqclient.ini is missing.",
    ),
    "",
    enabled
      ? `Enabled: both checks pass. (current)`
      : `Disabled: one or more checks failed. (current)`,
  ].join("\n");
}
