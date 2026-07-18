/** Pure helpers for the SSO Characters table — mirrors Python count_display / readiness_by_class / ui.py. */

import { zoneKeyToDisplay } from "./zoneTranslate";
import { TOOLTIP_AFFIRMATIVE, TOOLTIP_NEGATIVE } from "../../components/tooltip";

export { TOOLTIP_AFFIRMATIVE, TOOLTIP_NEGATIVE };

export const TIER_EMOJI_LOTS = "\u{1F7E2}"; // 🟢
export const TIER_EMOJI_SOME = "\u{1F7E1}"; // 🟡
export const TIER_EMOJI_FEW = "\u{1F534}"; // 🔴
export const READINESS_UNKNOWN_MARK = "?";
export const KEY_COLUMN_YES = TIER_EMOJI_LOTS;
export const KEY_COLUMN_UNKNOWN = READINESS_UNKNOWN_MARK;
export const ACTIVITY_FADE_SECONDS = 90;

export const COUNT_TIER_THRESHOLDS: Readonly<Record<string, readonly [number, number]>> = {
  lizard: [1, 2],
  pearl: [20, 60],
  peridot: [20, 60],
  mb3: [3, 6],
  mb4: [1, 2],
  mb5: [1, 2],
};

const TIER_SORT_RANK: Readonly<Record<string, number>> = {
  [TIER_EMOJI_LOTS]: 0,
  [TIER_EMOJI_SOME]: 1,
  [TIER_EMOJI_FEW]: 2,
  [READINESS_UNKNOWN_MARK]: 3,
  "": 4,
};

const READINESS_COLUMN_SORT_RANK: Readonly<Record<string, number>> = {
  [TIER_EMOJI_LOTS]: 0,
  [TIER_EMOJI_SOME]: 1,
  [READINESS_UNKNOWN_MARK]: 2,
  [TIER_EMOJI_FEW]: 3,
  "": 4,
};

const KEY_SORT_ORDER: Readonly<Record<string, number>> = {
  [KEY_COLUMN_YES]: 0,
  [KEY_COLUMN_UNKNOWN]: 1,
  "": 2,
};

const CLASS_SHORT: Readonly<Record<string, string>> = {
  Necromancer: "Necro",
  ShadowKnight: "SK",
};

/** Special search keywords → column id (matches Python _KEY_FILTER_TERMS). */
export const KEY_FILTER_TERMS: Readonly<Record<string, CharacterSortKey>> = {
  stkey: "st",
  vpkey: "vp",
  sebkey: "seb",
  lizpot: "ct",
  ctpot: "ct",
  thurgpot: "th",
  dainpot: "th",
  chneck: "ch",
};

/** Columns excluded from generic substring search (logged in by, account). */
export const SEARCH_SKIP_KEYS: ReadonlySet<CharacterSortKey> = new Set(["loggedInBy", "account"]);

/** Columns where blanks sort last regardless of direction. */
export const SORT_BLANKS_LAST_KEYS: ReadonlySet<CharacterSortKey> = new Set(["loggedInBy"]);

const KEY_SORT_KEYS: ReadonlySet<CharacterSortKey> = new Set(["st", "vp", "seb", "th"]);

export type CharacterSortKey =
  | "readiness"
  | "name"
  | "class"
  | "level"
  | "st"
  | "vp"
  | "seb"
  | "ct"
  | "th"
  | "ch"
  | "park"
  | "bind"
  | "loggedInBy"
  | "account";

export interface CharacterItems {
  st?: boolean | number | null;
  vp?: boolean | number | null;
  seb?: boolean | number | null;
  lizard?: boolean | number | null;
  thurg?: boolean | null;
  neck?: boolean | null;
  void?: boolean | null;
  mb3?: boolean | number | null;
  mb4?: boolean | number | null;
  pearl?: boolean | number | null;
  peridot?: boolean | number | null;
  mb5?: boolean | number | null;
  reaper?: boolean | null;
  brass_idol?: boolean | null;
}

