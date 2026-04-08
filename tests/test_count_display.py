"""Tests for stack-count tier emoji display (UI layer)."""

from __future__ import annotations

from p99_sso_login_proxy import count_display


def test_stack_count_unknown_empty():
    text, tip = count_display.stack_count_cell_parts("lizard", None)
    assert text == "" and tip == ""


def test_stack_count_lizard_tiers():
    # lizard thresholds from COUNT_TIER_THRESHOLDS (some_min, lots_min)
    sm, lm = count_display.COUNT_TIER_THRESHOLDS["lizard"]
    assert count_display.stack_count_cell_parts("lizard", 0)[0] == ""
    if sm > 1:
        assert count_display.stack_count_cell_parts("lizard", sm - 1)[0] == count_display.TIER_EMOJI_FEW
    assert count_display.stack_count_cell_parts("lizard", sm)[0] == count_display.TIER_EMOJI_SOME
    assert count_display.stack_count_cell_parts("lizard", lm - 1)[0] == count_display.TIER_EMOJI_SOME
    assert count_display.stack_count_cell_parts("lizard", lm)[0] == count_display.TIER_EMOJI_LOTS
    assert count_display.stack_count_cell_parts("lizard", 100)[1] == "100"


def test_count_column_sort_key_order():
    assert count_display.count_column_sort_key(count_display.TIER_EMOJI_LOTS) < count_display.count_column_sort_key(
        count_display.TIER_EMOJI_SOME
    )
    assert count_display.count_column_sort_key(count_display.TIER_EMOJI_SOME) < count_display.count_column_sort_key(
        count_display.TIER_EMOJI_FEW
    )
    assert count_display.count_column_sort_key(count_display.TIER_EMOJI_FEW) < count_display.count_column_sort_key("?")
    assert count_display.count_column_sort_key("?") < count_display.count_column_sort_key("")


def test_ch_bundle_unknown_neck_empty():
    text, tip = count_display.ch_bundle_cell_parts(None, True, 5)
    assert text == "" and tip == ""


def test_ch_bundle_green():
    g, _ = count_display.ch_bundle_cell_parts(True, True, 1)
    assert g == count_display.TIER_EMOJI_LOTS


def test_ch_bundle_yellow_when_neck_but_not_full_green():
    assert count_display.ch_bundle_cell_parts(True, True, 0)[0] == count_display.TIER_EMOJI_SOME
    assert count_display.ch_bundle_cell_parts(True, False, 99)[0] == count_display.TIER_EMOJI_SOME
    assert count_display.ch_bundle_cell_parts(True, None, 99)[0] == count_display.TIER_EMOJI_SOME


def test_ch_bundle_no_neck_blank():
    assert count_display.ch_bundle_cell_parts(False, True, 5)[0] == ""


def test_readiness_unknown_class_empty():
    e, tip = count_display.readiness_cell_parts("Warrior", {})
    assert e == "" and tip == ""


def test_readiness_cleric_all_green():
    lm = count_display.COUNT_TIER_THRESHOLDS["mb3"][1]
    items = {
        "neck": True,
        "void": True,
        "mb4": 1,
        "mb3": lm,
        "thurg": True,
    }
    e, tip = count_display.readiness_cell_parts("Cleric", items)
    assert e == count_display.TIER_EMOJI_LOTS
    assert "CH bundle" in tip


def test_readiness_cleric_tp_red_mixed_yellow():
    """TP red while CH + MB3 are green → mixed readiness shows yellow, not red."""
    lm = count_display.COUNT_TIER_THRESHOLDS["mb3"][1]
    items = {
        "neck": True,
        "void": True,
        "mb4": 1,
        "mb3": lm,
        "thurg": False,
    }
    e, _ = count_display.readiness_cell_parts("Cleric", items)
    assert e == count_display.TIER_EMOJI_SOME


def test_readiness_cleric_blank_ch_not_required():
    """No necklace CH column is blank; readiness ignores CH and only MB3 + TP."""
    lm = count_display.COUNT_TIER_THRESHOLDS["mb3"][1]
    items = {
        "neck": False,
        "void": True,
        "mb4": 1,
        "mb3": lm,
        "thurg": True,
    }
    e, _ = count_display.readiness_cell_parts("Cleric", items)
    assert e == count_display.TIER_EMOJI_LOTS


def test_readiness_magician_pearl_lots():
    plm = count_display.COUNT_TIER_THRESHOLDS["pearl"][1]
    e, _ = count_display.readiness_cell_parts("Magician", {"pearl": plm})
    assert e == count_display.TIER_EMOJI_LOTS


def test_readiness_magician_pearl_not_lots():
    sm = count_display.COUNT_TIER_THRESHOLDS["pearl"][0]
    e, _ = count_display.readiness_cell_parts("Magician", {"pearl": sm})
    assert e == count_display.TIER_EMOJI_SOME


def test_readiness_magician_pearl_unknown_question_mark():
    e, tip = count_display.readiness_cell_parts("Magician", {})
    assert e == count_display.READINESS_UNKNOWN_MARK
    assert "unknown" in tip.lower()


def test_readiness_cleric_unknown_mb3_question_mark():
    items = {
        "neck": True,
        "void": True,
        "mb4": 1,
        "mb3": None,
        "thurg": True,
    }
    e, _ = count_display.readiness_cell_parts("Cleric", items)
    assert e == count_display.READINESS_UNKNOWN_MARK
