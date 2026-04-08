"""WebSocket client for real-time account data from the SSO API."""

import asyncio
import base64
import contextlib
import json
import logging
import ssl
import uuid

import websockets
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from p99_sso_login_proxy import __version__, config, eq_config, utils


class WsClientSignals(QObject):
    """Marshals WebSocket-driven UI refresh to the Qt main thread."""

    cache_updated = Signal()
    rustle_ui_warning = Signal(str)  # message body


_ws_signals: WsClientSignals | None = None


def get_ws_signals() -> WsClientSignals | None:
    """Return the shared WsClientSignals object (after QApplication exists)."""
    global _ws_signals
    if _ws_signals is None:
        app = QApplication.instance()
        if app is None:
            return None
        _ws_signals = WsClientSignals(app)
    return _ws_signals


logger = logging.getLogger("ws_client")

_ws: websockets.WebSocketClientProtocol | None = None
_task: asyncio.Task | None = None
_connected = False
_auth_failed_detail: str | None = None
_pending_auth: dict[str, asyncio.Future] = {}
# character_name.lower() -> last sent update_location payload fields (excl. type)
_last_sent_location: dict[str, dict[str, object]] = {}

RECONNECT_MIN = 1
RECONNECT_MAX = 60


def is_connected() -> bool:
    return _connected


def is_auth_failed() -> bool:
    return _auth_failed_detail is not None


def get_auth_failed_detail() -> str | None:
    return _auth_failed_detail


async def send_heartbeat(character_name: str):
    """Send a heartbeat message over the WebSocket."""
    if _ws and _connected:
        try:
            await _ws.send(
                json.dumps(
                    {
                        "type": "heartbeat",
                        "character_name": character_name,
                    }
                )
            )
        except Exception:
            logger.debug("Failed to send heartbeat", exc_info=True)


def _merge_last_location_state(prev: dict, data_fields: dict) -> dict:
    """Merge outgoing update_location fields into the previous per-character snapshot (items dict merges shallowly)."""
    out = {**prev}
    for key, val in data_fields.items():
        if key == "items" and isinstance(val, dict):
            out["items"] = {**(out.get("items") or {}), **val}
        else:
            out[key] = val
    return out


async def send_update_location(
    character_name: str,
    park_location: str | None = None,
    bind_location: str | None = None,
    level: int | None = None,
    items: dict | None = None,
):
    """Send an update_location message over the WebSocket."""
    if _ws and _connected:
        msg = {"type": "update_location", "character_name": character_name}
        if park_location:
            msg["park_location"] = park_location
        if bind_location:
            msg["bind_location"] = bind_location
        if level is not None:
            msg["level"] = level
        if items:
            msg["items"] = items
        data_fields = {k: v for k, v in msg.items() if k not in ("type", "character_name")}
        char_key = character_name.lower()
        prev = _last_sent_location.get(char_key, {})
        tentative = _merge_last_location_state(prev, data_fields)
        if data_fields and tentative == prev:
            return
        try:
            await _ws.send(json.dumps(msg))
        except Exception:
            logger.debug("Failed to send update_location", exc_info=True)
        else:
            _last_sent_location[char_key] = tentative


async def send_fte(mob: str, player: str, character_name: str, eq_log_time: str):
    """Send a first-to-engage line to the SSO API over WebSocket.

    *eq_log_time* is the bracket timestamp from the EQ log (``time`` group).
    """
    if _ws and _connected:
        try:
            await _ws.send(
                json.dumps(
                    {
                        "type": "fte",
                        "mob": mob,
                        "player": player,
                        "character_name": character_name,
                        "eq_log_time": eq_log_time,
                    }
                )
            )
        except Exception:
            logger.debug("Failed to send fte", exc_info=True)


async def send_mob_death(mob: str, eq_log_time: str, character_name: str):
    """Send a raid-target death line to the SSO API over WebSocket.

    *eq_log_time* is the bracket timestamp from the EQ log (``time`` group), e.g.
    ``Fri Mar 06 11:13:03 2026``. The server parses it for ``!tod`` and verifies
    it is near server time.
    """
    if _ws and _connected:
        try:
            await _ws.send(
                json.dumps(
                    {
                        "type": "mob_death",
                        "mob": mob,
                        "eq_log_time": eq_log_time,
                        "character_name": character_name,
                    }
                )
            )
        except Exception:
            logger.debug("Failed to send mob_death", exc_info=True)


