import { describe, expect, it } from "vitest";

import {
  LOCAL_CHARACTER_GROUP_HEADER,
  LOCAL_CHARACTER_WIDTHS,
  SSO_CHARACTER_GROUP_HEADER,
  SSO_CHARACTER_WIDTHS,
} from "./tableConfig";

function spanTotal(cells: ReadonlyArray<{ colSpan: number }>) {
  return cells.reduce((sum, cell) => sum + cell.colSpan, 0);
}

describe("character group headers", () => {
  it("covers all SSO character columns with Pots over CT and Th only", () => {
    expect(spanTotal(SSO_CHARACTER_GROUP_HEADER)).toBe(Object.keys(SSO_CHARACTER_WIDTHS).length);
    expect(SSO_CHARACTER_GROUP_HEADER[2]).toEqual(
      expect.objectContaining({ label: "Pots", colSpan: 2 }),
    );
  });

  it("covers all local character columns with Pots over CT and Th only", () => {
    expect(spanTotal(LOCAL_CHARACTER_GROUP_HEADER)).toBe(Object.keys(LOCAL_CHARACTER_WIDTHS).length);
    expect(LOCAL_CHARACTER_GROUP_HEADER[2]).toEqual(
      expect.objectContaining({ label: "Pots", colSpan: 2 }),
    );
  });
});