export interface CharacterEntry {
  bind?: string | null;
  park?: string | null;
  class?: string | null;
  level?: number | null;
  items?: CharacterItems | null;
}

export interface AccountTreeEntry {
  aliases?: string[];
  tags?: string[];
  characters?: Record<string, CharacterEntry>;
  last_login?: number | string | null;
  last_login_by?: string;
  active_character?: string;
}

export type AccountTree = Record<string, AccountTreeEntry>;

export interface CharacterRow {
  readiness: string;
  name: string;
  class: string;
  classRaw: string | null;
  level: string;
  st: string;
  vp: string;
  seb: string;
  ct: string;
  th: string;
  ch: string;
  park: string;
  bind: string;
  loggedInBy: string;
  account: string;
  lastLogin: number | string | null;
  isBlocked: boolean;
  ctTooltip: string;
  chTooltip: string;
  readinessTooltip: string;
}

export interface FlattenCharactersOptions {
  /** Resolve zone keys to display names; defaults to raw key or "Unknown". */
  zoneKeyToName?: (key: string | null | undefined) => string;
  /** Clock override for deterministic activity-TTL tests. */
  nowMs?: number;
}

export interface SortCharactersOptions {
  key: CharacterSortKey;
  ascending?: boolean;
}

export interface SearchCharactersOptions {
  /** Extra columns to skip in generic substring search. */
  skipKeys?: ReadonlySet<CharacterSortKey>;
}

function normalizeStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  return value.filter((v): v is string => typeof v === "string");
}

function normalizeItems(raw: unknown): CharacterItems | undefined {
  if (raw == null || typeof raw !== "object" || Array.isArray(raw)) {
    return undefined;
  }
  return raw as CharacterItems;
}

function normalizeCharactersMap(raw: unknown): Record<string, CharacterEntry> | undefined {
  if (raw == null || typeof raw !== "object" || Array.isArray(raw)) {
    return undefined;
  }
  const out: Record<string, CharacterEntry> = {};
  for (const [name, entryRaw] of Object.entries(raw)) {
    if (entryRaw == null || typeof entryRaw !== "object" || Array.isArray(entryRaw)) {
      out[name] = {};
      continue;
    }
    const e = entryRaw as Record<string, unknown>;
    out[name] = {
      bind: typeof e.bind === "string" ? e.bind : e.bind == null ? null : undefined,
      park: typeof e.park === "string" ? e.park : e.park == null ? null : undefined,
      class: typeof e.class === "string" ? e.class : e.class == null ? null : undefined,
      level: typeof e.level === "number" ? e.level : e.level == null ? null : undefined,
      items: normalizeItems(e.items),
    };
  }
  return out;
}

/** SSO account cache summary — mirrors Python ``update_account_cache_display``. */
export function ssoAccountsSummary(tree: AccountTree): { text: string; tone: "success" | "muted" } {
  const normalized = normalizeAccountTree(tree);
  const realAccounts = Object.keys(normalized).length;
  if (realAccounts === 0) {
    return { text: "None", tone: "muted" };
  }

  let totalCharacters = 0;
  let totalAliases = 0;
  const uniqueTags = new Set<string>();
  for (const data of Object.values(normalized)) {
    totalCharacters += Object.keys(data.characters ?? {}).length;
    totalAliases += (data.aliases ?? []).length;
    for (const tag of data.tags ?? []) {
      uniqueTags.add(tag);
    }
  }

  return {
    text: `${realAccounts} accounts, ${totalCharacters} characters, ${totalAliases + uniqueTags.size} aliases/tags`,
    tone: "success",
  };
}

/** One actively logged-in SSO character (not blocked alts on the same account). */
export interface SsoLoggedInEntry {
  account: string;
  character: string;
  loggedInBy: string;
  level: number | null;
  className: string | null;
}

function formatLoggedInCharacterMeta(entry: SsoLoggedInEntry): string {
  const parts: string[] = [];
  if (entry.level != null) {
    parts.push(String(entry.level));
  }
  if (entry.className) {
    parts.push(entry.className);
  }
  return parts.length > 0 ? ` (${parts.join(" ")})` : "";
}

