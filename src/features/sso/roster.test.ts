import { describe, expect, it } from "vitest";

import {
  KEY_COLUMN_UNKNOWN,
  KEY_COLUMN_YES,
  READINESS_UNKNOWN_MARK,
  TIER_EMOJI_LOTS,
  TIER_EMOJI_SOME,
  TOOLTIP_AFFIRMATIVE,
  TOOLTIP_NEGATIVE,
  abbreviateClass,
  chBundleCellParts,
  countSsoLoggedInCharacters,
  flattenCharacters,
  formatSsoLoggedInTooltip,
  isRecentActivity,
  listSsoLoggedInCharacters,
  localAccountsSummary,
  normalizeAccountTree,
  searchCharacters,
  sortCharacters,
  sortLocalAccounts,
  ssoAccountsSummary,
  ssoLoggedInSummary,
  stackCountTierEmoji,
  type CharacterRow,
} from "./roster";

describe("normalizeAccountTree", () => {
  it("returns empty object for null, undefined, and non-objects", () => {
    expect(normalizeAccountTree(null)).toEqual({});
    expect(normalizeAccountTree(undefined)).toEqual({});
    expect(normalizeAccountTree([])).toEqual({});
    expect(normalizeAccountTree("bad")).toEqual({});
  });

  it("normalizes partial and malformed entries", () => {
    const tree = normalizeAccountTree({
      main: {
        aliases: ["Alt", 42],
        characters: {
          Alice: {
            class: "Cleric",
            level: 60,
            items: { st: true, lizard: 3 },
          },
          Bad: null,
        },
        last_login_by: "user1",
      },
      broken: "nope",
    });

    expect(tree.main.aliases).toEqual(["Alt"]);
    expect(tree.main.last_login_by).toBe("user1");
    expect(tree.main.characters?.Alice.class).toBe("Cleric");
    expect(tree.main.characters?.Alice.items?.st).toBe(true);
    expect(tree.main.characters?.Bad).toEqual({});
    expect(tree.broken).toEqual({});
  });
});

describe("flattenCharacters", () => {
  it("extracts sorted character rows with display fields", () => {
    const rows = flattenCharacters(
      normalizeAccountTree({
        acct: {
          characters: {
            Zara: { class: "Magician", level: 55, items: { pearl: 80 } },
            Amy: { class: "Necromancer", level: 50, items: { st: true } },
          },
          last_login_by: "bob",
        },
      }),
    );

    expect(rows.map((r) => r.name)).toEqual(["Amy", "Zara"]);
    expect(rows[0].class).toBe("Necro");
    expect(rows[0].st).toBe(KEY_COLUMN_YES);
    expect(rows[1].readiness).toBe(TIER_EMOJI_LOTS);
  });

  it("marks unknown lizard count with ?", () => {
    const [row] = flattenCharacters(
      normalizeAccountTree({
        a: { characters: { X: { items: {} } } },
      }),
    );
    expect(row.ct).toBe(KEY_COLUMN_UNKNOWN);
    expect(row.ctTooltip).toContain("unknown");
  });

  it("resolves zone keys to display names", () => {
    const [row] = flattenCharacters(
      normalizeAccountTree({
        a: {
          characters: {
            Hero: { park: "nro", bind: "kael" },
          },
        },
      }),
    );
    expect(row.park).toBe("Northern Desert Of Ro");
    expect(row.bind).toBe("Kael Drakkel");
  });

  it("shows login and blocked state only during the 90-second activity window", () => {
    const nowMs = Date.parse("2026-07-14T00:00:00Z");
    const tree = normalizeAccountTree({
      account: {
        characters: { Active: {}, Other: {} },
        last_login: "2026-07-13T23:59:30Z",
        last_login_by: "alice",
        active_character: "Active",
      },
    });
    const recent = flattenCharacters(tree, { nowMs });
    expect(recent.find((row) => row.name === "Active")?.loggedInBy).toBe("alice");
    expect(recent.find((row) => row.name === "Other")?.isBlocked).toBe(true);

    const stale = flattenCharacters(tree, { nowMs: nowMs + 90_000 });
    expect(stale.every((row) => row.loggedInBy === "")).toBe(true);
    expect(stale.every((row) => !row.isBlocked && row.lastLogin == null)).toBe(true);
  });

  it("accepts ISO strings and Unix timestamps, and rejects invalid timestamps", () => {
    const nowMs = Date.parse("2026-07-14T00:00:00Z");
    expect(isRecentActivity("2026-07-13T23:59:59Z", nowMs)).toBe(true);
    expect(isRecentActivity("2026-07-13T23:59:59", nowMs)).toBe(true);
    expect(isRecentActivity("2026-07-13T20:00:00", nowMs)).toBe(false);
    expect(isRecentActivity(nowMs / 1000 - 89, nowMs)).toBe(true);
    expect(isRecentActivity(nowMs - 90_000, nowMs)).toBe(false);
    expect(isRecentActivity("not-a-date", nowMs)).toBe(false);
  });
});

