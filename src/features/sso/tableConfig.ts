/** Fixed column widths matching Python ui.py table definitions. */

export const SSO_CHARACTER_WIDTHS = {
  readiness: 26,
  name: 106,
  class: 74,
  level: 30,
  st: 26,
  vp: 26,
  seb: 26,
  ct: 26,
  th: 26,
  ch: 26,
  park: 136,
  bind: 136,
  loggedInBy: 98,
  account: 100,
  roles: 160,
} as const;

const KEY_CELL_LEGEND = "🟢 = has key, ? = unknown, blank = no key.";

const CHARACTER_COLUMN_TOOLTIPS_BASE = [
  "Readiness (class-specific). Empty if no rule set for this class.",
  "Character name",
  "Class",
  "Level",
  "Sleeper's Key (ST). " + KEY_CELL_LEGEND + " Search: stkey",
  "Key of Veeshan (VP). " + KEY_CELL_LEGEND + " Search: vpkey",
  "Trakanon Idol (Seb). " + KEY_CELL_LEGEND + " Search: sebkey",
  "Lizard Blood Potion (CT). 🟢 Lots / 🟡 Some / 🔴 Few / ? — unknown count. Hover for count when known. Search: lizpot, ctpot = rows with a known count.",
  "Vial of Velium Vapors (Thurg pot, Th). 🟢 = has vial, ? = unknown, blank = no vial. Search: thurgpot, dainpot",
  "CH bundle: 🟢 full bundle · 🟡 partial · blank if no necklace or unknown. Hover for Necklace/Void/MB4. Search chneck = rows with necklace (🟢 or 🟡).",
  "Park location (current zone)",
  "Bind location",
] as const;

/** Column header tooltips — mirrors Python ``_CHARACTERS_COLUMN_HEADER_TOOLTIPS``. */
export const SSO_CHARACTER_HEADER_TOOLTIPS = [
  ...CHARACTER_COLUMN_TOOLTIPS_BASE,
  "Logged in by (last SSO user on this character)",
  "Account name (SSO)",
  "Discord roles whose SSO groups grant access to this account.",
] as const;

/** Column header tooltips — mirrors Python ``_LOCAL_CHARACTERS_COLUMN_HEADER_TOOLTIPS``. */
export const CHARACTER_HEADER_TOOLTIPS = [
  ...CHARACTER_COLUMN_TOOLTIPS_BASE,
  "Account name (local — free-form; may or may not match a row in local_accounts.csv)",
] as const;

export const KEYS_GROUP_HEADER_TOOLTIP = [
  "ST — Sleeper's Key",
  KEY_CELL_LEGEND,
  "Search: stkey",
  "",
  "VP — Key of Veeshan",
  KEY_CELL_LEGEND,
  "Search: vpkey",
  "",
  "Seb — Trakanon Idol",
  KEY_CELL_LEGEND,
  "Search: sebkey",
].join("\n");

export const POTS_GROUP_HEADER_TOOLTIP = [
  "CT — Lizard Blood Potion",
  "Tier emojis: 🟢 Lots, 🟡 Some, 🔴 Few — ? if count unknown (thresholds in count_display).",
  "Hover a cell for the exact stack count.",
  "Search: lizpot, ctpot (rows with a known count).",
  "",
  "Th — Vial of Velium Vapors (Thurg)",
  "🟢 = has vial, ? = unknown, blank = no vial.",
  "Search: thurgpot, dainpot",
].join("\n");

export const SSO_CHARACTER_GROUP_HEADER = [
  { label: "", colSpan: 4 },
  { label: "Keys", colSpan: 3, title: KEYS_GROUP_HEADER_TOOLTIP },
  { label: "Pots", colSpan: 2, title: POTS_GROUP_HEADER_TOOLTIP },
  { label: "", colSpan: 6 },
] as const;

export const SSO_ACCOUNT_WIDTHS = { name: 114, aliases: 220, tags: 140, roles: 160 } as const;
export const SSO_ALIAS_WIDTHS = { alias: 100, account: 114 } as const;
export const SSO_TAG_WIDTHS = { tag: 100, accounts: 514 } as const;
export const LOCAL_ACCOUNT_WIDTHS = { name: 114, aliases: 500 } as const;
export const LOCAL_CHARACTER_WIDTHS = {
  readiness: 26,
  name: 106,
  class: 74,
  level: 30,
  st: 26,
  vp: 26,
  seb: 26,
  ct: 26,
  th: 26,
  ch: 26,
  park: 136,
  bind: 136,
  account: 120,
} as const;

export const LOCAL_CHARACTER_GROUP_HEADER = [
  { label: "", colSpan: 4 },
  { label: "Keys", colSpan: 3, title: KEYS_GROUP_HEADER_TOOLTIP },
  { label: "Pots", colSpan: 2, title: POTS_GROUP_HEADER_TOOLTIP },
  { label: "", colSpan: 4 },
] as const;