/** Active SSO logins: recent activity on the account's ``active_character`` only. */
export function listSsoLoggedInCharacters(
  tree: AccountTree,
  nowMs = Date.now(),
): SsoLoggedInEntry[] {
  const normalized = normalizeAccountTree(tree);
  const entries: SsoLoggedInEntry[] = [];
  for (const [account, data] of Object.entries(normalized)) {
    if (!isRecentActivity(data.last_login ?? null, nowMs)) {
      continue;
    }
    const character = (data.active_character ?? "").trim();
    if (!character) {
      continue;
    }
    const charEntry = data.characters?.[character];
    entries.push({
      account,
      character,
      loggedInBy: (data.last_login_by ?? "").trim(),
      level: charEntry?.level ?? null,
      className: charEntry?.class?.trim() || null,
    });
  }
  entries.sort(
    (a, b) => a.character.localeCompare(b.character) || a.account.localeCompare(b.account),
  );
  return entries;
}

export function formatSsoLoggedInTooltip(entries: ReadonlyArray<SsoLoggedInEntry>): string | undefined {
  if (entries.length === 0) {
    return undefined;
  }
  return entries
    .map((entry) => {
      const by = entry.loggedInBy || "—";
      return `${entry.character}${formatLoggedInCharacterMeta(entry)} — ${by}`;
    })
    .join("\n");
}

/** Count SSO characters actively logged in (90s activity window). */
export function countSsoLoggedInCharacters(tree: AccountTree, nowMs = Date.now()): number {
  return listSsoLoggedInCharacters(tree, nowMs).length;
}

/** Summary line for Proxy tab Account Data — mirrors SSO Characters login highlighting. */
export function ssoLoggedInSummary(
  tree: AccountTree,
  nowMs = Date.now(),
): { text: string; tone: "success" | "muted"; title?: string } {
  const entries = listSsoLoggedInCharacters(tree, nowMs);
  const count = entries.length;
  if (count === 0) {
    return { text: "None", tone: "muted" };
  }
  return {
    text: count === 1 ? "1 character" : `${count} characters`,
    tone: "success",
    title: formatSsoLoggedInTooltip(entries),
  };
}

/** Local account summary for Proxy Account Data (accounts + characters + aliases from CSV). */
export function localAccountsSummary(
  accounts: ReadonlyArray<{ alias: string; username: string }>,
  characterCount = 0,
): { text: string; tone: "success" | "muted" } {
  const uniqueUsernames = new Set(accounts.map((a) => a.username));
  const accountN = uniqueUsernames.size;
  if (accountN === 0) {
    return { text: "None", tone: "muted" };
  }
  const aliasN = accounts.filter((a) => a.alias !== a.username).length;
  return {
    text: `${accountN} accounts, ${characterCount} characters, ${aliasN} aliases`,
    tone: "success",
  };
}

export type LocalAccountSortKey = "name" | "aliases";

export interface LocalAccountRow {
  name: string;
  password: string;
  aliases: string;
}

/** Sort local account rows by account name or alias list. */
export function sortLocalAccounts(
  rows: LocalAccountRow[],
  options: { key: LocalAccountSortKey; ascending: boolean },
): LocalAccountRow[] {
  const sorted = [...rows];
  sorted.sort((a, b) => {
    const cmp = a[options.key].localeCompare(b[options.key], undefined, { sensitivity: "base" });
    return options.ascending ? cmp : -cmp;
  });
  return sorted;
}

