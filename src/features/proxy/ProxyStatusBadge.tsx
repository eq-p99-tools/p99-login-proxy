import type { ProxyLifecycle } from "../../ipc/schemas";
import { tooltipProps } from "../../components/tooltip";
import { eqConfigTooltip, proxyLifecycleTooltip } from "./proxyStatusTooltips";

const LABELS: Record<ProxyLifecycle, string> = {
  stopped: "Stopped",
  starting: "Starting",
  running: "Running",
  stopping: "Stopping",
};

interface ProxyStatusBadgeProps {
  lifecycle: ProxyLifecycle | null | undefined;
  compact?: boolean;
}

export function ProxyStatusBadge({ lifecycle, compact = false }: ProxyStatusBadgeProps) {
  const state = lifecycle ?? "stopped";
  const label = LABELS[state];

  return (
    <span
      className={`status-badge status-${state}${compact ? " status-badge-compact" : ""}`}
      {...tooltipProps(proxyLifecycleTooltip(state))}
    >
      <span className="status-dot" aria-hidden />
      {label}
    </span>
  );
}

interface EqConfigBadgeProps {
  enabled: boolean;
  eqhostProxyEnabled?: boolean;
  eqclientLogEnabled?: boolean;
}

export function EqConfigBadge({
  enabled,
  eqhostProxyEnabled = enabled,
  eqclientLogEnabled = enabled,
}: EqConfigBadgeProps) {
  return (
    <span
      className={`status-badge status-${enabled ? "enabled" : "disabled"}`}
      {...tooltipProps(eqConfigTooltip(enabled, eqhostProxyEnabled, eqclientLogEnabled))}
    >
      <span className="status-dot" aria-hidden />
      {enabled ? "Enabled" : "Disabled"}
    </span>
  );
}
