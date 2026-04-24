"""Integrity tests for :mod:`p99_sso_login_proxy.readiness_by_class`.

The module-level ``assert`` in ``readiness_by_class`` already guarantees
CLASSES/READINESS_BY_CLASS are in sync at import time, but duplicating it as a
test keeps the guarantee visible in test reports.
"""

from __future__ import annotations

import pytest

from p99_sso_login_proxy import class_translate, readiness_by_class


def test_readiness_keys_match_class_roster():
    assert set(readiness_by_class.READINESS_BY_CLASS) == set(class_translate.CLASSES)


@pytest.mark.parametrize("klass", class_translate.CLASSES)
def test_dispatch_readiness_returns_tuple_of_two_strings(klass):
    # Call with an empty items dict; stub classes return ("", "") and
    # implemented classes still return a (str, str) tuple.
    result = readiness_by_class.dispatch_readiness(klass, {})
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], str)
    assert isinstance(result[1], str)


def test_dispatch_readiness_unknown_class_blank():
    assert readiness_by_class.dispatch_readiness(None, {}) == ("", "")
    assert readiness_by_class.dispatch_readiness("", {}) == ("", "")
    assert readiness_by_class.dispatch_readiness("NotAClass", {}) == ("", "")


def test_dispatch_readiness_magician_unknown_pearl():
    # Magician has a real implementation: with no pearl count known, cell
    # should surface the "unknown" mark rather than an empty string.
    cell, tooltip = readiness_by_class.dispatch_readiness("Magician", {})
    from p99_sso_login_proxy import count_display

    assert cell == count_display.READINESS_UNKNOWN_MARK
    assert "Magician" in tooltip