/** Coerce wire account_tree JSON to a safe in-memory shape (null/missing → empty tree). */
export function normalizeAccountTree(raw: unknown): AccountTree {
  if (raw == null || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }
  const result: AccountTree = {};
  for (const [accountName, entryRaw] of Object.entries(raw)) {
    if (entryRaw == null || typeof entryRaw !== "object" || Array.isArray(entryRaw)) {
      result[accountName] = {};
      continue;
    }
    const e = entryRaw as Record<string, unknown>;
    result[accountName] = {
      aliases: normalizeStringArray(e.aliases),
      tags: normalizeStringArray(e.tags),
      characters: normalizeCharactersMap(e.characters),
      last_login:
        typeof e.last_login === "number" || typeof e.last_login === "string" ? e.last_login : null,
      last_login_by: typeof e.last_login_by === "string" ? e.last_login_by : "",
      active_character: typeof e.active_character === "string" ? e.active_character : "",
    };
  }
  return result;
}

export function abbreviateClass(klass: string | null | undefined): string {
  if (!klass) {
    return "";
  }
  return CLASS_SHORT[klass] ?? klass;
}

function parseStackCount(value: unknown): number | null {
  if (value == null) {
    return null;
  }
  if (value === true) {
    return 1;
  }
  if (value === false) {
    return 0;
  }
  const n = Number(value);
  return Number.isFinite(n) ? Math.trunc(n) : null;
}

export function stackCountCellParts(
  wire: string,
  value: unknown,
): { text: string; tooltip: string } {
  const n = parseStackCount(value);
  if (n == null) {
    return { text: "", tooltip: "" };
  }

  const thresholds = COUNT_TIER_THRESHOLDS[wire];
  if (!thresholds) {
    return { text: "", tooltip: "" };
  }

  const [someMin, lotsMin] = thresholds;
  if (!(0 < someMin && someMin < lotsMin)) {
    return { text: "", tooltip: "" };
  }

  if (wire === "lizard" && n === 0) {
    return { text: "", tooltip: "" };
  }

  let emoji: string;
  if (n >= lotsMin) {
    emoji = TIER_EMOJI_LOTS;
  } else if (n >= someMin) {
    emoji = TIER_EMOJI_SOME;
  } else {
    emoji = TIER_EMOJI_FEW;
  }

  return { text: emoji, tooltip: String(n) };
}

export function stackCountTierEmoji(wire: string, value: unknown): string {
  return stackCountCellParts(wire, value).text;
}

export function countColumnSortKey(displayEmoji: string): number {
  return TIER_SORT_RANK[displayEmoji] ?? 3;
}

export function readinessColumnSortKey(display: string): number {
  return READINESS_COLUMN_SORT_RANK[display] ?? 4;
}

function keyCell(value: unknown): string {
  if (value === true) {
    return KEY_COLUMN_YES;
  }
  if (value === false) {
    return "";
  }
  return KEY_COLUMN_UNKNOWN;
}

/** Key column display (ST/VP/Sb/Th). Mirrors Python ``_characters_tab_key_cell``. */
export function keyCellDisplay(value: unknown): string {
  return keyCell(value);
}

function tooltipBoolean(value: unknown): string {
  if (value === true) {
    return TOOLTIP_AFFIRMATIVE;
  }
  if (value === false) {
    return TOOLTIP_NEGATIVE;
  }
  return READINESS_UNKNOWN_MARK;
}

function chTooltip(neck: unknown, voidBox: unknown, mb4: unknown): string {
  const lines: string[] = [];

  if (neck === true) {
    lines.push(`Necklace of Resolution: ${TOOLTIP_AFFIRMATIVE}`);
  } else if (neck === false) {
    lines.push(`Necklace of Resolution: ${TOOLTIP_NEGATIVE}`);
  } else {
    lines.push("Necklace of Resolution: unknown (no data)");
  }

  if (voidBox === true) {
    lines.push(`Box of the Void: ${TOOLTIP_AFFIRMATIVE}`);
  } else if (voidBox === false) {
    lines.push(`Box of the Void: ${TOOLTIP_NEGATIVE}`);
  } else {
    lines.push("Box of the Void: unknown (no data)");
  }

  let mb4Ok = false;
  if (mb4 == null) {
    lines.push("Mana Battery (Class Four): unknown (no data)");
  } else {
    const n = parseStackCount(mb4);
    if (n == null) {
      lines.push("Mana Battery (Class Four): unknown (not a number)");
    } else {
      mb4Ok = n > 0;
      lines.push(`Mana Battery (Class Four): ${n} (stack count; >0 required for green)`);
    }
  }

  const voidOk = voidBox === true;
  const neckOk = neck === true;
  const greenOk = neckOk && voidOk && mb4Ok;
  lines.push("");
  lines.push(
    `Green tier needs: necklace ${TOOLTIP_AFFIRMATIVE}, void ${TOOLTIP_AFFIRMATIVE}, MB4 count > 0.`,
  );
  if (neck == null) {
    lines.push("Cell is blank when necklace status is unknown.");
  } else {
    lines.push(
      `Green bundle met: ${greenOk ? TOOLTIP_AFFIRMATIVE : TOOLTIP_NEGATIVE} (yellow if necklace ${TOOLTIP_AFFIRMATIVE} but not all green).`,
    );
  }
  return lines.join("\n");
}

