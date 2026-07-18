import type { ReactNode } from "react";

import { tooltipProps } from "./tooltip";

export type FormSpacing = "status" | "stats" | "settings" | "cache";

interface FormLayoutProps {
  children: ReactNode;
  spacing?: FormSpacing;
  className?: string;
}

export function FormLayout({ children, spacing = "settings", className = "" }: FormLayoutProps) {
  return (
    <div className={`form-layout spacing-${spacing} ${className}`.trim()}>{children}</div>
  );
}

interface FormRowProps {
  label: string;
  bold?: boolean;
  children: ReactNode;
  className?: string;
}

export function FormRow({ label, bold = false, children, className = "" }: FormRowProps) {
  return (
    <div className={`form-row ${className}`.trim()}>
      <span className={`form-row-label${bold ? " form-row-label-bold" : ""}`}>{label}</span>
      <div className="form-row-field">{children}</div>
    </div>
  );
}

interface FormValueProps {
  tone?: "default" | "success" | "warning" | "error" | "muted";
  title?: string;
  children: ReactNode;
}

export function FormValue({ tone = "default", title, children }: FormValueProps) {
  return (
    <span className={`form-value tone-${tone}`} {...tooltipProps(title)}>
      {children}
    </span>
  );
}