describe("abbreviateClass", () => {
  it("shortens known classes", () => {
    expect(abbreviateClass("ShadowKnight")).toBe("SK");
    expect(abbreviateClass("Necromancer")).toBe("Necro");
    expect(abbreviateClass("Cleric")).toBe("Cleric");
    expect(abbreviateClass(null)).toBe("");
  });
});

describe("stackCountTierEmoji", () => {
  it("applies lizard thresholds", () => {
    expect(stackCountTierEmoji("lizard", 0)).toBe("");
    expect(stackCountTierEmoji("lizard", 1)).toBe(TIER_EMOJI_SOME);
    expect(stackCountTierEmoji("lizard", 2)).toBe(TIER_EMOJI_LOTS);
  });
});

describe("character tooltips", () => {
  it("uses check and x emojis for yes/no in CH and readiness tooltips", () => {
    const complete = chBundleCellParts(true, true, 2);
    expect(complete.tooltip).toContain(`Necklace of Resolution: ${TOOLTIP_AFFIRMATIVE}`);
    expect(complete.tooltip).toContain(`Box of the Void: ${TOOLTIP_AFFIRMATIVE}`);
    expect(complete.tooltip).toContain(`Green bundle met: ${TOOLTIP_AFFIRMATIVE}`);

    const partial = chBundleCellParts(true, false, 0);
    expect(partial.tooltip).toContain(`Box of the Void: ${TOOLTIP_NEGATIVE}`);
    expect(partial.tooltip).toContain(`Green bundle met: ${TOOLTIP_NEGATIVE}`);

    const [cleric] = flattenCharacters(
      normalizeAccountTree({
        a: {
          characters: {
            Bob: { class: "Cleric", items: { neck: true, void: false, mb4: 1 } },
          },
        },
      }),
    );
    expect(cleric.readinessTooltip).toContain(`Necklace: ${TOOLTIP_AFFIRMATIVE}`);
    expect(cleric.readinessTooltip).toContain(`Void: ${TOOLTIP_NEGATIVE}`);
    expect(cleric.chTooltip).not.toContain(": yes");
    expect(cleric.chTooltip).not.toContain(": no");
  });
});

function sampleRows(): CharacterRow[] {
  return flattenCharacters(
    normalizeAccountTree({
      one: {
        characters: {
          Alpha: {
            class: "Cleric",
            park: "east",
            items: { st: true, neck: true, void: true, mb4: 2, thurg: true },
          },
          Beta: {
            class: "Warrior",
            park: "west",
            items: { vp: true, lizard: 5 },
          },
          Gamma: {
            class: "Magician",
            items: { seb: false, pearl: null },
          },
        },
        last_login: new Date().toISOString(),
        last_login_by: "alice",
      },
      two: {
        characters: {
          Delta: { class: "Rogue", items: {} },
        },
        last_login_by: "",
      },
    }),
  );
}