async def request_login_auth(
    username: str,
) -> tuple[str | None, bytes | None, str | None]:
    """Send a login_auth request over the WebSocket and await the response.

    Returns ``(real_user, encrypted_credentials, error_detail)``.
    *encrypted_credentials* is the raw DES-CBC ciphertext (bytes) ready
    to splice into the login packet.
    Returns ``(None, None, "WebSocket not connected")`` if the WS is down.
    """
    if not _ws or not _connected:
        return None, None, "WebSocket not connected"

    request_id = uuid.uuid4().hex
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    _pending_auth[request_id] = future

    try:
        await _ws.send(
            json.dumps(
                {
                    "type": "login_auth",
                    "request_id": request_id,
                    "username": username,
                }
            )
        )
        result = await asyncio.wait_for(future, timeout=config.SSO_TIMEOUT)
        return result
    except TimeoutError:
        logger.warning("login_auth request timed out for %s", username)
        return None, None, "Login auth request timed out"
    except Exception:
        logger.debug("login_auth request failed for %s", username, exc_info=True)
        return None, None, "Login auth request failed"
    finally:
        _pending_auth.pop(request_id, None)


def _resolve_login_auth_response(msg: dict):
    """Resolve a pending login_auth future from a server response."""
    request_id = msg.get("request_id")
    if not request_id:
        return
    future = _pending_auth.get(request_id)
    if future is None or future.done():
        return

    error = msg.get("error")
    if error:
        future.set_result((None, None, error))
    else:
        enc_b64 = msg.get("encrypted_credentials", "")
        encrypted = base64.b64decode(enc_b64) if enc_b64 else None
        future.set_result((msg.get("real_user"), encrypted, None))


def _cancel_pending_auth():
    """Cancel all pending login_auth futures (e.g. on disconnect)."""
    for fut in _pending_auth.values():
        if not fut.done():
            fut.cancel()
    _pending_auth.clear()


def _build_ws_url() -> str:
    """Convert the HTTP(S) SSO_API URL to a ws(s):// URL for the WebSocket endpoint."""
    base = config.SSO_API.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :] + "/ws/accounts"
    elif base.startswith("http://"):
        return "ws://" + base[len("http://") :] + "/ws/accounts"
    return "wss://" + base + "/ws/accounts"


def _get_ssl_context() -> ssl.SSLContext | None:
    url = _build_ws_url()
    if not url.startswith("wss://"):
        return None
    if not config.SSO_VERIFY_TLS:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    ca = config.SSO_CA_BUNDLE
    ctx = ssl.create_default_context()
    if isinstance(ca, str):
        ctx.load_verify_locations(ca)
    return ctx


def _apply_full_state(data: dict):
    """Replace the entire account cache from a full_state message."""
    account_tree = data.get("account_tree", {})
    dynamic_tag_zones = data.get("dynamic_tag_zones", [])
    dynamic_tag_classes = data.get("dynamic_tag_classes", [])

    _rebuild_cache(account_tree, dynamic_tag_zones, dynamic_tag_classes)


def _apply_delta(data: dict):
    """Apply incremental changes from a delta message to the account cache."""
    tree = dict(config.ACCOUNTS_CACHED)
    for change in data.get("changes", []):
        action = change.get("action")
        account = change.get("account")

        if action == "add":
            tree[account] = change.get("data", {})

        elif action == "remove":
            tree.pop(account, None)

        elif action == "update":
            entry = dict(tree.get(account, {}))
            fields = change.get("fields", {})

            for list_field in ("aliases", "tags"):
                if list_field in fields:
                    current = set(entry.get(list_field, []))
                    current |= set(fields[list_field].get("add", []))
                    current -= set(fields[list_field].get("remove", []))
                    entry[list_field] = sorted(current)

            if "characters" in fields:
                chars = dict(entry.get("characters", {}))
                char_diff = fields["characters"]
                for name, cdata in char_diff.get("add", {}).items():
                    chars[name] = cdata
                for name in char_diff.get("remove", []):
                    chars.pop(name, None)
                for name, cdata in char_diff.get("update", {}).items():
                    chars[name] = cdata
                entry["characters"] = chars

            for scalar in ("last_login", "last_login_by", "active_character"):
                if scalar in fields:
                    entry[scalar] = fields[scalar]

            tree[account] = entry

    _rebuild_cache(tree)


def _rebuild_cache(account_tree: dict, dynamic_tag_zones=None, dynamic_tag_classes=None):
    """Rebuild all config cache globals from an account_tree dict."""
    all_names = []
    characters = []

    for acct_name, data in account_tree.items():
        all_names.append(acct_name)
        all_names.extend(a.lower() for a in data.get("aliases", []))
        all_names.extend(t.lower() for t in data.get("tags", []))
        all_names.extend(c.lower() for c in data.get("characters", {}))
        characters.extend(c.lower() for c in data.get("characters", {}))

    if dynamic_tag_zones is not None and dynamic_tag_classes is not None:
        all_names.extend(utils.get_dynamic_tag_list(dynamic_tag_zones, dynamic_tag_classes))

    import datetime

    config.ACCOUNTS_CACHED = account_tree
    config.ALL_CACHED_NAMES = list(set(all_names))
    config.CHARACTERS_CACHED = characters
    config.ACCOUNTS_CACHE_REAL_COUNT = len(account_tree)
    config.ACCOUNTS_CACHE_TIMESTAMP = datetime.datetime.now()

    _notify_ui()


