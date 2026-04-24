"""Per-class readiness (R column): one function per EQ class returning (emoji, tooltip).

Implementations can grow arbitrarily; stubs return blank until filled in. Dispatch from
``count_display.readiness_cell_parts`` to avoid circular imports with ``count_display``."""

from __future__ import annotations

from collections.abc import Callable

from p99_sso_login_proxy import class_translate
from p99_sso_login_proxy import count_display as cd

ReadinessFn = Callable[[dict[str, object]], tuple[str, str]]


def readiness_bard(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


def readiness_cleric(items: dict[str, object]) -> tuple[str, str]:
    neck_v = items.get("neck")
    ch_emoji, _ = cd.ch_bundle_cell_parts(
        neck_v,
        items.get("void"),
        items.get("mb4"),
    )
    mb3_emoji = cd.stack_count_tier_emoji("mb3", items.get("mb3"))
    r_mb3 = cd._readiness_rank_from_tier_emoji(mb3_emoji)
    r_tp = cd._readiness_rank_thurg(items.get("thurg"))
    ranks = [r_mb3, r_tp]
    if ch_emoji:
        ranks.insert(0, cd._readiness_rank_from_tier_emoji(ch_emoji))
    out = cd._readiness_roll_up(ranks)
    lines = [
        f"Cleric — overall {out}",
        "",
        *cd._readiness_ch_bundle_lines(items, ch_emoji),
        "",
        *cd._readiness_stack_detail_lines("MB3 (Class Three battery)", "mb3", items.get("mb3")),
        "",
        *cd._thurg_readiness_tooltip_lines(items.get("thurg")),
    ]
    return out, "\n".join(lines)


def readiness_druid(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


def readiness_enchanter(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


def readiness_magician(items: dict[str, object]) -> tuple[str, str]:
    pearl_val = items.get("pearl")
    if pearl_val is None:
        lines = [
            "Magician — no status until pearl count is known",
            "",
            *cd._readiness_stack_detail_lines("Pearl", "pearl", pearl_val),
        ]
        return cd.READINESS_UNKNOWN_MARK, "\n".join(lines)
    pearl_emoji = cd.stack_count_tier_emoji("pearl", pearl_val)
    r_pearl = cd._readiness_rank_from_tier_emoji(pearl_emoji)
    out = cd._readiness_roll_up([r_pearl])
    lines = [
        f"Magician — overall {out}",
        "",
        *cd._readiness_stack_detail_lines("Pearl", "pearl", pearl_val),
    ]
    return out, "\n".join(lines)


def readiness_monk(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


def readiness_necromancer(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


def readiness_paladin(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


def readiness_ranger(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


def readiness_rogue(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


def readiness_shadow_knight(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


def readiness_shaman(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


def readiness_warrior(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


def readiness_wizard(_items: dict[str, object]) -> tuple[str, str]:
    return "", ""


_READINESS_FUNCTIONS: dict[str, ReadinessFn] = {
    "Bard": readiness_bard,
    "Cleric": readiness_cleric,
    "Druid": readiness_druid,
    "Enchanter": readiness_enchanter,
    "Magician": readiness_magician,
    "Monk": readiness_monk,
    "Necromancer": readiness_necromancer,
    "Paladin": readiness_paladin,
    "Ranger": readiness_ranger,
    "Rogue": readiness_rogue,
    "ShadowKnight": readiness_shadow_knight,
    "Shaman": readiness_shaman,
    "Warrior": readiness_warrior,
    "Wizard": readiness_wizard,
}

# Assert every canonical class has a readiness function so silent gaps fail loud
# if CLASSES grows and a function is forgotten.
assert set(_READINESS_FUNCTIONS) == set(class_translate.CLASSES), (
    f"readiness functions out of sync with class_translate.CLASSES: "
    f"missing={set(class_translate.CLASSES) - set(_READINESS_FUNCTIONS)}, "
    f"extra={set(_READINESS_FUNCTIONS) - set(class_translate.CLASSES)}"
)

READINESS_BY_CLASS: dict[str, ReadinessFn] = {cls: _READINESS_FUNCTIONS[cls] for cls in class_translate.CLASSES}


def dispatch_readiness(class_name: str | None, items: dict[str, object]) -> tuple[str, str]:
    """Return (cell emoji, tooltip) for the R column, or blank when no handler."""
    if not class_name:
        return "", ""
    fn = READINESS_BY_CLASS.get(class_name)
    if fn is None:
        return "", ""
    return fn(items)
