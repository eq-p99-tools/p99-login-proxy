export type NavTab = "proxy" | "sso" | "advanced" | "logs" | "changelog" | "extras";

/** Top-level tabs shown in normal use (Extras is easter-egg only). */
export const NAV_TABS: { id: NavTab; label: string }[] = [
  { id: "proxy", label: "Proxy" },
  { id: "sso", label: "SSO" },
  { id: "advanced", label: "Advanced" },
  { id: "logs", label: "Log" },
  { id: "changelog", label: "Changelog" },
];

export const EXTRAS_NAV_TAB = { id: "extras" as const, label: "Extras" };

export function visibleNavTabs(easterEggMode: boolean): { id: NavTab; label: string }[] {
  return easterEggMode ? [...NAV_TABS, EXTRAS_NAV_TAB] : NAV_TABS;
}

export type SsoSubTab =
  | "characters"
  | "accounts"
  | "aliases"
  | "tags"
  | "local-accounts"
  | "local-characters";

export const SSO_SUB_TABS: { id: SsoSubTab; label: string }[] = [
  { id: "characters", label: "Characters" },
  { id: "accounts", label: "Accounts" },
  { id: "aliases", label: "Aliases" },
  { id: "tags", label: "Tags" },
  { id: "local-accounts", label: "Local Accounts" },
  { id: "local-characters", label: "Local Characters" },
];
