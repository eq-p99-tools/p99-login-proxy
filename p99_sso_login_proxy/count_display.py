"""Stack-count tier display (emoji + tooltip) for the Characters table — UI-only; server sends raw ints."""

from __future__ import annotations

# Large green / yellow / red circles (same as plan).
TIER_EMOJI_LOTS = "\U0001f7e2"  # 🟢
TIER_EMOJI_SOME = "\U0001f7e1"  # 🟡
TIER_EMOJI_FEW = "\U0001f534"  # 🔴

# Per wire: some_min <= n < lots_min -> Some; n >= lots_min -> Lots; n < some_min -> None/Few (includes 0).
# Require 0 < some_min < lots_min.
COUNT_TIER_THRESHOLDS: dict[str, tuple[int, int]] = {
    "lizard": (1, 2),
    "pearl": (20, 60),
    "peridot": (20, 60),
    "mb3": (3, 6),
    "mb4": (1, 2),
    "mb5": (1, 2),
}

# Sort: Lots first, then Some, then Few, then ? (unknown count), then blank.
TIER_SORT_RANK: dict[str, int] = {
    TIER_EMOJI_LOTS: 0,
    TIER_EMOJI_SOME: 1,
    TIER_EMOJI_FEW: 2,
    "?": 3,
    "": 4,
}

# Readiness (R) column: green > yellow > ? > red > blank.
READINESS_UNKNOWN_MARK = "?"
READINESS_COLUMN_SORT_RANK: dict[str, int] = {
    TIER_EMOJI_LOTS: 0,
    TIER_EMOJI_SOME: 1,
    READINESS_UNKNOWN_MARK: 2,
    TIER_EMOJI_FEW: 3,
    "": 4,
}


def readiness_column_sort_key(display: str) -> int:
    """Sort key for readiness column; includes ? when data is incomplete."""
    return READINESS_COLUMN_SORT_RANK.get(display, 4)


def stack_count_tier_emoji(wire: str, value: object) -> str:
    """Return tier emoji for *value* or empty string if unknown."""
    text, _tip = stack_count_cell_parts(wire, value)
    return text


def stack_count_cell_parts(wire: str, value: object) -> tuple[str, str]:
    """Return (cell_text, tooltip) for a stack-count column. Tooltip is empty when cell is empty."""
    if value is None:
        return "", ""
    if value is True:
        n = 1
    else:
        try:
            n = int(value)  # bool False -> 0; numeric strings OK
        except (TypeError, ValueError):
            return "", ""

    thresholds = COUNT_TIER_THRESHOLDS.get(wire)
    if not thresholds:
        return "", ""

    some_min, lots_min = thresholds
    if not (0 < some_min < lots_min):
        return "", ""

    # Lizard Blood: 0 pots is empty cell, not the red "few" tier.
    if wire == "lizard" and n == 0:
        return "", ""

    if n >= lots_min:
        emoji = TIER_EMOJI_LOTS
    elif n >= some_min:
        emoji = TIER_EMOJI_SOME
    else:
        emoji = TIER_EMOJI_FEW

    return emoji, str(n)


def count_column_sort_key(display_emoji: str) -> int:
    """Sort key for CT / CH tier columns: green > yellow > red > ? > blank."""
    return TIER_SORT_RANK.get(display_emoji, 3)


def _ch_tooltip(neck: object, void: object, mb4: object) -> str:
    """Multi-line CH bundle: status of each input and how it feeds the tier."""
    lines: list[str] = []

    if neck is True:
        lines.append("Necklace of Resolution: yes")
    elif neck is False:
        lines.append("Necklace of Resolution: no")
    else:
        lines.append("Necklace of Resolution: unknown (no data)")

    if void is True:
        lines.append("Box of the Void: yes")
    elif void is False:
        lines.append("Box of the Void: no")
    else:
        lines.append("Box of the Void: unknown (no data)")

    mb4_ok = False
    if mb4 is None:
        lines.append("Mana Battery (Class Four): unknown (no data)")
    else:
        try:
            n = int(mb4)
            mb4_ok = n > 0
            lines.append(f"Mana Battery (Class Four): {n} (stack count; >0 required for green)")
        except (TypeError, ValueError):
            lines.append("Mana Battery (Class Four): unknown (not a number)")

    void_ok = void is True
    neck_ok = neck is True
    green_ok = neck_ok and void_ok and mb4_ok
    lines.append("")
    lines.append("Green tier needs: necklace yes, void yes, MB4 count > 0.")
    if neck is None:
        lines.append("Cell is blank when necklace status is unknown.")
    else:
        lines.append(f"Green bundle met: {'yes' if green_ok else 'no'} (yellow if necklace yes but not all green).")
    return "\n".join(lines)


def ch_bundle_cell_parts(neck: object, void: object, mb4: object) -> tuple[str, str]:
    """CH bundle column: green / yellow from neck, void, mb4; blank if neck unknown or no necklace."""
    if neck is None:
        return "", ""
    if neck is False:
        return "", ""
    if neck is not True:
        return "", ""

    void_ok = void is True
    mb4_ok = False
    if mb4 is not None:
        try:
            mb4_ok = int(mb4) > 0
        except (TypeError, ValueError):
            mb4_ok = False

    tip = _ch_tooltip(neck, void, mb4)
    if void_ok and mb4_ok:
        return TIER_EMOJI_LOTS, tip
    return TIER_EMOJI_SOME, tip


# Readiness sub-check rank: 0 = green, 1 = yellow/partial, 2 = red/fail, 3 = missing/unknown input.
_READINESS_RED = 2
_READINESS_YELLOW = 1
_READINESS_GREEN = 0
_READINESS_MISSING = 3


