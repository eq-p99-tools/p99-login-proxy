"""Sanity tests for :mod:`p99_sso_login_proxy.zone_translate`."""

from __future__ import annotations

import pytest

from p99_sso_login_proxy import zone_translate


@pytest.mark.parametrize(
    ("zone", "zonekey"),
    [
        ("East Commonlands", "ecommons"),
        ("South Qeynos", "qeynos"),
        ("Plane of Hate", "hateplane"),
        ("The Feerrott", "feerrott"),
        ("Kael Drakkel", "kael"),
        ("Old Sebilis", "sebilis"),  # /consider alias -> same zonekey
        ("Ruins of Sebilis", "sebilis"),
        ("West Karana", "qey2hh1"),  # historically awkward zonekey preserved
    ],
)
def test_zone_to_zonekey_aliased(zone, zonekey):
    assert zone_translate.zone_to_zonekey(zone) == zonekey


def test_zone_to_zonekey_falls_back_to_lowercased_input():
    # Zones not in the alias map should return the input lowercased.
    assert zone_translate.zone_to_zonekey("SomeUnmappedZone") == "someunmappedzone"


def test_zone_to_zonekey_empty_returns_none():
    assert zone_translate.zone_to_zonekey("") is None


@pytest.mark.parametrize(
    ("zonekey", "expected_prefix"),
    [
        ("ecommons", "East Commonlands"),
        ("feerrott", "The Feerrott"),
        ("qeynos", "South Qeynos"),
    ],
)
def test_zonekey_to_zone_title_cases_alias(zonekey, expected_prefix):
    assert zone_translate.zonekey_to_zone(zonekey) == expected_prefix


def test_zonekey_to_zone_unknown_title_cases_key():
    assert zone_translate.zonekey_to_zone("unknownzone") == "Unknownzone"


def test_zonekey_to_zone_empty_returns_none():
    assert zone_translate.zonekey_to_zone("") is None


def test_capitalize_multi_word():
    assert zone_translate.capitalize("east commonlands") == "East Commonlands"
    assert zone_translate.capitalize("plane of hate") == "Plane Of Hate"