export function chBundleCellParts(
  neck: unknown,
  voidBox: unknown,
  mb4: unknown,
): { text: string; tooltip: string } {
  if (neck !== true) {
    return { text: "", tooltip: "" };
  }

  const voidOk = voidBox === true;
  let mb4Ok = false;
  if (mb4 != null) {
    const n = parseStackCount(mb4);
    mb4Ok = n != null && n > 0;
  }

  const tip = chTooltip(neck, voidBox, mb4);
  if (voidOk && mb4Ok) {
    return { text: TIER_EMOJI_LOTS, tooltip: tip };
  }
  return { text: TIER_EMOJI_SOME, tooltip: tip };
}

const READINESS_RED = 2;
const READINESS_YELLOW = 1;
const READINESS_GREEN = 0;
const READINESS_MISSING = 3;

function readinessRankFromTierEmoji(emoji: string): number {
  if (emoji === TIER_EMOJI_LOTS) {
    return READINESS_GREEN;
  }
  if (emoji === TIER_EMOJI_FEW) {
    return READINESS_RED;
  }
  if (emoji === TIER_EMOJI_SOME) {
    return READINESS_YELLOW;
  }
  if (!emoji) {
    return READINESS_MISSING;
  }
  return READINESS_YELLOW;
}

function readinessRankThurg(thurg: unknown): number {
  if (thurg === true) {
    return READINESS_GREEN;
  }
  if (thurg === false) {
    return READINESS_RED;
  }
  return READINESS_MISSING;
}

function readinessRollUp(ranks: number[]): string {
  if (ranks.some((r) => r === READINESS_MISSING)) {
    return READINESS_UNKNOWN_MARK;
  }
  if (ranks.every((r) => r === READINESS_GREEN)) {
    return TIER_EMOJI_LOTS;
  }
  if (ranks.some((r) => r === READINESS_GREEN)) {
    return TIER_EMOJI_SOME;
  }
  if (ranks.some((r) => r === READINESS_RED)) {
    return TIER_EMOJI_FEW;
  }
  return TIER_EMOJI_SOME;
}

function thurgLabel(thurg: unknown): string {
  if (thurg === true) {
    return "has vial";
  }
  if (thurg === false) {
    return "no vial";
  }
  return "unknown";
}

function thurgReadinessTooltipLines(thurg: unknown): string[] {
  const header = "Th — Thurgpot (Vial of Velium Vapors):";
  if (thurg === true) {
    return [header, `  ${TIER_EMOJI_LOTS} green — ${thurgLabel(thurg)}`];
  }
  if (thurg === false) {
    return [header, `  ${TIER_EMOJI_FEW} red — ${thurgLabel(thurg)}`];
  }
  return [header, `  ${READINESS_UNKNOWN_MARK} unknown — vial status ${thurgLabel(thurg)}`];
}

