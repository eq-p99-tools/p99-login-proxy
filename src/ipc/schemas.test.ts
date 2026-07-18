import { describe, expect, it } from "vitest";

import { parseSsoAccounts } from "./schemas";

describe("parseSsoAccounts", () => {
  it("normalizes null account_tree to empty object", () => {
    const result = parseSsoAccounts({ account_tree: null, account_count: 0 });
    expect(result.account_tree).toEqual({});
    expect(result.account_count).toBe(0);
  });

  it("normalizes missing account_tree", () => {
    const result = parseSsoAccounts({ account_count: 2 });
    expect(result.account_tree).toEqual({});
  });

  it("preserves valid tree", () => {
    const tree = { main: { aliases: ["a1"] } };
    const result = parseSsoAccounts({ account_tree: tree, account_count: 1 });
    expect(result.account_tree).toEqual(tree);
  });
});
