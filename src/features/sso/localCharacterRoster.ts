/** Flat display rows for the local-characters table — mirrors Python ``_refresh_local_characters_list``. */

import type { LocalCharacter } from "../../ipc/schemas";

import {
  KEY_COLUMN_UNKNOWN,
  abbreviateClass,
  chBundleCellParts,
  keyCellDisplay,
  readinessCellParts,
  searchCharacters,
  sortCharacters,
  stackCountCellParts,
  type CharacterItems,
  type CharacterRow,
  type CharacterSortKey,
  type SearchCharactersOptions,
  type SortCharactersOptions,
} from "./roster";
import { zoneKeyToDisplay } from "./zoneTranslate";

export type LocalCharacterSortKey = Exclude<CharacterSortKey, "loggedInBy">;

export interface LocalCharacterRow {
  rowKey: string;
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
  account: string;
  server: string;
  ctTooltip: string;
  chTooltip: string;
  readinessTooltip: string;
}

function normalizeItems(raw: LocalCharacter["items"]): CharacterItems {
  if (!raw || typeof raw !== "object") {
    return {};
  }
  const out: CharacterItems = {};
  for (const [key, value] of Object.entries(raw)) {
    if (value === null || value === undefined) {
      continue;
    }
    if (typeof value === "boolean") {
      (out as Record<string, boolean | number | null>)[key] = value;
    } else if (typeof value === "number") {
      (out as Record<string, boolean | number | null>)[key] = value;
    }
  }
  return out;
}

function localRowKey(ch: LocalCharacter): string {
  if (ch.server) {
    return `${ch.server}:${ch.name}`;
  }
  return ch.name;
}

function buildLocalCharacterRow(ch: LocalCharacter): LocalCharacterRow {
  const items = normalizeItems(ch.items);
  const classRaw = ch.class ?? null;
  const readiness = readinessCellParts(classRaw, items);
  const chParts = chBundleCellParts(items.neck, items.void, items.mb4);
  const liz = stackCountCellParts("lizard", items.lizard);

  let ct = liz.text;
  let ctTooltip = liz.tooltip;
  if (!ct && items.lizard == null) {
    ct = KEY_COLUMN_UNKNOWN;
    if (!ctTooltip) {
      ctTooltip = "Lizard Blood Potion: count unknown";
    }
  }

  const parkRaw = zoneKeyToDisplay(ch.park);
  const bindRaw = zoneKeyToDisplay(ch.bind);

  return {
    rowKey: localRowKey(ch),
    readiness: readiness.text,
    name: ch.name,
    class: abbreviateClass(classRaw),
    classRaw,
    level: ch.level != null ? String(ch.level) : "",
    st: keyCellDisplay(items.st),
    vp: keyCellDisplay(items.vp),
    seb: keyCellDisplay(items.seb),
    ct,
    th: keyCellDisplay(items.thurg),
    ch: chParts.text,
    park: parkRaw || "Unknown",
    bind: bindRaw || "Unknown",
    account: ch.account_alias,
    server: ch.server,
    ctTooltip,
    chTooltip: chParts.tooltip,
    readinessTooltip: readiness.tooltip,
  };
}

/** Flatten local characters to display rows sorted by name. */
export function flattenLocalCharacters(characters: readonly LocalCharacter[]): LocalCharacterRow[] {
  return [...characters]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map(buildLocalCharacterRow);
}

function toCharacterRow(row: LocalCharacterRow): CharacterRow {
  return {
    readiness: row.readiness,
    name: row.name,
    class: row.class,
    classRaw: row.classRaw,
    level: row.level,
    st: row.st,
    vp: row.vp,
    seb: row.seb,
    ct: row.ct,
    th: row.th,
    ch: row.ch,
    park: row.park,
    bind: row.bind,
    loggedInBy: "",
    account: row.account,
    roles: "",
    lastLogin: null,
    isBlocked: false,
    ctTooltip: row.ctTooltip,
    chTooltip: row.chTooltip,
    readinessTooltip: row.readinessTooltip,
  };
}

/** Multi-term search; skips account column by default (Python ``_LOCAL_CHARACTERS_FILTER_SKIP_COLS``). */
export function searchLocalCharacters(
  rows: LocalCharacterRow[],
  searchText: string,
  options: SearchCharactersOptions = {},
): LocalCharacterRow[] {
  const skipKeys = options.skipKeys ?? new Set<CharacterSortKey>(["account"]);
  return rows.filter((row) => {
    const [match] = searchCharacters([toCharacterRow(row)], searchText, { skipKeys });
    return Boolean(match);
  });
}

/** Sort local character rows by column key. */
export function sortLocalCharacters(
  rows: LocalCharacterRow[],
  options: SortCharactersOptions & { key: LocalCharacterSortKey },
): LocalCharacterRow[] {
  const indexed = rows.map((row) => ({ row, sort: toCharacterRow(row) }));
  const sortedSort = sortCharacters(
    indexed.map((entry) => entry.sort),
    options,
  );
  const rank = new Map<string, number>();
  for (const [idx, sortRow] of sortedSort.entries()) {
    const match = indexed.find(
      (entry) =>
        entry.sort.name === sortRow.name &&
        entry.sort.account === sortRow.account &&
        entry.sort.park === sortRow.park,
    );
    if (match) {
      rank.set(match.row.rowKey, idx);
    }
  }
  return [...indexed]
    .sort((a, b) => (rank.get(a.row.rowKey) ?? 0) - (rank.get(b.row.rowKey) ?? 0))
    .map((entry) => entry.row);
}