describe("searchCharacters", () => {
  const rows = sampleRows();

  it("returns all rows for empty search", () => {
    expect(searchCharacters(rows, "")).toHaveLength(4);
    expect(searchCharacters(rows, "   ")).toHaveLength(4);
  });

  it("ANDs multiple terms on generic columns", () => {
    const filtered = searchCharacters(rows, "cleric east");
    expect(filtered).toHaveLength(1);
    expect(filtered[0].name).toBe("Alpha");
  });

  it("matches special key keywords", () => {
    expect(searchCharacters(rows, "stkey").map((r) => r.name)).toEqual(["Alpha"]);
    expect(searchCharacters(rows, "vpkey").map((r) => r.name)).toEqual(["Beta"]);
    // lizpot matches any row with a non-empty CT cell, including "?" (unknown count).
    expect(searchCharacters(rows, "lizpot").map((r) => r.name)).toEqual([
      "Alpha",
      "Beta",
      "Gamma",
      "Delta",
    ]);
    expect(searchCharacters(rows, "chneck").map((r) => r.name)).toEqual(["Alpha"]);
    expect(searchCharacters(rows, "thurgpot").map((r) => r.name)).toEqual(["Alpha"]);
  });

  it("does not search account or loggedInBy by default", () => {
    expect(searchCharacters(rows, "alice")).toHaveLength(0);
    expect(searchCharacters(rows, "one")).toHaveLength(0);
  });

  it("ANDs special and generic terms", () => {
    const filtered = searchCharacters(rows, "stkey cleric");
    expect(filtered).toHaveLength(1);
    expect(filtered[0].name).toBe("Alpha");
  });
});

describe("sortCharacters", () => {
  const rows = sampleRows();

  it("sorts readiness with green before yellow, then ?, then red, then blank", () => {
    const sorted = sortCharacters(rows, { key: "readiness", ascending: true });
    const magician = sorted.find((r) => r.name === "Gamma");
    expect(magician?.readiness).toBe(READINESS_UNKNOWN_MARK);
    const cleric = sorted.find((r) => r.name === "Alpha");
    // MB3 unknown keeps cleric at ? until stack data exists.
    expect(cleric?.readiness).toBe(READINESS_UNKNOWN_MARK);
    const ranks = sorted.map((r) => r.readiness);
    expect(ranks.indexOf(READINESS_UNKNOWN_MARK)).toBeLessThan(ranks.lastIndexOf(""));
  });

  it("sorts CT tier columns by emoji rank", () => {
    const sorted = sortCharacters(rows, { key: "ct", ascending: true });
    const beta = sorted.find((r) => r.name === "Beta");
    expect(beta?.ct).toBe(TIER_EMOJI_LOTS);
  });

  it("sorts key columns green before ? before blank", () => {
    const sorted = sortCharacters(rows, { key: "st", ascending: true });
    expect(sorted[0].name).toBe("Alpha");
    expect(sorted[sorted.length - 1].st).toBe(KEY_COLUMN_UNKNOWN);
  });

  it("keeps blank loggedInBy rows last", () => {
    const sorted = sortCharacters(rows, { key: "loggedInBy", ascending: true });
    expect(sorted[sorted.length - 1].name).toBe("Delta");
    expect(sorted[0].loggedInBy).toBe("alice");
  });

  it("sorts by name ascending with secondary name tie-break", () => {
    const sorted = sortCharacters(rows, { key: "name", ascending: true });
    expect(sorted.map((r) => r.name)).toEqual(["Alpha", "Beta", "Delta", "Gamma"]);
  });

  it("reverses non-blank-last columns when descending", () => {
    const sorted = sortCharacters(rows, { key: "name", ascending: false });
    expect(sorted[0].name).toBe("Gamma");
  });
});

