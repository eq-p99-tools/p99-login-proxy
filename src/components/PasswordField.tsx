import { useCallback, useState, type InputHTMLAttributes, type KeyboardEvent, type PointerEvent } from "react";

import { PasswordVisibilityIcon } from "./PasswordVisibilityIcon";
import { tooltipProps } from "./tooltip";

type PasswordVisibilityMode = "toggle" | "hold";

interface PasswordFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: string;
  /** Toggle click vs press-and-hold to reveal (hold is safer for secrets on screen). */
  visibilityMode?: PasswordVisibilityMode;
  showTip?: string;
  hideTip?: string;
  holdTip?: string;
  tooltip?: string;
}

export function PasswordField({
  label,
  id,
  className = "",
  visibilityMode = "toggle",
  showTip = "Show password",
  hideTip = "Hide password",
  holdTip = "Hold to show password",
  tooltip,
  ...rest
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  const fieldId = id ?? `pw-${(label || "field").replace(/\s+/g, "-").toLowerCase()}`;

  const reveal = useCallback(() => setVisible(true), []);
  const conceal = useCallback(() => setVisible(false), []);

  const visibilityTip =
    visibilityMode === "hold"
      ? visible
        ? "Release to hide"
        : holdTip
      : visible
        ? hideTip
        : showTip;

  const onHoldPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    reveal();
  };

  const onHoldKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      reveal();
    }
  };

  const onHoldKeyUp = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      conceal();
    }
  };

  return (
    <label className={`password-field ${className}`.trim()} htmlFor={fieldId}>
      {label ? <span>{label}</span> : null}
      <span className="password-input-wrap">
        <input id={fieldId} type={visible ? "text" : "password"} {...tooltipProps(tooltip)} {...rest} />
        <button
          type="button"
          className="password-toggle"
          aria-label={visibilityTip}
          data-visibility-mode={visibilityMode}
          {...tooltipProps(visibilityTip)}
          {...(visibilityMode === "toggle"
            ? { onClick: () => setVisible((v) => !v) }
            : {
                onPointerDown: onHoldPointerDown,
                onPointerUp: conceal,
                onPointerLeave: conceal,
                onPointerCancel: conceal,
                onKeyDown: onHoldKeyDown,
                onKeyUp: onHoldKeyUp,
                onBlur: conceal,
                onContextMenu: (event) => event.preventDefault(),
              })}
        >
          <PasswordVisibilityIcon visible={visible} />
        </button>
      </span>
    </label>
  );
}
