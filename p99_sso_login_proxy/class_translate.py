"""Canonical EQ class names + /who title translation.

Mirrors the ``zone_translate`` module's shape: static data plus a resolver.

- :data:`CLASSES` is the authoritative tuple of class keys used everywhere in the
  app (readiness dispatch, local-character dialog, UI short-names).
- :func:`resolve_class` normalizes whatever EQ prints in a ``/who`` line
  (``[60 Warlord] ...``, ``[45 Cleric] ...``, ``[60 Shadow Knight] ...``) to the
  canonical key from :data:`CLASSES`, handling level 51/55/60 titles.

Source of truth for the title map mirrors roboToald's ``TITLE_TO_CLASS`` in
``roboToald/db/raid_models/character.py``.
"""

from __future__ import annotations

CLASSES: tuple[str, ...] = (
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
)

# Level 51/55/60 title strings EQ prints in /who, mapped back to canonical keys.
# Lowercased for case-insensitive lookup in :func:`resolve_class`.
TITLE_TO_BASE_CLASS: dict[str, str] = {
    "minstrel": "Bard",
    "troubadour": "Bard",
    "virtuoso": "Bard",
    "vicar": "Cleric",
    "templar": "Cleric",
    "high priest": "Cleric",
    "wanderer": "Druid",
    "preserver": "Druid",
    "hierophant": "Druid",
    "illusionist": "Enchanter",
    "beguiler": "Enchanter",
    "phantasmist": "Enchanter",
    "elementalist": "Magician",
    "conjurer": "Magician",
    "arch mage": "Magician",
    "disciple": "Monk",
    "master": "Monk",
    "grandmaster": "Monk",
    "heretic": "Necromancer",
    "defiler": "Necromancer",
    "warlock": "Necromancer",
    "cavalier": "Paladin",
    "knight": "Paladin",
    "crusader": "Paladin",
    "pathfinder": "Ranger",
    "outrider": "Ranger",
    "warder": "Ranger",
    "rake": "Rogue",
    "blackguard": "Rogue",
    "assassin": "Rogue",
    "reaver": "ShadowKnight",
    "revenant": "ShadowKnight",
    "grave lord": "ShadowKnight",
    "mystic": "Shaman",
    "luminary": "Shaman",
    "oracle": "Shaman",
    "champion": "Warrior",
    "myrmidon": "Warrior",
    "warlord": "Warrior",
    "channeler": "Wizard",
    "evoker": "Wizard",
    "sorcerer": "Wizard",
}

# Base class names as they appear in /who (level 1-50), normalized to canonical keys.
# Handles "Shadow Knight" (EQ's two-word form) -> "ShadowKnight".
BASE_CLASS_ALIASES: dict[str, str] = {
    **{name.lower(): name for name in CLASSES},
    "shadow knight": "ShadowKnight",
}


def resolve_class(raw: str | None) -> str | None:
    """Return the canonical class key for a /who class/title string, or ``None``.

    Accepts both base class names ("Warrior", "Shadow Knight") and level-60 titles
    ("Warlord", "Grave Lord"). Case- and whitespace-insensitive.
    """
    if not raw:
        return None
    key = " ".join(raw.split()).lower()
    if not key:
        return None
    if key in BASE_CLASS_ALIASES:
        return BASE_CLASS_ALIASES[key]
    return TITLE_TO_BASE_CLASS.get(key)
