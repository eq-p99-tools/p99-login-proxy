import { describe, expect, it } from "vitest";

import type { LocalCharacter } from "../../ipc/schemas";

import {
  flattenLocalCharacters,
  searchLocalCharacters,
  sortLocalCharacters,
} from "./localCharacterRoster";
import { KEY_COLUMN_UNKNOWN, KEY_COLUMN_YES, TIER_EMOJI_LOTS } from "./roster";

function sampleCharacters(): LocalCharacter[] {
  return [
    {
      name: "Alice",
      account_alias: "main",
      server: "",
      class: "Cleric",
      level: 60,
      bind: "kael",
      park: "nro",
      items: { st: true, neck: true, void: true, mb4: 2, thurg: true, lizard: 3 },
    },
    {
      name: "Bob",
      account_alias: "altacct",
      server: "",
      class: "Warrior",
      level: 55,
      bind: null,
      park: "west",
      items: { vp: true, lizard: 5 },
    },
    {
      name: "Zara",
      account_alias: "main",
      server: "",
      class: "Magician",
      level: null,
      bind: null,
      park: null,
      items: { pearl: 80 },
    },
  ];
}

describe("flattenLocalCharacters", () => {
  it("builds display rows with keys, pots, and zones", () => {
    const rows = flattenLocalCharacters(sampleCharacters());
    expect(rows.map((r) => r.name)).toEqual(["Alice", "Bob", "Zara"]);
    const alice = rows[0];
    expect(alice.st).toBe(KEY_COLUMN_YES);
    expect(alice.class).toBe("Cleric");
    expect(alice.level).toBe("60");
    expect(alice.park.toLowerCase()).toContain("ro");
    expect(alice.ch).toBe(TIER_EMOJI_LOTS);
  });

  it("shows unknown lizard count as ?", () => {
    const [row] = flattenLocalCharacters([
      {
        name: "X",
        account_alias: "a",
        server: "",
        class: null,
        level: null,
        bind: null,
        park: null,
        items: {},
      },
    ]);
    expect(row.ct).toBe(KEY_COLUMN_UNKNOWN);
  });
});

describe("searchLocalCharacters", () => {
  const rows = flattenLocalCharacters(sampleCharacters());

  it("skips account column in generic search", () => {
    expect(searchLocalCharacters(rows, "altacct")).toHaveLength(0);
    expect(searchLocalCharacters(rows, "main")).toHaveLength(0);
  });

  it("matches special key terms and generic columns", () => {
    expect(searchLocalCharacters(rows, "stkey").map((r) => r.name)).toEqual(["Alice"]);
    expect(searchLocalCharacters(rows, "cleric kael").map((r) => r.name)).toEqual(["Alice"]);
  });
});

describe("sortLocalCharacters", () => {
  const rows = flattenLocalCharacters(sampleCharacters());

  it("defaults to class sort like Python local tab", () => {
    const sorted = sortLocalCharacters(rows, { key: "class", ascending: true });
    expect(sorted.map((r) => r.name)).toEqual(["Alice", "Zara", "Bob"]);
  });

  it("sorts key columns green before unknown", () => {
    const sorted = sortLocalCharacters(rows, { key: "st", ascending: true });
    expect(sorted[0].name).toBe("Alice");
  });
});
