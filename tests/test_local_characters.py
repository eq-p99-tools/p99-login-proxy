"""Tests for :mod:`p99_sso_login_proxy.local_characters`.

Covers the state machine that pairs the most-recent local login with the next
new EQ log file, plus ``apply_update`` / ``set_entry`` / ``delete_entry``.
"""

from __future__ import annotations

from p99_sso_login_proxy import config, local_characters


def _seed_local_account(name: str = "acct1", password: str = "pw") -> None:
    """Register a local account so ``try_auto_create`` treats it as valid."""
    config.LOCAL_ACCOUNTS[name.lower()] = {"password": password, "aliases": []}


# ---- note_login -----------------------------------------------------------


def test_note_login_local_sets_pending():
    local_characters.note_login("local", "ACCT1")
    assert local_characters._pending_local_account == "acct1"


def test_note_login_local_char_sets_pending():
    local_characters.note_login("local_char", "acct1")
    assert local_characters._pending_local_account == "acct1"


def test_note_login_sso_clears_pending():
    local_characters.note_login("local", "acct1")
    assert local_characters._pending_local_account == "acct1"

    local_characters.note_login("sso", "acct1")
    assert local_characters._pending_local_account is None


def test_note_login_passthrough_clears_pending():
    local_characters.note_login("local", "acct1")
    local_characters.note_login("passthrough", "whatever")
    assert local_characters._pending_local_account is None


def test_note_login_local_with_no_account_clears_pending():
    local_characters.note_login("local", "acct1")
    local_characters.note_login("local", None)
    assert local_characters._pending_local_account is None


# ---- try_auto_create ------------------------------------------------------


def test_try_auto_create_no_pending_returns_false():
    assert local_characters.try_auto_create("Toald") is False
    assert "toald" not in config.LOCAL_CHARACTERS


def test_try_auto_create_happy_path_adds_row():
    _seed_local_account("acct1")
    local_characters.note_login("local", "acct1")

    assert local_characters.try_auto_create("Toald") is True

    assert "toald" in config.LOCAL_CHARACTER_NAMES
    entry = config.LOCAL_CHARACTERS["toald"]
    assert entry["name"] == "Toald"
    assert entry["account"] == "acct1"
    assert entry["class"] is None
    assert entry["level"] is None


def test_try_auto_create_local_char_method_seeds_pending():
    _seed_local_account("acct1")
    local_characters.note_login("local_char", "acct1")

    assert local_characters.try_auto_create("Toald") is True
    assert config.LOCAL_CHARACTERS["toald"]["account"] == "acct1"


def test_try_auto_create_disabled_by_config_flag():
    _seed_local_account("acct1")
    local_characters.note_login("local", "acct1")
    config.AUTO_ADD_LOCAL_CHARACTERS = False

    assert local_characters.try_auto_create("Toald") is False
    assert "toald" not in config.LOCAL_CHARACTER_NAMES


def test_try_auto_create_pending_account_missing_skips_and_warns(caplog):
    # Pending account exists on the slot but was since deleted from local_accounts.csv.
    local_characters.note_login("local", "ghost")
    config.LOCAL_ACCOUNTS.pop("ghost", None)

    with caplog.at_level("WARNING", logger="p99_sso_login_proxy.local_characters"):
        assert local_characters.try_auto_create("Toald") is False

    assert "toald" not in config.LOCAL_CHARACTER_NAMES
    assert any("no longer in local_accounts" in rec.message for rec in caplog.records)


def test_try_auto_create_collision_preserves_existing_binding(caplog):
    # Existing row bound to acctA.
    _seed_local_account("accta")
    _seed_local_account("acctb")
    local_characters.set_entry(
        {"name": "Toald", "account": "accta", "class": None, "level": None, "bind": None, "park": None, "items": {}}
    )
    # Log in as a different local account, then hit the auto-add path.
    local_characters.note_login("local", "acctb")

    with caplog.at_level("WARNING", logger="p99_sso_login_proxy.local_characters"):
        assert local_characters.try_auto_create("Toald") is False

    assert config.LOCAL_CHARACTERS["toald"]["account"] == "accta"
    assert any("not overwriting" in rec.message for rec in caplog.records)


def test_try_auto_create_collision_same_account_is_noop():
    _seed_local_account("acct1")
    local_characters.set_entry(
        {"name": "Toald", "account": "acct1", "class": None, "level": None, "bind": None, "park": None, "items": {}}
    )
    local_characters.note_login("local", "acct1")

    # No new row created, no warning — existing row already correct.
    assert local_characters.try_auto_create("Toald") is False
    assert config.LOCAL_CHARACTERS["toald"]["account"] == "acct1"


def test_try_auto_create_two_consecutive_characters():
    _seed_local_account("acct1")
    _seed_local_account("acct2")

    local_characters.note_login("local", "acct1")
    assert local_characters.try_auto_create("Alice") is True

    local_characters.note_login("local", "acct2")
    assert local_characters.try_auto_create("Bob") is True

    assert config.LOCAL_CHARACTERS["alice"]["account"] == "acct1"
    assert config.LOCAL_CHARACTERS["bob"]["account"] == "acct2"


def test_try_auto_create_empty_name_is_noop():
    _seed_local_account("acct1")
    local_characters.note_login("local", "acct1")

    assert local_characters.try_auto_create("") is False
    assert "" not in config.LOCAL_CHARACTER_NAMES


# ---- apply_update ---------------------------------------------------------


def test_apply_update_only_runs_for_known_characters():
    assert local_characters.apply_update("Unknown", klass="Cleric") is False
    assert "unknown" not in config.LOCAL_CHARACTERS


def test_apply_update_sets_class_level_bind_park():
    local_characters.set_entry(
        {"name": "Toald", "account": "acct1", "class": None, "level": None, "bind": None, "park": None, "items": {}}
    )

    changed = local_characters.apply_update(
        "Toald",
        klass="Cleric",
        level=60,
        bind="East Commonlands",
        park="Plane of Knowledge",
    )
    assert changed is True

    e = config.LOCAL_CHARACTERS["toald"]
    assert e["class"] == "Cleric"
    assert e["level"] == 60
    assert e["bind"] == "East Commonlands"
    assert e["park"] == "Plane of Knowledge"


def test_apply_update_no_change_returns_false():
    local_characters.set_entry(
        {"name": "Toald", "account": "acct1", "class": "Cleric", "level": 60, "bind": None, "park": None, "items": {}}
    )
    assert local_characters.apply_update("Toald", klass="Cleric", level=60) is False


def test_apply_update_merges_items():
    local_characters.set_entry(
        {
            "name": "Toald",
            "account": "acct1",
            "class": "Cleric",
            "level": 60,
            "bind": None,
            "park": None,
            "items": {"pearl": 5, "reaper": False},
        }
    )

    changed = local_characters.apply_update("Toald", items={"pearl": 12, "reaper": True, "lizard": 3})
    assert changed is True
    items = config.LOCAL_CHARACTERS["toald"]["items"]
    assert items["pearl"] == 12
    assert items["reaper"] is True
    assert items["lizard"] == 3


# ---- delete_entry ---------------------------------------------------------


def test_delete_entry_removes_from_name_set_and_dict():
    local_characters.set_entry(
        {"name": "Toald", "account": "acct1", "class": None, "level": None, "bind": None, "park": None, "items": {}}
    )
    assert "toald" in config.LOCAL_CHARACTER_NAMES

    assert local_characters.delete_entry("Toald") is True
    assert "toald" not in config.LOCAL_CHARACTERS
    assert "toald" not in config.LOCAL_CHARACTER_NAMES
    assert local_characters.delete_entry("Toald") is False
