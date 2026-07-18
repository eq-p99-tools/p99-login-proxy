import type { ReactNode } from "react";

interface StatusValueProps {
  label: string;
  value: ReactNode;
  tone?: "default" | "success" | "warning" | "error" | "muted";
}

export function StatusValue({ label, value, tone = "default" }: StatusValueProps) {
  return (
    <div className="status-value">
      <span className="status-value-label">{label}</span>
      <span className={`status-value-text tone-${tone}`}>{value}</span>
    </div>
  );
}
