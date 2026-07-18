import { useState, type InputHTMLAttributes } from "react";

import { PasswordVisibilityIcon } from "./PasswordVisibilityIcon";
import { tooltipProps } from "./tooltip";

interface PasswordFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: string;
  showTip?: string;
  hideTip?: string;
  tooltip?: string;
}

export function PasswordField({
  label,
  id,
  className = "",
  showTip = "Show password",
  hideTip = "Hide password",
  tooltip,
  ...rest
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  const fieldId = id ?? `pw-${(label || "field").replace(/\s+/g, "-").toLowerCase()}`;
  const visibilityTip = visible ? hideTip : showTip;
  return (
    <label className={`password-field ${className}`.trim()} htmlFor={fieldId}>
      {label ? <span>{label}</span> : null}
      <span className="password-input-wrap">
        <input id={fieldId} type={visible ? "text" : "password"} {...tooltipProps(tooltip)} {...rest} />
        <button
          type="button"
          className="password-toggle"
          aria-label={visibilityTip}
          {...tooltipProps(visibilityTip)}
          onClick={() => setVisible((v) => !v)}
        >
          <PasswordVisibilityIcon visible={visible} />
        </button>
      </span>
    </label>
  );
}