def _notify_ui():
    """Tell the Qt UI to refresh its account displays (thread-safe)."""
    try:
        sig = get_ws_signals()
        if sig:
            sig.cache_updated.emit()
    except Exception:
        pass


async def _run(reconnect_requested: asyncio.Event):
    """Main WebSocket loop with auto-reconnect."""
    global _ws, _connected, _auth_failed_detail
    delay = RECONNECT_MIN

    while True:
        reconnect_requested.clear()
        _auth_failed_detail = None

        if not config.USER_API_TOKEN:
            _notify_ui()
            # Park until a reconnect is requested (token was set)
            await reconnect_requested.wait()
            continue

        url = _build_ws_url()
        ssl_ctx = _get_ssl_context()
        logger.info("Connecting to %s", url)

        auth_error = None
        try:
            async with websockets.connect(
                url,
                ssl=ssl_ctx,
                ping_interval=None,
                close_timeout=5,
            ) as ws:
                _ws = ws
                if eq_config.detect_rustle_ui() and config.WARN_RUSTLE:
                    msg = (
                        "A modified UI skin with non-standard inventory slots was "
                        "detected in your EverQuest uifiles directory. This may "
                        "cause issues or be blocked by some servers."
                    )
                    sig = get_ws_signals()
                    if sig:
                        sig.rustle_ui_warning.emit(msg)
                await ws.send(
                    json.dumps(
                        {
                            "type": "auth",
                            "access_key": config.USER_API_TOKEN,
                            "client_version": __version__,
                            "client_settings": eq_config.get_client_settings(),
                        }
                    )
                )

                while True:
                    recv_task = asyncio.ensure_future(ws.recv())
                    reconnect_wait = asyncio.ensure_future(reconnect_requested.wait())

                    done, pending = await asyncio.wait(
                        {recv_task, reconnect_wait},
                        return_when=asyncio.FIRST_COMPLETED,
                        timeout=60,
                    )

                    for t in pending:
                        t.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await t

                    if reconnect_wait in done or reconnect_requested.is_set():
                        logger.info("Reconnect requested, closing connection")
                        await ws.close()
                        break

                    if not done:
                        continue

                    raw = recv_task.result()
                    msg = json.loads(raw)
                    msg_type = msg.get("type")

                    if msg_type == "full_state":
                        logger.info(
                            "Received full_state (%d accounts)",
                            msg.get("count", 0),
                        )
                        _connected = True
                        _notify_ui()
                        delay = RECONNECT_MIN
                        _apply_full_state(msg)

                    elif msg_type == "delta":
                        changes = msg.get("changes", [])
                        parts = []
                        for c in changes:
                            action = c.get("action", "?")
                            acct = c.get("account", "?")
                            if action == "update":
                                fields = ", ".join(c.get("fields", {}).keys())
                                parts.append(f"update {acct} ({fields})")
                            else:
                                parts.append(f"{action} {acct}")
                        logger.debug("Received delta: %s", "; ".join(parts))
                        _apply_delta(msg)

                    elif msg_type == "login_auth_response":
                        _resolve_login_auth_response(msg)

                    elif msg_type == "ping":
                        await ws.send(json.dumps({"type": "pong"}))

                    elif msg_type == "error":
                        error_detail = msg.get("detail", "Authentication failed")
                        logger.error("Server error: %s", error_detail)
                        auth_error = error_detail
                        break

        except asyncio.CancelledError:
            raise
        except (
            websockets.exceptions.InvalidStatus,
            websockets.exceptions.ConnectionClosedError,
            ConnectionError,
            OSError,
        ) as exc:
            logger.info("WebSocket connection lost (%s), reconnecting in %ds", exc, delay)
        except Exception:
            logger.warning("WebSocket disconnected, reconnecting in %ds", delay, exc_info=True)
        finally:
            _ws = None
            _connected = False
            _cancel_pending_auth()
            _last_sent_location.clear()
            _rebuild_cache({}, [], [])

        if auth_error:
            _auth_failed_detail = auth_error
            _notify_ui()
            logger.info("Auth failed, parking until reconnect is requested")
            await reconnect_requested.wait()
            delay = RECONNECT_MIN
            continue

        await asyncio.sleep(delay)
        delay = min(delay * 2, RECONNECT_MAX)


_reconnect_event: asyncio.Event | None = None


def request_reconnect():
    """Signal the WS loop to disconnect and reconnect (for a fresh full_state)."""
    if _reconnect_event is not None:
        _reconnect_event.set()


async def start():
    """Start the WebSocket client task on the current event loop."""
    global _task, _reconnect_event
    _reconnect_event = asyncio.Event()
    _task = asyncio.current_task()
    await _run(_reconnect_event)


async def stop():
    """Cancel the running WebSocket task."""
    global _task
    if _task and not _task.done():
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
    _task = None