def _readiness_rank_from_tier_emoji(emoji: str) -> int:
    if emoji == TIER_EMOJI_LOTS:
        return _READINESS_GREEN
    if emoji == TIER_EMOJI_FEW:
        return _READINESS_RED
    if emoji == TIER_EMOJI_SOME:
        return _READINESS_YELLOW
    if not emoji:
        return _READINESS_MISSING
    return _READINESS_YELLOW


def _readiness_rank_thurg(thurg: object) -> int:
    if thurg is True:
        return _READINESS_GREEN
    if thurg is False:
        return _READINESS_RED
    return _READINESS_MISSING


def _readiness_roll_up(ranks: list[int]) -> str:
    """Worst-of rollup: unknown first; all green → green; any green + any non-green → yellow (mixed)."""
    if any(r == _READINESS_MISSING for r in ranks):
        return READINESS_UNKNOWN_MARK
    if all(r == _READINESS_GREEN for r in ranks):
        return TIER_EMOJI_LOTS
    has_green = any(r == _READINESS_GREEN for r in ranks)
    if has_green:
        return TIER_EMOJI_SOME
    if any(r == _READINESS_RED for r in ranks):
        return TIER_EMOJI_FEW
    return TIER_EMOJI_SOME


def _thurg_label(thurg: object) -> str:
    if thurg is True:
        return "has vial"
    if thurg is False:
        return "no vial"
    return "unknown"


def _thurg_readiness_tooltip_lines(thurg: object) -> list[str]:
    """Thurgpot line for Cleric readiness: tier emoji + explicit color matches R-column rollup."""
    header = "Th — Thurgpot (Vial of Velium Vapors):"
    if thurg is True:
        return [
            header,
            f"  {TIER_EMOJI_LOTS} green — {_thurg_label(thurg)}",
        ]
    if thurg is False:
        return [
            header,
            f"  {TIER_EMOJI_FEW} red — {_thurg_label(thurg)}",
        ]
    return [
        header,
        f"  {READINESS_UNKNOWN_MARK} unknown — vial status {_thurg_label(thurg)}",
    ]


def _readiness_stack_detail_lines(title: str, wire: str, value: object) -> list[str]:
    """Count + tier + thresholds for a stack wire (e.g. pearl not shown elsewhere in the table)."""
    th = COUNT_TIER_THRESHOLDS.get(wire)
    if not th:
        return [f"{title}: (no thresholds for wire {wire!r})"]
    some_min, lots_min = th
    emoji, count_tip = stack_count_cell_parts(wire, value)
    if not emoji:
        return [
            f"{title}: count unknown",
            f"  Need ≥{lots_min} for Lots, ≥{some_min} for Some tier.",
        ]
    return [
        f"{title}: {count_tip} in inventory",
        f"  Tier {emoji} — Lots ≥{lots_min}, Some ≥{some_min} — needs Lots for readiness.",
    ]


def _readiness_ch_bundle_lines(items: dict[str, object], ch_emoji: str) -> list[str]:
    neck = items.get("neck")
    void = items.get("void")
    mb4 = items.get("mb4")
    n = "yes" if neck is True else ("no" if neck is False else "?")
    v = "yes" if void is True else ("no" if void is False else "?")
    if mb4 is None:
        mb4_s = "?"
    else:
        try:
            mb4_s = str(int(mb4))
        except (TypeError, ValueError):
            mb4_s = "?"
    return [
        f"CH bundle: {ch_emoji or '—'}",
        f"  Necklace: {n} · Void: {v} · MB4: {mb4_s}",
    ]


def readiness_cell_parts(class_name: str | None, items: dict[str, object]) -> tuple[str, str]:
    """Overall class readiness (R column). Empty when no profile exists for this class."""
    if not class_name:
        return "", ""

    if class_name == "Cleric":
        neck_v = items.get("neck")
        ch_emoji, _ = ch_bundle_cell_parts(
            neck_v,
            items.get("void"),
            items.get("mb4"),
        )
        mb3_emoji = stack_count_tier_emoji("mb3", items.get("mb3"))
        r_mb3 = _readiness_rank_from_tier_emoji(mb3_emoji)
        r_tp = _readiness_rank_thurg(items.get("thurg"))
        ranks = [r_mb3, r_tp]
        if ch_emoji:
            ranks.insert(0, _readiness_rank_from_tier_emoji(ch_emoji))
        out = _readiness_roll_up(ranks)
        lines = [
            f"Cleric — overall {out}",
            "",
            *_readiness_ch_bundle_lines(items, ch_emoji),
            "",
            *_readiness_stack_detail_lines("MB3 (Class Three battery)", "mb3", items.get("mb3")),
            "",
            *_thurg_readiness_tooltip_lines(items.get("thurg")),
        ]
        return out, "\n".join(lines)

    if class_name == "Magician":
        pearl_val = items.get("pearl")
        # Unknown count is not "Some tier" — avoid yellow (that implies a known partial stack).
        if pearl_val is None:
            lines = [
                "Magician — no status until pearl count is known",
                "",
                *_readiness_stack_detail_lines("Pearl", "pearl", pearl_val),
            ]
            return READINESS_UNKNOWN_MARK, "\n".join(lines)
        pearl_emoji = stack_count_tier_emoji("pearl", pearl_val)
        r_pearl = _readiness_rank_from_tier_emoji(pearl_emoji)
        out = _readiness_roll_up([r_pearl])
        lines = [
            f"Magician — overall {out}",
            "",
            *_readiness_stack_detail_lines("Pearl", "pearl", pearl_val),
        ]
        return out, "\n".join(lines)

    return "", ""
