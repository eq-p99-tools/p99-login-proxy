/** Canonical EQ class keys — mirrors Python ``class_translate.CLASSES``. */
export const CLASS_CHOICES = [
  "Bard",
  "Cleric",
  "Druid",
  "Enchanter",
  "Magician",
  "Monk",
  "Necromancer",
  "Paladin",
  "Ranger",
  "Rogue",
  "ShadowKnight",
  "Shaman",
  "Warrior",
  "Wizard",
] as const;

export type ClassChoice = (typeof CLASS_CHOICES)[number];
