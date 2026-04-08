"""Tests for Vial of Velium Vapors log line and update_location merge helper."""

from __future__ import annotations

from p99_sso_login_proxy import config
from p99_sso_login_proxy.ws_client import _merge_last_location_state


def test_match_velium_vapors_glow():
    line = "[Mon Jul 22 23:08:38 2024] Your Vial of Velium Vapors begins to glow."
    m = config.MATCH_VELIUM_VAPORS_GLOW.match(line)
    assert m is not None
    assert m.group("time") == "Mon Jul 22 23:08:38 2024"


def test_match_velium_vapors_glow_does_not_match_other_lines():
    assert config.MATCH_VELIUM_VAPORS_GLOW.match("[Mon Jul 22 23:08:38 2024] You begin casting Thurgadin Gate.") is None
    assert config.MATCH_VELIUM_VAPORS_GLOW.match("Your Vial of Velium Vapors begins to glow.") is None


def test_merge_last_location_state_merges_items():
    prev = {"park_location": "seb", "items": {"lizard": 5, "thurg": True}}
    data = {"items": {"thurg": False}}
    assert _merge_last_location_state(prev, data) == {
        "park_location": "seb",
        "items": {"lizard": 5, "thurg": False},
    }


def test_merge_last_location_state_dedup_unchanged_when_thurg_already_false():
    prev = {"items": {"thurg": False}}
    data = {"items": {"thurg": False}}
    assert _merge_last_location_state(prev, data) == prev
