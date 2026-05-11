"""Tests for the snapshot-and-replace eqhost.txt handling in eq_config.

These cover the public surface of the proxy toggle: enable_proxy, disable_proxy,
restore_backup, is_using_proxy, plus the read helpers' tolerance for
BOM / CRLF / whitespace.
"""

from __future__ import annotations

import os

import pytest

from p99_sso_login_proxy import eq_config


@pytest.fixture
def eqhost(tmp_path, monkeypatch):
    """Yield (eqhost_path, backup_path); both initially absent. Patches
    eq_config.get_eqhost_path so the proxy toggles operate on the temp file.
    """
    path = tmp_path / "eqhost.txt"
    backup = tmp_path / "eqhost.txt.bak"
    monkeypatch.setattr(eq_config, "get_eqhost_path", lambda *a, **kw: str(path))
    return path, backup


def _write(path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_enable_with_custom_content_snapshots_verbatim(eqhost):
    path, backup = eqhost
    _write(path, "Host=guild.example.com:5998\n# old comment\n")

    ok, err = eq_config.enable_proxy()

    assert ok and err is None
    assert path.read_text(encoding="utf-8") == eq_config.DEFAULT_PROXY_ADDRESS + "\n"
    assert backup.read_text(encoding="utf-8") == "Host=guild.example.com:5998\n# old comment\n"


def test_enable_does_not_overwrite_existing_backup(eqhost):
    path, backup = eqhost
    _write(path, "Host=guild.example.com:5998\n")
    _write(backup, "Host=preexisting.example.com:5998\n")

    ok, _ = eq_config.enable_proxy()

    assert ok
    assert backup.read_text(encoding="utf-8") == "Host=preexisting.example.com:5998\n"


def test_enable_when_already_proxy_only_writes_synthetic_default_backup(eqhost):
    path, backup = eqhost
    _write(path, eq_config.DEFAULT_PROXY_ADDRESS + "\n")

    ok, _ = eq_config.enable_proxy()

    assert ok
    assert path.read_text(encoding="utf-8") == eq_config.DEFAULT_PROXY_ADDRESS + "\n"
    assert backup.read_text(encoding="utf-8") == eq_config.DEFAULT_LOGIN_SERVER + "\n"


def test_enable_when_eqhost_missing_writes_synthetic_default_backup(eqhost):
    path, backup = eqhost
    assert not path.exists()

    ok, _ = eq_config.enable_proxy()

    assert ok
    assert path.read_text(encoding="utf-8") == eq_config.DEFAULT_PROXY_ADDRESS + "\n"
    assert backup.read_text(encoding="utf-8") == eq_config.DEFAULT_LOGIN_SERVER + "\n"


def test_enable_when_only_commented_hosts_writes_synthetic_default_backup(eqhost):
    path, backup = eqhost
    _write(path, "# Host=login.eqemulator.net:5998\n# Host=other.example.com:5998\n")

    ok, _ = eq_config.enable_proxy()

    assert ok
    assert backup.read_text(encoding="utf-8") == eq_config.DEFAULT_LOGIN_SERVER + "\n"


def test_disable_with_backup_restores_and_consumes_backup(eqhost):
    path, backup = eqhost
    _write(path, eq_config.DEFAULT_PROXY_ADDRESS + "\n")
    _write(backup, "Host=guild.example.com:5998\n")

    ok, err = eq_config.disable_proxy()

    assert ok and err is None
    assert path.read_text(encoding="utf-8") == "Host=guild.example.com:5998\n"
    assert not backup.exists()


def test_disable_without_backup_writes_default(eqhost):
    path, backup = eqhost
    _write(path, eq_config.DEFAULT_PROXY_ADDRESS + "\n")

    ok, _ = eq_config.disable_proxy()

    assert ok
    assert path.read_text(encoding="utf-8") == eq_config.DEFAULT_LOGIN_SERVER + "\n"
    assert not backup.exists()


def test_restore_backup_without_backup_returns_error(eqhost):
    path, _ = eqhost
    _write(path, eq_config.DEFAULT_PROXY_ADDRESS + "\n")

    ok, err = eq_config.restore_backup()

    assert not ok
    assert err and "backup" in err.lower()
    # eqhost.txt unchanged
    assert path.read_text(encoding="utf-8") == eq_config.DEFAULT_PROXY_ADDRESS + "\n"


def test_full_enable_disable_roundtrip(eqhost):
    path, backup = eqhost
    original = "Host=guild.example.com:5998\n# old comment\n"
    _write(path, original)

    eq_config.enable_proxy()
    assert path.read_text(encoding="utf-8") == eq_config.DEFAULT_PROXY_ADDRESS + "\n"

    eq_config.disable_proxy()
    assert path.read_text(encoding="utf-8") == original
    assert not backup.exists()


def test_is_using_proxy_true_only_for_single_proxy_line(eqhost):
    path, _ = eqhost
    _write(path, eq_config.DEFAULT_PROXY_ADDRESS + "\n")
    using, eqpath = eq_config.is_using_proxy()
    assert using is True
    assert eqpath == str(path)


def test_is_using_proxy_false_when_proxy_with_other_active_host(eqhost):
    path, _ = eqhost
    _write(path, eq_config.DEFAULT_PROXY_ADDRESS + "\nHost=other.example.com:5998\n")
    using, _ = eq_config.is_using_proxy()
    assert using is False


def test_is_using_proxy_ignores_commented_proxy_lines(eqhost):
    path, _ = eqhost
    _write(path, "# " + eq_config.DEFAULT_PROXY_ADDRESS + "\nHost=login.eqemulator.net:5998\n")
    using, _ = eq_config.is_using_proxy()
    assert using is False


def test_read_eqhost_file_tolerates_bom_crlf_and_whitespace(eqhost):
    path, _ = eqhost
    raw = "\ufeffHost=login.eqemulator.net:5998\r\n \r\nHost=guild.example.com:5998 \r\n"
    path.write_bytes(raw.encode("utf-8"))

    lines = eq_config.read_eqhost_file(str(path))

    assert lines == ["Host=login.eqemulator.net:5998", "", "Host=guild.example.com:5998"]


def test_atomic_write_leaves_no_temp_files_on_success(eqhost):
    path, _ = eqhost
    eq_config._atomic_write_text(str(path), "Host=login.eqemulator.net:5998\n")
    assert path.read_text(encoding="utf-8") == "Host=login.eqemulator.net:5998\n"
    debris = [p.name for p in path.parent.iterdir() if p.name.startswith(".eqhost-")]
    assert debris == []


def test_atomic_write_cleans_temp_on_replace_failure(eqhost, monkeypatch):
    path, _ = eqhost
    _write(path, "original\n")

    def boom(*_args, **_kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError, match="simulated"):
        eq_config._atomic_write_text(str(path), "new content\n")

    # Original is untouched
    assert path.read_text(encoding="utf-8") == "original\n"
    # No temp debris
    debris = [p.name for p in path.parent.iterdir() if p.name.startswith(".eqhost-")]
    assert debris == []
