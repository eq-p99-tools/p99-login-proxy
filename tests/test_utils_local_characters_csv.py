"""Tests for local-character CSV persistence in :mod:`p99_sso_login_proxy.utils`."""

from __future__ import annotations

import csv

from p99_sso_login_proxy import utils


def _sample_entry(**overrides) -> dict:
    entry = {
        "name": "Toald",
        "account": "toaldsaccount",
        "class": "Cleric",
        "level": 60,
        "bind": "East Commonlands",
        "park": "Plane of Knowledge",
        "items": {
            # Bool items
            "seb": True,
            "vp": False,
            "st": None,
            "void": True,
            "neck": False,
            "thurg": None,
            "reaper": True,
            "brass_idol": None,
            # Count items
            "lizard": 5,
            "pearl": 12,
            "peridot": 0,
            "mb3": None,
            "mb4": 3,
            "mb5": None,
        },
    }
    entry.update(overrides)
    return entry


def test_load_missing_file_creates_header_only_file(tmp_path):
    path = tmp_path / "local_characters.csv"
    assert not path.exists()

    out = utils.load_local_characters(str(path))

    assert out == {}
    assert path.exists()
    with open(path) as f:
        header = next(csv.reader(f))
    assert tuple(header) == utils.LOCAL_CHARACTER_FIELDS


def test_save_then_load_roundtrip_preserves_entry(tmp_path):
    path = tmp_path / "local_characters.csv"
    entry = _sample_entry()
    characters = {"toald": entry}

    assert utils.save_local_characters(characters, str(path)) is True

    loaded = utils.load_local_characters(str(path))
    assert set(loaded) == {"toald"}
    out = loaded["toald"]

    assert out["name"] == "Toald"
    assert out["account"] == "toaldsaccount"
    assert out["class"] == "Cleric"
    assert out["level"] == 60
    assert out["bind"] == "East Commonlands"
    assert out["park"] == "Plane of Knowledge"

    # Items round-trip: bool items preserve True/False/None, counts preserve ints and None.
    items = out["items"]
    assert items["seb"] is True
    assert items["vp"] is False
    assert items["st"] is None
    assert items["reaper"] is True
    assert items["lizard"] == 5
    assert items["pearl"] == 12
    assert items["peridot"] == 0
    assert items["mb3"] is None
    assert items["mb4"] == 3


def test_load_skips_rows_with_empty_name(tmp_path):
    path = tmp_path / "local_characters.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(utils.LOCAL_CHARACTER_FIELDS)
        # Valid row
        writer.writerow(
            [
                "acct1",
                "Alice",
                "Warrior",
                "50",
                "Bind",
                "",
                *[""] * len(utils.LOCAL_CHARACTER_BOOL_ITEMS),
                *[""] * len(utils.LOCAL_CHARACTER_COUNT_ITEMS),
            ]
        )
        # Skipped row: empty name
        writer.writerow(
            [
                "acct2",
                "",
                "",
                "",
                "",
                "",
                *[""] * len(utils.LOCAL_CHARACTER_BOOL_ITEMS),
                *[""] * len(utils.LOCAL_CHARACTER_COUNT_ITEMS),
            ]
        )

    out = utils.load_local_characters(str(path))
    assert set(out) == {"alice"}
    assert out["alice"]["name"] == "Alice"
    assert out["alice"]["level"] == 50
    assert out["alice"]["class"] == "Warrior"


def test_load_tolerates_bad_level_and_bool(tmp_path):
    path = tmp_path / "local_characters.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(utils.LOCAL_CHARACTER_FIELDS)
        row = [
            "acct",
            "Bob",
            "Wizard",
            "notanumber",  # bad level -> None
            "",
            "",
        ]
        row.extend(["maybe"] + [""] * (len(utils.LOCAL_CHARACTER_BOOL_ITEMS) - 1))  # first bool: unknown
        row.extend(["x"] + [""] * (len(utils.LOCAL_CHARACTER_COUNT_ITEMS) - 1))  # first count: unknown
        writer.writerow(row)

    out = utils.load_local_characters(str(path))
    assert out["bob"]["level"] is None
    assert out["bob"]["items"][utils.LOCAL_CHARACTER_BOOL_ITEMS[0]] is None
    assert out["bob"]["items"][utils.LOCAL_CHARACTER_COUNT_ITEMS[0]] is None


def test_save_writes_sorted_by_key(tmp_path):
    path = tmp_path / "local_characters.csv"
    characters = {
        "charlie": _sample_entry(name="Charlie", account="c"),
        "alice": _sample_entry(name="Alice", account="a"),
        "bob": _sample_entry(name="Bob", account="b"),
    }
    assert utils.save_local_characters(characters, str(path)) is True

    with open(path) as f:
        rows = list(csv.reader(f))
    # header + three data rows
    assert rows[0] == list(utils.LOCAL_CHARACTER_FIELDS)
    data_names = [row[1] for row in rows[1:]]
    assert data_names == ["Alice", "Bob", "Charlie"]