describe("ssoLoggedInSummary", () => {
  it("counts only the active character when login activity is recent", () => {
    const nowMs = Date.parse("2026-07-14T00:00:00Z");
    const tree = normalizeAccountTree({
      main: {
        characters: { Active: { class: "Cleric", level: 60 }, Other: {} },
        last_login: "2026-07-13T23:59:30Z",
        last_login_by: "alice",
        active_character: "Active",
      },
      alt: {
        characters: { Other: {} },
        last_login: "2026-07-13T20:00:00Z",
      },
    });
    expect(ssoLoggedInSummary(tree, nowMs)).toEqual({
      text: "1 character",
      tone: "success",
      title: "Active (60 Cleric) — alice",
    });
    expect(countSsoLoggedInCharacters(tree, nowMs)).toBe(1);
    expect(listSsoLoggedInCharacters(tree, nowMs)).toEqual([
      {
        account: "main",
        character: "Active",
        loggedInBy: "alice",
        level: 60,
        className: "Cleric",
      },
    ]);
  });

  it("ignores recent activity without an active character", () => {
    const nowMs = Date.parse("2026-07-14T00:00:00Z");
    const tree = normalizeAccountTree({
      main: {
        characters: { Active: {}, Other: {} },
        last_login: "2026-07-13T23:59:30Z",
        last_login_by: "alice",
      },
    });
    expect(ssoLoggedInSummary(tree, nowMs)).toEqual({ text: "None", tone: "muted" });
  });

  it("returns None when no recent logins", () => {
    const nowMs = Date.parse("2026-07-14T00:00:00Z");
    const tree = normalizeAccountTree({
      main: {
        characters: { Active: {} },
        last_login: "2026-07-13T20:00:00Z",
        active_character: "Active",
      },
    });
    expect(ssoLoggedInSummary(tree, nowMs)).toEqual({ text: "None", tone: "muted" });
  });

  it("pluralizes and lists multiple active characters", () => {
    const nowMs = Date.parse("2026-07-14T00:00:00Z");
    const tree = normalizeAccountTree({
      main: {
        characters: { A: { class: "Magician", level: 55 } },
        last_login: "2026-07-13T23:59:30Z",
        active_character: "A",
        last_login_by: "alice",
      },
      alt: {
        characters: { B: { class: "Warrior", level: 60 } },
        last_login: "2026-07-13T23:59:00Z",
        active_character: "B",
        last_login_by: "bob",
      },
    });
    expect(ssoLoggedInSummary(tree, nowMs)).toEqual({
      text: "2 characters",
      tone: "success",
      title: "A (55 Magician) — alice\nB (60 Warrior) — bob",
    });
    expect(formatSsoLoggedInTooltip(listSsoLoggedInCharacters(tree, nowMs))).toBe(
      "A (55 Magician) — alice\nB (60 Warrior) — bob",
    );
  });
});

describe("ssoAccountsSummary", () => {
  it("includes alias and tag counts in aliases/tags total", () => {
    const tree = normalizeAccountTree({
      main: {
        aliases: ["alt1"],
        tags: ["tag1", "tag2"],
        characters: { Hero: {} },
      },
    });
    expect(ssoAccountsSummary(tree)).toEqual({
      text: "1 accounts, 1 characters, 3 aliases/tags",
      tone: "success",
    });
  });

  it("returns None when the cache tree is empty", () => {
    expect(ssoAccountsSummary({})).toEqual({ text: "None", tone: "muted" });
  });
});

describe("localAccountsSummary", () => {
  it("includes local character count between accounts and aliases", () => {
    expect(
      localAccountsSummary(
        [
          { alias: "main", username: "main" },
          { alias: "alt1", username: "main" },
        ],
        5,
      ),
    ).toEqual({ text: "1 accounts, 5 characters, 1 aliases", tone: "success" });
  });

  it("returns None when there are no local accounts", () => {
    expect(localAccountsSummary([], 3)).toEqual({ text: "None", tone: "muted" });
  });
});

describe("sortLocalAccounts", () => {
  const rows = [
    { name: "zebra", password: "pw1", aliases: "z1, z2" },
    { name: "alpha", password: "pw2", aliases: "main" },
    { name: "beta", password: "pw3", aliases: "" },
  ];

  it("sorts by account name ascending by default", () => {
    const sorted = sortLocalAccounts(rows, { key: "name", ascending: true });
    expect(sorted.map((r) => r.name)).toEqual(["alpha", "beta", "zebra"]);
  });

  it("sorts by aliases descending", () => {
    const sorted = sortLocalAccounts(rows, { key: "aliases", ascending: false });
    expect(sorted[0].name).toBe("zebra");
  });
});
