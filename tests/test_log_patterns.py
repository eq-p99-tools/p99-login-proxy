"""Tests for the EQ log regexes in :mod:`p99_sso_login_proxy.config`.

The biggest risk is ``MATCH_WHO_SELF`` because we recently extended it to
capture ``klass`` alongside ``level`` and ``name`` so local-character class can
be inferred from a ``/who`` self-line. These tests lock that capture in.
"""

from __future__ import annotations

import pytest

from p99_sso_login_proxy import config

_TS = "[Mon Jul 22 23:08:38 2024] "


# ---- MATCH_WHO_SELF ------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected_level", "expected_klass", "expected_name"),
    [
        (f"{_TS}[45 Cleric] Toald (Human) <Kingdom> ZONE: eastcommons", 45, "Cleric", "Toald"),
        (f"{_TS}[60 Warlord] Gruthar (Ogre) <Kingdom> ZONE: feerrott", 60, "Warlord", "Gruthar"),
        (f"{_TS}[60 Shadow Knight] Skele (Iksar) <Kingdom> ZONE: cabeast", 60, "Shadow Knight", "Skele"),
        (f"{_TS}[60 Grave Lord] Skele (Iksar) ZONE: cabeast", 60, "Grave Lord", "Skele"),
    ],
)
def test_match_who_self_captures_level_klass_name(line, expected_level, expected_klass, expected_name):
    m = config.MATCH_WHO_SELF.match(line)
    assert m is not None, line
    assert int(m.group("level")) == expected_level
    assert m.group("klass") == expected_klass
    assert m.group("name") == expected_name


def test_match_who_self_does_not_match_other_lines():
    assert config.MATCH_WHO_SELF.match(f"{_TS}You have entered East Commonlands.") is None
    assert config.MATCH_WHO_SELF.match(f"{_TS}There are 12 players in East Commonlands.") is None


# ---- MATCH_ENTERED_ZONE / MATCH_WHO_ZONE / MATCH_CHARINFO / MATCH_BIND_CONFIRM ----


def test_match_entered_zone_captures_zone_name():
    m = config.MATCH_ENTERED_ZONE.match(f"{_TS}You have entered East Commonlands.")
    assert m is not None
    assert m.group("zone") == "East Commonlands"


def test_match_who_zone_captures_player_count_and_zone():
    m = config.MATCH_WHO_ZONE.match(f"{_TS}There are 12 players in East Commonlands.")
    assert m is not None
    assert m.group("num") == "12"
    assert m.group("zone") == "East Commonlands"

    m = config.MATCH_WHO_ZONE.match(f"{_TS}There is 1 player in East Commonlands.")
    assert m is not None
    assert m.group("num") == "1"


def test_match_charinfo_captures_bind_zone():
    m = config.MATCH_CHARINFO.match(f"{_TS}You are currently bound in: East Commonlands")
    assert m is not None
    assert m.group("zone") == "East Commonlands"


def test_match_bind_confirm_fires_on_rebind_line():
    assert config.MATCH_BIND_CONFIRM.match(f"{_TS}You feel yourself bind to the area.") is not None
    assert config.MATCH_BIND_CONFIRM.match(f"{_TS}You feel yourself bind to the area") is None
