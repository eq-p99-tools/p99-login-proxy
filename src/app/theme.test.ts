import { describe, expect, it } from "vitest";

import {
  nativeWindowThemeForMode,
  resolveTheme,
  themeUsesDarkPalette,
  THEME_OPTIONS,
} from "./theme";

describe("theme", () => {
  it("lists EverQuest-inspired palettes in the theme dropdown", () => {
    const labels = THEME_OPTIONS.map((option) => option.label);
    expect(labels).toContain("Qeynos Harbor");
    expect(labels).toContain("Erudin Library");
    expect(labels).toContain("Nektulos Forest");
    expect(labels).toContain("Gnomish Terminal");
    expect(labels).toContain("Iceclad Ocean");
    expect(labels).toContain("Kelethin Treetops");
    expect(labels).toContain("Lavastorm Mountains");
    expect(labels).toContain("Paineel Undercity");
  });

  it("resolves custom palettes directly", () => {
    expect(resolveTheme("gnomish")).toBe("gnomish");
    expect(resolveTheme("iceclad")).toBe("iceclad");
    expect(resolveTheme("kelethin")).toBe("kelethin");
    expect(resolveTheme("lavastorm")).toBe("lavastorm");
    expect(resolveTheme("erudin")).toBe("erudin");
    expect(resolveTheme("paineel")).toBe("paineel");
    expect(resolveTheme("light")).toBe("light");
    expect(resolveTheme("dark")).toBe("dark");
  });

  it("maps system default to the standard light or dark palette", () => {
    expect(["light", "dark"]).toContain(resolveTheme("system"));
  });

  it("treats EQ palettes as dark or light for legacy dark_mode", () => {
    expect(themeUsesDarkPalette("gnomish")).toBe(true);
    expect(themeUsesDarkPalette("iceclad")).toBe(true);
    expect(themeUsesDarkPalette("kelethin")).toBe(true);
    expect(themeUsesDarkPalette("lavastorm")).toBe(true);
    expect(themeUsesDarkPalette("paineel")).toBe(true);
    expect(themeUsesDarkPalette("erudin")).toBe(false);
    expect(themeUsesDarkPalette("light")).toBe(false);
    expect(themeUsesDarkPalette("dark")).toBe(true);
    expect(themeUsesDarkPalette("system", true)).toBe(true);
    expect(themeUsesDarkPalette("system", false)).toBe(false);
  });

  it("maps palettes to native window chrome while system follows the OS", () => {
    expect(nativeWindowThemeForMode("system")).toBeNull();
    expect(nativeWindowThemeForMode("light")).toBe("light");
    expect(nativeWindowThemeForMode("erudin")).toBe("light");
    for (const theme of ["dark", "gnomish", "iceclad", "kelethin", "lavastorm", "paineel"] as const) {
      expect(nativeWindowThemeForMode(theme)).toBe("dark");
    }
  });
});
