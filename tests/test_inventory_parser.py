"""Tests for ``p99_sso_login_proxy.inventory_parser``."""

from __future__ import annotations

from p99_sso_login_proxy import inventory_parser


def _write_inv(tmp_path, body: str) -> str:
    p = tmp_path / "Toald-Inventory.txt"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_parse_empty_file(tmp_path):
    path = _write_inv(tmp_path, "")
    r = inventory_parser.parse_inventory_file(path)
    assert r["pearl"] == 0
    assert r["lizard"] == 0
    assert r["reaper"] is False
    assert set(r.keys()) == set(inventory_parser.ALL_INVENTORY_WIRE_KEYS)


def test_parse_sums_pearl_counts(tmp_path):
    path = _write_inv(
        tmp_path,
        "Location\tName\tID\tCount\tSlots\nG1\tPearl\t13073\t3\t5\nG2\tPearl\t13073\t20\t5\nG3\tPearl\t13073\t20\t5\n",
    )
    r = inventory_parser.parse_inventory_file(path)
    assert r["pearl"] == 43
    assert r["peridot"] == 0


def test_parse_peridot_and_pearl(tmp_path):
    path = _write_inv(
        tmp_path,
        "Location\tName\tID\tCount\tSlots\nA\tPeridot\t1\t10\t5\nB\tPearl\t1\t5\t5\n",
    )
    r = inventory_parser.parse_inventory_file(path)
    assert r["peridot"] == 10
    assert r["pearl"] == 5


def test_parse_presence_flags(tmp_path):
    path = _write_inv(
        tmp_path,
        "Location\tName\tID\tCount\tSlots\n"
        "X\tReaper of the Dead\t1\t1\t5\n"
        "Y\tShiny Brass Idol\t2\t1\t5\n"
        "Z\tTrakanon Idol\t3\t1\t5\n",
    )
    r = inventory_parser.parse_inventory_file(path)
    assert r["reaper"] is True
    assert r["brass_idol"] is True
    assert r["seb"] is True


def test_character_name_from_path():
    assert inventory_parser.character_name_from_inventory_path(r"C:\eq\Toald-Inventory.txt") == "Toald"


def test_parse_sums_lizard_blood_potion_stacks(tmp_path):
    path = _write_inv(
        tmp_path,
        "Location\tName\tID\tCount\tSlots\nG1\tLizard Blood Potion\t1\t5\t5\nG2\tLizard Blood Potion\t1\t3\t5\n",
    )
    r = inventory_parser.parse_inventory_file(path)
    assert r["lizard"] == 8


def test_parse_mana_battery_counts(tmp_path):
    path = _write_inv(
        tmp_path,
        "Location\tName\tID\tCount\tSlots\n"
        "A\tMana Battery - Class Three\t1\t2\t5\n"
        "B\tMana Battery - Class Four\t2\t1\t5\n"
        "C\tMana Battery - Class Five\t3\t4\t5\n",
    )
    r = inventory_parser.parse_inventory_file(path)
    assert r["mb3"] == 2
    assert r["mb4"] == 1
    assert r["mb5"] == 4


def test_bad_count_cell_skipped(tmp_path):
    path = _write_inv(
        tmp_path,
        "Location\tName\tID\tCount\tSlots\nA\tPearl\t1\tx\t5\nB\tPearl\t1\t7\t5\n",
    )
    r = inventory_parser.parse_inventory_file(path)
    assert r["pearl"] == 7
