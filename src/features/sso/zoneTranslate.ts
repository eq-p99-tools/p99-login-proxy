import zoneAliases from "../../data/zone_aliases.json";

/** Title-case each word — mirrors Python ``zone_translate.capitalize``. */
function capitalizeWords(text: string): string {
  return text
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

const ALIAS_TO_KEY: Record<string, string> = {};
const KEY_TO_DISPLAY = new Map<string, string>();

for (const [display, key] of Object.entries(zoneAliases as Record<string, string>)) {
  ALIAS_TO_KEY[display.toLowerCase()] = key;
  if (!KEY_TO_DISPLAY.has(key)) {
    KEY_TO_DISPLAY.set(key, display);
  }
}

/** Map display name or zonekey to canonical zonekey (Python ``zone_to_zonekey``). */
export function zoneToZonekey(zone: string): string {
  const trimmed = zone.trim();
  if (!trimmed) {
    return "";
  }
  const lc = trimmed.toLowerCase();
  return ALIAS_TO_KEY[lc] ?? lc;
}

/** Resolve zonekey to a display name; falls back to title-cased key (Python ``zonekey_to_zone``). */
export function zoneKeyToDisplay(key: string | null | undefined): string {
  if (key == null || key === "") {
    return "Unknown";
  }
  const mapped = KEY_TO_DISPLAY.get(key);
  return capitalizeWords(mapped ?? key);
}

/** Sorted zone display names and keys for autocomplete suggestions. */
export function zoneSuggestionValues(): string[] {
  const values = new Set<string>();
  for (const [display, zoneKey] of Object.entries(zoneAliases as Record<string, string>)) {
    values.add(capitalizeWords(display));
    values.add(zoneKey);
  }
  return [...values].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
}
