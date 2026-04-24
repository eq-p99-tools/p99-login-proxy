"""Tests for ``p99_sso_login_proxy.class_translate``."""

from __future__ import annotations

import pytest

from p99_sso_login_proxy import class_translate


def test_classes_roster_is_the_14_eq_classes():
    assert set(class_translate.CLASSES) == {
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
    }


def test_every_title_maps_to_a_real_class():
    # Catches typos in TITLE_TO_BASE_CLASS values.
    for title, klass in class_translate.TITLE_TO_BASE_CLASS.items():
        assert klass in class_translate.CLASSES, f"{title!r} -> {klass!r} not in CLASSES"


def test_base_aliases_cover_every_canonical_class():
    for klass in class_translate.CLASSES:
        assert class_translate.BASE_CLASS_ALIASES[klass.lower()] == klass


def test_shadow_knight_two_word_form_is_aliased():
    assert class_translate.BASE_CLASS_ALIASES["shadow knight"] == "ShadowKnight"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Warrior", "Warrior"),
        ("warrior", "Warrior"),
        ("  Warrior  ", "Warrior"),
        ("Shadow Knight", "ShadowKnight"),
        ("shadow  knight", "ShadowKnight"),  # collapsed whitespace
        ("ShadowKnight", "ShadowKnight"),
    ],
)
def test_resolve_class_base_forms(raw, expected):
    assert class_translate.resolve_class(raw) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Warlord", "Warrior"),  # 60 warrior
        ("Myrmidon", "Warrior"),  # 55 warrior
        ("Champion", "Warrior"),  # 51 warrior
        ("Grave Lord", "ShadowKnight"),  # 60 SK, two-word
        ("Grandmaster", "Monk"),
        ("High Priest", "Cleric"),
        ("Arch Mage", "Magician"),
    ],
)
def test_resolve_class_level60_titles(title, expected):
    assert class_translate.resolve_class(title) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "NotAClass", "Paladin Lord"])
def test_resolve_class_unknown_inputs_return_none(raw):
    assert class_translate.resolve_class(raw) is None
