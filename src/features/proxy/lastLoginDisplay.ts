const LOGIN_METHOD_LABELS: Record<string, string> = {
  sso: "SSO",
  local: "Local account alias",
  local_char: "Local character name",
  proxy_only: "Proxy only (passthrough)",
  skip_sso: "SSO skipped (passthrough)",
  passthrough: "Passthrough (no rewrite)",
};

export interface LastLoginDisplay {
  text: string;
  tooltip?: string;
}

/** Render Last Login from runtime stats (backend may embed alias → account in last_username). */
export function lastLoginDisplay(
  lastUsername: string | null | undefined,
  lastAccount: string | null | undefined,
  lastMethod: string | null | undefined,
): LastLoginDisplay {
  if (!lastUsername && !lastAccount) {
    return {
      text: "—",
      tooltip: "No login proxied yet.",
    };
  }

  const text = lastUsername ?? lastAccount ?? "—";
  const account = lastAccount ?? lastUsername ?? "";
  const typed = lastUsername?.includes(" → ")
    ? lastUsername.slice(0, lastUsername.indexOf(" → "))
    : (lastUsername ?? account);

  const methodLabel = lastMethod
    ? (LOGIN_METHOD_LABELS[lastMethod] ?? lastMethod)
    : null;

  let tooltip: string;
  if (typed && account && typed !== account) {
    tooltip = `Typed in EQ login screen: ${typed}\nSent to login server: ${account}`;
  } else {
    tooltip = `Login username (no rewrite): ${account || typed}`;
  }
  if (methodLabel) {
    tooltip += `\nRewrite method: ${methodLabel}`;
  }

  return { text, tooltip };
}
