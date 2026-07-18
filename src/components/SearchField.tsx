import type { InputHTMLAttributes } from "react";

interface SearchFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: string;
}

export function SearchField({ label = "Type to filter...", className = "", ...rest }: SearchFieldProps) {
  return (
    <label className={`search-field ${className}`.trim()}>
      <span className="sr-only">{label}</span>
      <input type="search" placeholder={label} aria-label={label} {...rest} />
    </label>
  );
}