function readinessStackDetailLines(title: string, wire: string, value: unknown): string[] {
  const th = COUNT_TIER_THRESHOLDS[wire];
  if (!th) {
    return [`${title}: (no thresholds for wire ${JSON.stringify(wire)})`];
  }
  const [someMin, lotsMin] = th;
  const { text: emoji, tooltip: countTip } = stackCountCellParts(wire, value);
  if (!emoji) {
    return [`${title}: count unknown`, `  Need ≥${lotsMin} for Lots, ≥${someMin} for Some tier.`];
  }
  return [
    `${title}: ${countTip} in inventory`,
    `  Tier ${emoji} — Lots ≥${lotsMin}, Some ≥${someMin} — needs Lots for readiness.`,
  ];
}

function readinessChBundleLines(items: CharacterItems, chEmoji: string): string[] {
  const neck = items.neck;
  const voidBox = items.void;
  const mb4 = items.mb4;
  const n = tooltipBoolean(neck);
  const v = tooltipBoolean(voidBox);
  let mb4s = "?";
  if (mb4 != null) {
    const parsed = parseStackCount(mb4);
    mb4s = parsed == null ? "?" : String(parsed);
  }
  return [`CH bundle: ${chEmoji || "—"}`, `  Necklace: ${n} · Void: ${v} · MB4: ${mb4s}`];
}

function readinessCleric(items: CharacterItems): { text: string; tooltip: string } {
  const ch = chBundleCellParts(items.neck, items.void, items.mb4);
  const mb3Emoji = stackCountTierEmoji("mb3", items.mb3);
  const ranks = [readinessRankFromTierEmoji(mb3Emoji), readinessRankThurg(items.thurg)];
  if (ch.text) {
    ranks.unshift(readinessRankFromTierEmoji(ch.text));
  }
  const out = readinessRollUp(ranks);
  const lines = [
    `Cleric — overall ${out}`,
    "",
    ...readinessChBundleLines(items, ch.text),
    "",
    ...readinessStackDetailLines("MB3 (Class Three battery)", "mb3", items.mb3),
    "",
    ...thurgReadinessTooltipLines(items.thurg),
  ];
  return { text: out, tooltip: lines.join("\n") };
}

function readinessMagician(items: CharacterItems): { text: string; tooltip: string } {
  const pearlVal = items.pearl;
  if (pearlVal == null) {
    const lines = [
      "Magician — no status until pearl count is known",
      "",
      ...readinessStackDetailLines("Pearl", "pearl", pearlVal),
    ];
    return { text: READINESS_UNKNOWN_MARK, tooltip: lines.join("\n") };
  }
  const pearlEmoji = stackCountTierEmoji("pearl", pearlVal);
  const out = readinessRollUp([readinessRankFromTierEmoji(pearlEmoji)]);
  const lines = [
    `Magician — overall ${out}`,
    "",
    ...readinessStackDetailLines("Pearl", "pearl", pearlVal),
  ];
  return { text: out, tooltip: lines.join("\n") };
}

const READINESS_BY_CLASS: Readonly<
  Partial<Record<string, (items: CharacterItems) => { text: string; tooltip: string }>>
> = {
  Cleric: readinessCleric,
  Magician: readinessMagician,
};

/** Class-specific readiness (R column). */
export function readinessCellParts(
  className: string | null | undefined,
  items: CharacterItems,
): { text: string; tooltip: string } {
  if (!className) {
    return { text: "", tooltip: "" };
  }
  const fn = READINESS_BY_CLASS[className];
  if (!fn) {
    return { text: "", tooltip: "" };
  }
  return fn(items);
}

function defaultZoneKeyToName(key: string | null | undefined): string {
  return zoneKeyToDisplay(key);
}

function activityTimestampMs(value: number | string | null | undefined): number | null {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      return null;
    }
    // The API normally sends ISO strings, but accept Unix seconds and milliseconds.
    return Math.abs(value) < 100_000_000_000 ? value * 1000 : value;
  }
  if (typeof value !== "string" || !value.trim()) {
    return null;
  }
  const text = value.trim();
  // Python treats a timezone-less ISO value as UTC. JavaScript otherwise
  // interprets it as local time, which can put UTC activity hours in the future
  // and keep every row highlighted indefinitely.
  const hasTimezone = /(?:z|[+-]\d{2}(?::?\d{2})?)$/i.test(text);
  const parsed = Date.parse(hasTimezone ? text : `${text}Z`);
  return Number.isFinite(parsed) ? parsed : null;
}

