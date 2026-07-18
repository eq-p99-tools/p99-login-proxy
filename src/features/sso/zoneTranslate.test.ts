import { describe, expect, it } from "vitest";

import { zoneKeyToDisplay, zoneSuggestionValues, zoneToZonekey } from "./zoneTranslate";

describe("zoneTranslate", () => {
  it("maps display names to zone keys", () => {
    expect(zoneToZonekey("Kael Drakkel")).toBe("kael");
    expect(zoneToZonekey("nro")).toBe("nro");
  });

  it("maps zone keys to title-cased display names", () => {
    expect(zoneKeyToDisplay("nro")).toBe("Northern Desert Of Ro");
    expect(zoneKeyToDisplay("kael")).toBe("Kael Drakkel");
    expect(zoneKeyToDisplay(null)).toBe("Unknown");
  });

  it("title-cases unknown zone keys", () => {
    expect(zoneKeyToDisplay("customzone")).toBe("Customzone");
  });

  it("provides sorted zone suggestions", () => {
    const values = zoneSuggestionValues();
    expect(values.length).toBeGreaterThan(100);
    expect(values).toContain("Northern Desert Of Ro");
    expect(values).toContain("nro");
    expect([...values].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }))).toEqual(values);
  });
});
