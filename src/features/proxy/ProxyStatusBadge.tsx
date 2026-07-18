import type { ProxyLifecycle } from "../../ipc/schemas";

const LABELS: Record<ProxyLifecycle, string> = {
  stopped: "Stopped",
  starting: "Starting…",
  running: "Running",
  stopping: "Stopping…",
};

interface ProxyStatusBadgeProps {
  lifecycle: ProxyLifecycle | null | undefined;
  compact?: boolean;
}

export function ProxyStatusBadge({ lifecycle, compact = false }: ProxyStatusBadgeProps) {
  const state = lifecycle ?? "stopped";
  const label = LABELS[state];

  return (
    <span className={`status-badge status-${state}${compact ? " status-badge-compact" : ""}`}>
      <span className="status-dot" aria-hidden />
      {label}
    </span>
  );
}

interface EqConfigBadgeProps {
  enabled: boolean;
}

export function EqConfigBadge({ enabled }: EqConfigBadgeProps) {
  return (
    <span className={`status-badge status-${enabled ? "enabled" : "disabled"}`}>
      <span className="status-dot" aria-hidden />
      {enabled ? "Enabled" : "Disabled"}
    </span>
  );
}
