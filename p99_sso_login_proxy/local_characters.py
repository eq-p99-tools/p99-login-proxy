"""Helpers for mutating / persisting the local character CSV.

The in-memory source of truth is :data:`config.LOCAL_CHARACTERS`. All mutators here
take the lock, update the dict, schedule a debounced flush to disk, and notify
listeners so the UI can re-render.

No Qt dependency at import time; UI subscribes via :data:`ON_UPDATED`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from p99_sso_login_proxy import config, utils

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_save_timer: threading.Timer | None = None
_SAVE_DEBOUNCE_SEC = 0.25

# Login methods (from server.PROXY_STATS.user_login) that establish a local-account
# binding suitable for pairing with the next new EQ log file.
_LOCAL_METHODS = frozenset({"local", "local_char"})

# The most recently observed local-account login. Set by note_login when a local
# rewrite fires, cleared by any non-local login. Used by try_auto_create.
_pending_local_account: str | None = None

# Callbacks invoked (from the save-timer thread) whenever LOCAL_CHARACTERS mutates.
# Subscribers are responsible for marshalling back to their UI thread.
ON_UPDATED: list[Callable[[], None]] = []


def _blank_items() -> dict[str, bool | int | None]:
    return {k: None for k in (*utils.LOCAL_CHARACTER_BOOL_ITEMS, *utils.LOCAL_CHARACTER_COUNT_ITEMS)}


def _ensure_entry(name: str) -> dict:
    """Return the mutable entry for ``name`` (lowercased), creating an empty one if needed."""
    key = name.lower()
    entry = config.LOCAL_CHARACTERS.get(key)
    if entry is None:
        entry = {
            "name": name,
            "account": "",
            "class": None,
            "level": None,
            "bind": None,
            "park": None,
            "items": _blank_items(),
        }
        config.LOCAL_CHARACTERS[key] = entry
        config.LOCAL_CHARACTER_NAMES.add(key)
    else:
        entry.setdefault("items", _blank_items())
        for wk in (*utils.LOCAL_CHARACTER_BOOL_ITEMS, *utils.LOCAL_CHARACTER_COUNT_ITEMS):
            entry["items"].setdefault(wk, None)
    return entry


def _notify() -> None:
    for cb in list(ON_UPDATED):
        try:
            cb()
        except Exception:
            logger.exception("Error in local_characters ON_UPDATED callback")


def _flush() -> None:
    with _lock:
        global _save_timer
        _save_timer = None
        snapshot = {k: dict(v) for k, v in config.LOCAL_CHARACTERS.items()}
    utils.save_local_characters(snapshot, config.LOCAL_CHARACTERS_FILE)
    _notify()


def _schedule_save() -> None:
    global _save_timer
    if _save_timer is not None:
        return
    _save_timer = threading.Timer(_SAVE_DEBOUNCE_SEC, _flush)
    _save_timer.daemon = True
    _save_timer.start()


def mark_dirty() -> None:
    """Schedule a debounced save + listener notification."""
    with _lock:
        _schedule_save()


def save_now() -> bool:
    """Flush synchronously (cancels any pending debounce). Returns success flag."""
    global _save_timer
    with _lock:
        if _save_timer is not None:
            _save_timer.cancel()
            _save_timer = None
        snapshot = {k: dict(v) for k, v in config.LOCAL_CHARACTERS.items()}
    ok = utils.save_local_characters(snapshot, config.LOCAL_CHARACTERS_FILE)
    _notify()
    return ok


def apply_update(
    name: str,
    *,
    park: str | None = None,
    bind: str | None = None,
    level: int | None = None,
    klass: str | None = None,
    items: dict | None = None,
) -> bool:
    """Merge observed fields into :data:`config.LOCAL_CHARACTERS[name.lower()]`.

    Only updates fields that are not ``None`` in the call. Returns ``True`` if the
    entry changed and a save was scheduled.
    """
    key = name.lower()
    if key not in config.LOCAL_CHARACTER_NAMES:
        return False

    changed = False
    with _lock:
        entry = _ensure_entry(name)
        if park is not None and entry.get("park") != park:
            entry["park"] = park
            changed = True
        if bind is not None and entry.get("bind") != bind:
            entry["bind"] = bind
            changed = True
        if level is not None and entry.get("level") != level:
            entry["level"] = level
            changed = True
        if klass is not None and entry.get("class") != klass:
            entry["class"] = klass
            changed = True
        if items:
            bucket = entry.setdefault("items", _blank_items())
            for wire_key, value in items.items():
                if bucket.get(wire_key) != value:
                    bucket[wire_key] = value
                    changed = True
        if changed:
            _schedule_save()
    return changed


def set_entry(entry: dict) -> None:
    """Replace the entry for ``entry['name']`` (used by Add/Edit dialog handlers)."""
    name = (entry.get("name") or "").strip()
    if not name:
        raise ValueError("entry must have a non-empty 'name'")
    key = name.lower()
    with _lock:
        normalized = {
            "name": name,
            "account": (entry.get("account") or "").strip().lower(),
            "class": entry.get("class") or None,
            "level": entry.get("level"),
            "bind": entry.get("bind") or None,
            "park": entry.get("park") or None,
            "items": {**_blank_items(), **(entry.get("items") or {})},
        }
        config.LOCAL_CHARACTERS[key] = normalized
        config.LOCAL_CHARACTER_NAMES.add(key)


def delete_entry(name: str) -> bool:
    """Remove the entry for ``name``; returns ``True`` if a row was removed."""
    key = name.lower()
    with _lock:
        if key not in config.LOCAL_CHARACTERS:
            return False
        del config.LOCAL_CHARACTERS[key]
        config.LOCAL_CHARACTER_NAMES.discard(key)
    return True


def note_login(method: str, account: str | None) -> None:
    """Record (or clear) the pending local account based on the login method.

    Called by every rewrite path in :mod:`server`. If *method* is one of
    :data:`_LOCAL_METHODS`, the resolved local account is stashed for the next
    new log file to claim. Any other method clears the slot so a stale local
    login can't be mis-paired with a subsequent non-local session.
    """
    global _pending_local_account
    with _lock:
        _pending_local_account = account.strip().lower() or None if method in _LOCAL_METHODS and account else None


def try_auto_create(character_name: str) -> bool:
    """Create a minimal local-character row for *character_name* when a local
    login is pending.

    Returns ``True`` if a new row was added. Safe no-op (with a logged warning)
    on collision with an existing row bound to a different account.
    """
    if not config.AUTO_ADD_LOCAL_CHARACTERS:
        return False
    if not character_name:
        return False

    with _lock:
        pending = _pending_local_account
        if not pending:
            return False
        if pending not in config.LOCAL_ACCOUNTS:
            logger.warning(
                "Skipping auto-add for %s: pending local account %r is no longer in local_accounts.csv",
                character_name,
                pending,
            )
            return False

        key = character_name.lower()
        if key in config.LOCAL_CHARACTER_NAMES:
            existing_account = (config.LOCAL_CHARACTERS.get(key) or {}).get("account") or ""
            if existing_account.lower() != pending:
                logger.warning(
                    "Local character %s is bound to %s; saw recent local login as %s (not overwriting)",
                    character_name,
                    existing_account or "<unset>",
                    pending,
                )
            return False

        set_entry(
            {
                "name": character_name,
                "account": pending,
                "class": None,
                "level": None,
                "bind": None,
                "park": None,
                "items": {},
            }
        )
        mark_dirty()

    logger.info("Auto-added local character %s -> account %s", character_name, pending)
    return True
