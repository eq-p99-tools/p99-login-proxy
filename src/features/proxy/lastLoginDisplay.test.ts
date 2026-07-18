import { describe, expect, it } from "vitest";

import { lastLoginDisplay } from "./lastLoginDisplay";

describe("lastLoginDisplay", () => {
  it("shows em dash when no login yet", () => {
    expect(lastLoginDisplay(null, null, null)).toEqual({
      text: "—",
      tooltip: "No login proxied yet.",
    });
  });

  it("does not duplicate account when backend already formatted alias → account", () => {
    const result = lastLoginDisplay("myalias → realuser", "realuser", "sso");
    expect(result.text).toBe("myalias → realuser");
    expect(result.tooltip).toContain("Typed in EQ login screen: myalias");
    expect(result.tooltip).toContain("Sent to login server: realuser");
    expect(result.tooltip).toContain("Rewrite method: SSO");
  });

  it("shows single username when no rewrite occurred", () => {
    const result = lastLoginDisplay("realuser", "realuser", "passthrough");
    expect(result.text).toBe("realuser");
    expect(result.tooltip).toContain("Login username (no rewrite): realuser");
  });
});
