"""Repair corrupted proxyconfig.ini files before configparser loads them."""

from __future__ import annotations

import configparser
import os
import re
from typing import Mapping

_CUSTOM_LABEL_RE = re.compile(r"^Custom:\s*(.+)$", re.IGNORECASE)
_OLD_P99_NAME = "P99 Login Proxy"
_API_TOKENS_SECTION = "api_tokens"
_SSO_BACKENDS_SECTION = "sso_backends"
_DEFAULT_SECTION = "DEFAULT"
_TOKEN_SECTIONS = frozenset({_API_TOKENS_SECTION, _SSO_BACKENDS_SECTION})

_BUILTIN_URL_TO_NAME: dict[str, str] = {
    "https://proxy.p99loginproxy.net": "Good Guys",
    "https://bot.kingdomdkp.com": "Kingdom",
    "http://localhost:5998": "Localhost",
}


def _is_unsafe_key(name: str) -> bool:
    return ":" in name or "=" in name


def _parse_line(line: str, section: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(";") or stripped.startswith("#"):
        return None
    if stripped.startswith("[") and stripped.endswith("]"):
        return None

    if section in _TOKEN_SECTIONS and " = " in stripped:
        key, value = stripped.rsplit(" = ", 1)
        return key.strip(), value.strip()

    if "=" in stripped:
        key, _, value = stripped.partition("=")
        return key.strip(), value.strip()

    return None


def _parse_ini_text(text: str) -> dict[str, dict[str, list[str]]]:
    """Parse an INI file, keeping duplicate keys as lists for repair."""
    sections: dict[str, dict[str, list[str]]] = {_DEFAULT_SECTION: {}}
    current = _DEFAULT_SECTION

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip()
            sections.setdefault(current, {})
            continue

        parsed = _parse_line(raw_line, current)
        if parsed is None:
            continue
        key, value = parsed
        sections.setdefault(current, {}).setdefault(key, []).append(value)

    return sections


def _collapse_values(values: list[str]) -> str:
    for value in reversed(values):
        cleaned = value.strip().rstrip("=").strip()
        if cleaned:
            return cleaned
    return values[-1].strip() if values else ""


def _url_to_name_map(sections: Mapping[str, Mapping[str, list[str]]]) -> dict[str, str]:
    mapping = dict(_BUILTIN_URL_TO_NAME)
    for name, values in sections.get(_SSO_BACKENDS_SECTION, {}).items():
        url = _collapse_values(values)
        if url and name not in mapping.values():
            mapping.setdefault(url, name)
    return mapping


def _extract_url_from_value(value: str) -> str | None:
    match = re.search(r"https?://[^\s=]+", value)
    return match.group(0) if match else None


def resolve_backend_name(
    name: str,
    *,
    url_hint: str | None = None,
    url_to_name: Mapping[str, str] | None = None,
) -> str:
    """Return a safe backend display name for persistence and token lookup."""
    url_to_name = dict(url_to_name or _BUILTIN_URL_TO_NAME)

    custom_match = _CUSTOM_LABEL_RE.match(name.strip())
    if custom_match:
        url = custom_match.group(1).strip()
        return url_to_name.get(url, name.strip())

    if _is_unsafe_key(name):
        hinted = url_hint or _extract_url_from_value(name)
        if hinted:
            return url_to_name.get(hinted, name.strip())

    return name.strip()


def _pick_token(values: list[str]) -> str:
    for value in reversed(values):
        token = value.strip().rstrip("=").strip()
        if token and "://" not in token:
            return token
        if " = " in value:
            token = value.rsplit(" = ", 1)[-1].strip()
            if token:
                return token
    for value in reversed(values):
        token = value.strip().rstrip("=").strip()
        if token:
            return token
    return ""


def _repair_api_tokens(
    tokens: dict[str, list[str]],
    url_to_name: Mapping[str, str],
) -> dict[str, str]:
    repaired: dict[str, str] = {}

    for raw_name, values in tokens.items():
        token = _pick_token(values)
        url_hint = _extract_url_from_value(_collapse_values(values))

        if raw_name == "Custom" and url_hint:
            safe_name = url_to_name.get(url_hint, raw_name)
        else:
            safe_name = resolve_backend_name(raw_name, url_hint=url_hint, url_to_name=url_to_name)

        if _is_unsafe_key(safe_name):
            continue

        if safe_name not in repaired or (token and not repaired[safe_name]):
            repaired[safe_name] = token
        elif token and repaired[safe_name] != token:
            repaired[safe_name] = token

    if _OLD_P99_NAME in repaired and (
        "Good Guys" in repaired or "Marginal Threat" in repaired
    ):
        repaired.pop(_OLD_P99_NAME, None)

    return repaired


def _repair_defaults(defaults: dict[str, list[str]], url_to_name: Mapping[str, str]) -> dict[str, str]:
    repaired = {key: _collapse_values(values) for key, values in defaults.items()}

    sso_api_name = repaired.get("sso_api_name", "")
    sso_api = repaired.get("sso_api", "")
    if sso_api_name:
        safe_name = resolve_backend_name(sso_api_name, url_hint=sso_api or None, url_to_name=url_to_name)
        if safe_name != sso_api_name:
            repaired["sso_api_name"] = safe_name

    return repaired


def repair_sections(sections: Mapping[str, Mapping[str, list[str]]]) -> dict[str, dict[str, str]]:
    """Return repaired section data ready to write."""
    url_to_name = _url_to_name_map(sections)
    repaired: dict[str, dict[str, str]] = {}

    defaults = sections.get(_DEFAULT_SECTION, {})
    if defaults:
        repaired[_DEFAULT_SECTION] = _repair_defaults(defaults, url_to_name)

    if _API_TOKENS_SECTION in sections:
        repaired[_API_TOKENS_SECTION] = _repair_api_tokens(sections[_API_TOKENS_SECTION], url_to_name)

    if _SSO_BACKENDS_SECTION in sections:
        backend_repaired: dict[str, str] = {}
        for name, values in sections[_SSO_BACKENDS_SECTION].items():
            safe_name = resolve_backend_name(name, url_hint=_collapse_values(values), url_to_name=url_to_name)
            if _is_unsafe_key(safe_name):
                continue
            backend_repaired[safe_name] = _collapse_values(values)
        repaired[_SSO_BACKENDS_SECTION] = backend_repaired

    for section, options in sections.items():
        if section in repaired or section == _DEFAULT_SECTION:
            continue
        repaired[section] = {key: _collapse_values(values) for key, values in options.items()}

    return repaired


def config_text_needs_repair(text: str) -> bool:
    sections = _parse_ini_text(text)
    url_to_name = _url_to_name_map(sections)
    repaired = repair_sections(sections)

    if repaired.get(_DEFAULT_SECTION, {}) != {
        key: _collapse_values(values) for key, values in sections.get(_DEFAULT_SECTION, {}).items()
    }:
        return True

    original_tokens = {
        key: _collapse_values(values) for key, values in sections.get(_API_TOKENS_SECTION, {}).items()
    }
    if repaired.get(_API_TOKENS_SECTION, {}) != original_tokens:
        return True

    for section, options in sections.items():
        for key, values in options.items():
            if section in _TOKEN_SECTIONS and _is_unsafe_key(key):
                return True
            if key == "sso_api_name" and _CUSTOM_LABEL_RE.match(_collapse_values(values)):
                return True
            if section == _API_TOKENS_SECTION and key == "Custom":
                if _extract_url_from_value(_collapse_values(values)):
                    return True
            if len(values) > 1:
                return True

    if _OLD_P99_NAME in sections.get(_API_TOKENS_SECTION, {}) and (
        "Good Guys" in sections.get(_API_TOKENS_SECTION, {})
        or "Marginal Threat" in sections.get(_API_TOKENS_SECTION, {})
    ):
        return True

    if url_to_name:
        return False

    return False


def write_repaired_config(path: str, repaired: Mapping[str, Mapping[str, str]]) -> None:
    parser = configparser.ConfigParser()
    parser.optionxform = str

    for section, options in repaired.items():
        if section == _DEFAULT_SECTION:
            for key, value in options.items():
                parser.set(_DEFAULT_SECTION, key, value)
        else:
            if not parser.has_section(section):
                parser.add_section(section)
            for key, value in options.items():
                parser.set(section, key, value)

    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        parser.write(handle)
    os.replace(tmp_path, path)


def repair_proxyconfig_ini(path: str) -> bool:
    """Repair a proxyconfig.ini file in place. Returns True if a rewrite occurred."""
    if not os.path.exists(path):
        return False

    with open(path, encoding="utf-8") as handle:
        text = handle.read()

    if not config_text_needs_repair(text):
        return False

    sections = _parse_ini_text(text)
    repaired = repair_sections(sections)
    write_repaired_config(path, repaired)
    return True


def load_config_parser(path: str) -> configparser.ConfigParser:
    """Load proxyconfig.ini, repairing it first when necessary."""
    parser = configparser.ConfigParser()
    parser.optionxform = str

    if not os.path.exists(path):
        return parser

    try:
        parser.read(path, encoding="utf-8")
    except (configparser.DuplicateOptionError, configparser.DuplicateSectionError):
        repair_proxyconfig_ini(path)
        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser.read(path, encoding="utf-8")
        return parser

    with open(path, encoding="utf-8") as handle:
        if config_text_needs_repair(handle.read()):
            repair_proxyconfig_ini(path)
            parser = configparser.ConfigParser()
            parser.optionxform = str
            parser.read(path, encoding="utf-8")

    return parser
