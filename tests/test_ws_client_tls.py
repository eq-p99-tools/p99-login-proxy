"""Tests for SSO WebSocket TLS context selection in ``ws_client``.

Covers:
  * ``_get_ssl_context`` across the certifi/system/custom/disabled modes.
  * Proof that disabling verification (``sso_verify_tls = False``) actually
    produces a non-verifying context AND that this exact context is handed to
    ``websockets.connect``.
"""

from __future__ import annotations

import asyncio
import ssl

import certifi
import pytest

from p99_sso_login_proxy import config, ws_client


@pytest.fixture
def sso_https(monkeypatch):
    """Point the SSO backend at an https:// URL so the endpoint is wss://."""
    monkeypatch.setattr(config, "SSO_API", "https://sso.example.test")


def test_non_wss_endpoint_returns_no_context(monkeypatch):
    monkeypatch.setattr(config, "SSO_API", "http://localhost:5998")
    assert ws_client._get_ssl_context() is None


def test_verify_disabled_returns_non_verifying_context(monkeypatch, sso_https):
    monkeypatch.setattr(config, "SSO_VERIFY_TLS", False)
    ctx = ws_client._get_ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_certifi_is_the_default_bundle(monkeypatch, sso_https):
    monkeypatch.setattr(config, "SSO_VERIFY_TLS", True)
    # Default fallback for an unset key is the boolean True.
    monkeypatch.setattr(config, "SSO_CA_BUNDLE", True)
    mode, path = ws_client._resolve_ca_mode()
    assert mode == "certifi"
    assert path == certifi.where()

    ctx = ws_client._get_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


@pytest.mark.parametrize("value", ["True", "true", "", "  "])
def test_truthy_strings_map_to_certifi(monkeypatch, value):
    monkeypatch.setattr(config, "SSO_CA_BUNDLE", value)
    mode, path = ws_client._resolve_ca_mode()
    assert mode == "certifi"
    assert path == certifi.where()


@pytest.mark.parametrize("value", ["system", "System", "false", "False"])
def test_system_and_false_use_platform_store(monkeypatch, value):
    monkeypatch.setattr(config, "SSO_CA_BUNDLE", value)
    mode, path = ws_client._resolve_ca_mode()
    assert mode == "system"
    assert path is None


def test_custom_bundle_path_is_loaded(monkeypatch, sso_https):
    monkeypatch.setattr(config, "SSO_VERIFY_TLS", True)
    # Use the certifi bundle as a stand-in for a real, loadable custom CA file.
    monkeypatch.setattr(config, "SSO_CA_BUNDLE", certifi.where())
    mode, path = ws_client._resolve_ca_mode()
    assert mode == "custom"
    assert path == certifi.where()

    ctx = ws_client._get_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_disabled_context_is_passed_to_websockets_connect(monkeypatch, sso_https):
    """End-to-end wiring: the non-verifying context must reach connect()."""
    monkeypatch.setattr(config, "SSO_VERIFY_TLS", False)
    monkeypatch.setattr(config, "USER_API_TOKEN", "test-token")

    captured: dict = {}

    class _FakeConnect:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        async def __aenter__(self):
            # Break out of the reconnect loop immediately; _run re-raises this.
            raise asyncio.CancelledError

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(ws_client.websockets, "connect", _FakeConnect)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ws_client._run(asyncio.Event()))

    ssl_arg = captured["kwargs"]["ssl"]
    assert isinstance(ssl_arg, ssl.SSLContext)
    assert ssl_arg.verify_mode == ssl.CERT_NONE
    assert ssl_arg.check_hostname is False