export function isRecentActivity(
  value: number | string | null | undefined,
  nowMs = Date.now(),
): boolean {
  const timestamp = activityTimestampMs(value);
  if (timestamp == null) {
    return false;
  }
  const elapsedSeconds = Math.max(0, (nowMs - timestamp) / 1000);
  return elapsedSeconds < ACTIVITY_FADE_SECONDS;
}

function buildCharacterRow(
  account: string,
  name: string,
  entry: CharacterEntry,
  accountMeta: AccountTreeEntry,
  zoneKeyToName: (key: string | null | undefined) => string,
  nowMs: number,
): CharacterRow {
  const items = entry.items ?? {};
  const classRaw = entry.class ?? null;
  const level = entry.level;
  const activeCharacter = accountMeta.active_character ?? "";
  const lastLogin = accountMeta.last_login ?? null;
  const isRecent = isRecentActivity(lastLogin, nowMs);
  const isBlocked = isRecent && Boolean(activeCharacter) && name !== activeCharacter;

  const readiness = readinessCellParts(classRaw, items);
  const ch = chBundleCellParts(items.neck, items.void, items.mb4);
  const liz = stackCountCellParts("lizard", items.lizard);

  let ct = liz.text;
  let ctTooltip = liz.tooltip;
  if (!ct && items.lizard == null) {
    ct = KEY_COLUMN_UNKNOWN;
    if (!ctTooltip) {
      ctTooltip = "Lizard Blood Potion: count unknown";
    }
  }

  const parkRaw = zoneKeyToName(entry.park);
  const bindRaw = zoneKeyToName(entry.bind);

  return {
    readiness: readiness.text,
    name,
    class: abbreviateClass(classRaw),
    classRaw,
    level: level != null ? String(level) : "",
    st: keyCell(items.st),
    vp: keyCell(items.vp),
    seb: keyCell(items.seb),
    ct,
    th: keyCell(items.thurg),
    ch: ch.text,
    park: parkRaw || "Unknown",
    bind: bindRaw || "Unknown",
    loggedInBy: isRecent ? (accountMeta.last_login_by ?? "") : "",
    account,
    lastLogin: isRecent ? lastLogin : null,
    isBlocked,
    ctTooltip,
    chTooltip: ch.tooltip,
    readinessTooltip: readiness.tooltip,
  };
}

/** Extract flat character rows from the normalized account tree. */
export function flattenCharacters(
  tree: AccountTree,
  options: FlattenCharactersOptions = {},
): CharacterRow[] {
  const zoneKeyToName = options.zoneKeyToName ?? defaultZoneKeyToName;
  const nowMs = options.nowMs ?? Date.now();
  const rows: CharacterRow[] = [];

  for (const [account, data] of Object.entries(tree)) {
    const characters = data.characters ?? {};
    for (const name of Object.keys(characters).sort()) {
      rows.push(buildCharacterRow(account, name, characters[name] ?? {}, data, zoneKeyToName, nowMs));
    }
  }

  return rows;
}

function rowSearchValue(row: CharacterRow, key: CharacterSortKey): string {
  switch (key) {
    case "readiness":
      return row.readiness;
    case "name":
      return row.name;
    case "class":
      return row.class;
    case "level":
      return row.level;
    case "st":
      return row.st;
    case "vp":
      return row.vp;
    case "seb":
      return row.seb;
    case "ct":
      return row.ct;
    case "th":
      return row.th;
    case "ch":
      return row.ch;
    case "park":
      return row.park;
    case "bind":
      return row.bind;
    case "loggedInBy":
      return row.loggedInBy;
    case "account":
      return row.account;
    default:
      return "";
  }
}

