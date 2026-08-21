"""Tests for proxyconfig.ini repair and safe backend name handling."""

from __future__ import annotations

import configparser
import stat

from p99_sso_login_proxy import config_repair

EXAMPLE_TOKEN = "example-token-abc123"
EXAMPLE_TOKEN_ALT = "example-token-xyz789"
P99_PROXY_URL = "https://proxy.p99loginproxy.net"

BROKEN_CONFIG = f"""[DEFAULT]
user_api_token = {EXAMPLE_TOKEN}
sso_api_name = Custom: {P99_PROXY_URL}
sso_api = {P99_PROXY_URL}

[api_tokens]
P99 Login Proxy = {EXAMPLE_TOKEN}
Good Guys = {EXAMPLE_TOKEN}
Marginal Threat = {EXAMPLE_TOKEN}
Custom = {P99_PROXY_URL} =
Custom: {P99_PROXY_URL} = {EXAMPLE_TOKEN}
"""


def _write_config(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_broken_config_repairs_without_duplicate_option_error(tmp_path):
    ini_path = tmp_path / "proxyconfig.ini"
    _write_config(ini_path, BROKEN_CONFIG)

    assert config_repair.repair_proxyconfig_ini(str(ini_path)) is True

    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(ini_path, encoding="utf-8")

    assert parser.get("DEFAULT", "sso_api_name") == "Good Guys"
    assert parser.get("api_tokens", "Good Guys") == EXAMPLE_TOKEN
    assert parser.get("api_tokens", "Marginal Threat") == EXAMPLE_TOKEN
    assert not parser.has_option("api_tokens", "P99 Login Proxy")
    assert not parser.has_option("api_tokens", "Custom")
    assert not parser.has_option("api_tokens", f"Custom: {P99_PROXY_URL}")


def test_load_config_parser_handles_duplicate_option_error(tmp_path):
    ini_path = tmp_path / "proxyconfig.ini"
    _write_config(ini_path, BROKEN_CONFIG)

    parser = config_repair.load_config_parser(str(ini_path))

    assert parser.get("DEFAULT", "sso_api_name") == "Good Guys"
    assert parser.get("api_tokens", "Good Guys") == EXAMPLE_TOKEN


def test_load_config_parser_repairs_read_only_file(tmp_path):
    ini_path = tmp_path / "proxyconfig.ini"
    _write_config(ini_path, BROKEN_CONFIG)
    ini_path.chmod(stat.S_IREAD)

    try:
        parser = config_repair.load_config_parser(str(ini_path))

        assert parser.get("DEFAULT", "sso_api_name") == "Good Guys"
        assert ini_path.stat().st_mode & stat.S_IWRITE
        assert "sso_api_name = Good Guys" in ini_path.read_text(encoding="utf-8")
    finally:
        ini_path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_load_config_parser_uses_memory_repair_when_replace_is_blocked(tmp_path, monkeypatch):
    ini_path = tmp_path / "proxyconfig.ini"
    _write_config(ini_path, BROKEN_CONFIG)

    def deny_replace(_source, _destination):
        raise PermissionError("file is locked")

    monkeypatch.setattr(config_repair.os, "replace", deny_replace)

    parser = config_repair.load_config_parser(str(ini_path))

    assert parser.get("DEFAULT", "sso_api_name") == "Good Guys"
    assert parser.get("api_tokens", "Good Guys") == EXAMPLE_TOKEN
    assert ini_path.read_text(encoding="utf-8") == BROKEN_CONFIG
    assert not ini_path.with_suffix(".ini.tmp").exists()


def test_custom_sso_api_name_resolves_to_good_guys(tmp_path):
    ini_path = tmp_path / "proxyconfig.ini"
    _write_config(
        ini_path,
        f"""[DEFAULT]
sso_api_name = Custom: {P99_PROXY_URL}
sso_api = {P99_PROXY_URL}

[api_tokens]
Good Guys = {EXAMPLE_TOKEN}
""",
    )

    config_repair.repair_proxyconfig_ini(str(ini_path))
    text = ini_path.read_text(encoding="utf-8")
    assert "sso_api_name = Good Guys" in text
    assert "Custom:" not in text


def test_colon_key_round_trip_repairs_to_single_entry(tmp_path):
    ini_path = tmp_path / "proxyconfig.ini"
    _write_config(
        ini_path,
        f"""[DEFAULT]
sso_api_name = Good Guys
sso_api = {P99_PROXY_URL}

[api_tokens]
Custom: {P99_PROXY_URL} = {EXAMPLE_TOKEN_ALT}
""",
    )

    config_repair.repair_proxyconfig_ini(str(ini_path))

    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(ini_path, encoding="utf-8")

    assert parser.get("api_tokens", "Good Guys") == EXAMPLE_TOKEN_ALT
    assert not parser.has_option("api_tokens", "Custom")
    assert not parser.has_option("api_tokens", f"Custom: {P99_PROXY_URL}")


def test_migration_removes_stale_p99_login_proxy_key(tmp_path):
    ini_path = tmp_path / "proxyconfig.ini"
    _write_config(
        ini_path,
        f"""[DEFAULT]
sso_api_name = Good Guys
sso_api = {P99_PROXY_URL}

[api_tokens]
P99 Login Proxy = {EXAMPLE_TOKEN}
Good Guys = {EXAMPLE_TOKEN}
Marginal Threat = {EXAMPLE_TOKEN}
""",
    )

    assert config_repair.config_text_needs_repair(ini_path.read_text(encoding="utf-8")) is True
    config_repair.repair_proxyconfig_ini(str(ini_path))

    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(ini_path, encoding="utf-8")

    assert not parser.has_option("api_tokens", "P99 Login Proxy")
    assert parser.get("api_tokens", "Good Guys") == EXAMPLE_TOKEN


def test_resolve_backend_name_normalizes_custom_label():
    resolved = config_repair.resolve_backend_name(
        f"Custom: {P99_PROXY_URL}",
        url_hint=P99_PROXY_URL,
    )
    assert resolved == "Good Guys"


def test_set_api_token_normalizes_unsafe_backend_name(tmp_path, monkeypatch):
    ini_path = tmp_path / "proxyconfig.ini"
    _write_config(
        ini_path,
        f"""[DEFAULT]
sso_api_name = Good Guys
sso_api = {P99_PROXY_URL}
user_api_token =

[api_tokens]
Good Guys =
""",
    )

    from p99_sso_login_proxy import config

    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(ini_path, encoding="utf-8")

    monkeypatch.setattr(config, "CONFIG_FILE", str(ini_path))
    monkeypatch.setattr(config, "CONFIG", parser)
    monkeypatch.setattr(config, "SSO_API_NAME", "Good Guys")
    monkeypatch.setattr(config, "SSO_API", P99_PROXY_URL)

    config.set_api_token_for_backend(f"Custom: {P99_PROXY_URL}", EXAMPLE_TOKEN_ALT)

    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(ini_path, encoding="utf-8")

    assert parser.get("api_tokens", "Good Guys") == EXAMPLE_TOKEN_ALT
    assert not parser.has_option("api_tokens", f"Custom: {P99_PROXY_URL}")


def test_healthy_config_is_not_rewritten(tmp_path):
    ini_path = tmp_path / "proxyconfig.ini"
    healthy = f"""[DEFAULT]
sso_api_name = Good Guys
sso_api = {P99_PROXY_URL}
user_api_token = {EXAMPLE_TOKEN}

[api_tokens]
Good Guys = {EXAMPLE_TOKEN}
Marginal Threat = {EXAMPLE_TOKEN}
"""
    _write_config(ini_path, healthy)
    mtime_before = ini_path.stat().st_mtime_ns

    assert config_repair.repair_proxyconfig_ini(str(ini_path)) is False
    assert ini_path.read_text(encoding="utf-8") == healthy
    assert ini_path.stat().st_mtime_ns == mtime_before
