import type { ReactNode } from "react";

interface GroupBoxProps {
  title: string;
  children: ReactNode;
  className?: string;
}

export function GroupBox({ title, children, className = "" }: GroupBoxProps) {
  return (
    <section className={`group-box ${className}`.trim()}>
      <h3 className="group-box-title">{title}</h3>
      <div className="group-box-body">{children}</div>
    </section>
  );
}