function keyTermMatch(row: CharacterRow, term: string): boolean {
  const col = KEY_FILTER_TERMS[term];
  if (!col) {
    return false;
  }
  const value = rowSearchValue(row, col);
  if (col === "ct" && (term === "lizpot" || term === "ctpot")) {
    return Boolean(value && value.trim());
  }
  if (col === "ch" && term === "chneck") {
    return value === TIER_EMOJI_LOTS || value === TIER_EMOJI_SOME;
  }
  return value === KEY_COLUMN_YES;
}

const SEARCHABLE_KEYS: readonly CharacterSortKey[] = [
  "readiness",
  "name",
  "class",
  "level",
  "st",
  "vp",
  "seb",
  "ct",
  "th",
  "ch",
  "park",
  "bind",
];

function rowMatchesTerm(
  row: CharacterRow,
  term: string,
  skipKeys: ReadonlySet<CharacterSortKey>,
): boolean {
  if (term in KEY_FILTER_TERMS) {
    return keyTermMatch(row, term);
  }

  for (const key of SEARCHABLE_KEYS) {
    if (skipKeys.has(key)) {
      continue;
    }
    if (rowSearchValue(row, key).toLowerCase().includes(term)) {
      return true;
    }
  }

  return keyTermMatch(row, term);
}

/** Multi-term AND filter with special key keywords (stkey, vpkey, lizpot, …). */
export function searchCharacters(
  rows: CharacterRow[],
  searchText: string,
  options: SearchCharactersOptions = {},
): CharacterRow[] {
  const skipKeys = options.skipKeys ?? SEARCH_SKIP_KEYS;
  const terms = searchText
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  if (terms.length === 0) {
    return rows;
  }
  return rows.filter((row) => terms.every((term) => rowMatchesTerm(row, term, skipKeys)));
}

function compareNames(a: CharacterRow, b: CharacterRow): number {
  return a.name.localeCompare(b.name);
}

function sortKeyForRow(row: CharacterRow, key: CharacterSortKey): string | number {
  return rowSearchValue(row, key);
}

/** Sort character rows by column key; blanks-last for loggedInBy. */
export function sortCharacters(
  rows: CharacterRow[],
  options: SortCharactersOptions,
): CharacterRow[] {
  const { key, ascending = true } = options;
  const sorted = [...rows];

  if (key === "readiness") {
    sorted.sort((a, b) => {
      const cmp =
        readinessColumnSortKey(a.readiness) - readinessColumnSortKey(b.readiness) ||
        compareNames(a, b);
      return ascending ? cmp : -cmp;
    });
    return sorted;
  }

  if (key === "ct" || key === "ch") {
    sorted.sort((a, b) => {
      const cmp =
        countColumnSortKey(rowSearchValue(a, key)) -
          countColumnSortKey(rowSearchValue(b, key)) || compareNames(a, b);
      return ascending ? cmp : -cmp;
    });
    return sorted;
  }

  if (KEY_SORT_KEYS.has(key)) {
    sorted.sort((a, b) => {
      const av = rowSearchValue(a, key);
      const bv = rowSearchValue(b, key);
      const cmp = (KEY_SORT_ORDER[av] ?? 2) - (KEY_SORT_ORDER[bv] ?? 2) || compareNames(a, b);
      return ascending ? cmp : -cmp;
    });
    return sorted;
  }

  if (SORT_BLANKS_LAST_KEYS.has(key)) {
    const isBlank = (row: CharacterRow) => !rowSearchValue(row, key).trim();
    const nonBlank = sorted.filter((r) => !isBlank(r));
    const blank = sorted.filter((r) => isBlank(r));
    nonBlank.sort((a, b) => {
      const cmp =
        rowSearchValue(a, key).localeCompare(rowSearchValue(b, key)) || compareNames(a, b);
      return ascending ? cmp : -cmp;
    });
    return [...nonBlank, ...blank];
  }

  sorted.sort((a, b) => {
    const av = sortKeyForRow(a, key);
    const bv = sortKeyForRow(b, key);
    const cmp = String(av).localeCompare(String(bv)) || compareNames(a, b);
    return ascending ? cmp : -cmp;
  });
  return sorted;
}
