"""Shared pytest fixtures.

The autouse ``_reset_local_characters_state`` fixture isolates tests that touch
``p99_sso_login_proxy.local_characters`` so one test can't leak module-level
globals (the pending-login slot, the LOCAL_CHARACTERS dict, the debounce timer,
or the AUTO_ADD flag) into the next.
"""

from __future__ import annotations

import pytest

from p99_sso_login_proxy import config, local_characters


@pytest.fixture(autouse=True)
def _reset_local_characters_state(tmp_path, monkeypatch):
    """Snapshot and restore local-character module state around each test."""
    # Cancel any debounce timer from previous tests, then null out the slot so
    # tests start from a known-clean state.
    if local_characters._save_timer is not None:
        local_characters._save_timer.cancel()
        local_characters._save_timer = None

    saved = {
        "LOCAL_CHARACTERS": dict(config.LOCAL_CHARACTERS),
        "LOCAL_CHARACTER_NAMES": set(config.LOCAL_CHARACTER_NAMES),
        "LOCAL_ACCOUNTS": dict(config.LOCAL_ACCOUNTS),
        "LOCAL_ACCOUNT_NAME_MAP": dict(config.LOCAL_ACCOUNT_NAME_MAP),
        "AUTO_ADD": config.AUTO_ADD_LOCAL_CHARACTERS,
        "LOCAL_CHARACTERS_FILE": config.LOCAL_CHARACTERS_FILE,
        "pending": local_characters._pending_local_account,
        "on_updated": list(local_characters.ON_UPDATED),
    }

    config.LOCAL_CHARACTERS.clear()
    config.LOCAL_CHARACTER_NAMES.clear()
    local_characters._pending_local_account = None
    local_characters.ON_UPDATED.clear()

    monkeypatch.setattr(config, "LOCAL_CHARACTERS_FILE", str(tmp_path / "local_characters.csv"))

    yield

    # Drain any timer a test kicked off so the after-test thread doesn't write
    # into a later test's tmp_path or stale config dict.
    if local_characters._save_timer is not None:
        local_characters._save_timer.cancel()
        local_characters._save_timer = None

    config.LOCAL_CHARACTERS.clear()
    config.LOCAL_CHARACTERS.update(saved["LOCAL_CHARACTERS"])
    config.LOCAL_CHARACTER_NAMES.clear()
    config.LOCAL_CHARACTER_NAMES.update(saved["LOCAL_CHARACTER_NAMES"])
    config.LOCAL_ACCOUNTS.clear()
    config.LOCAL_ACCOUNTS.update(saved["LOCAL_ACCOUNTS"])
    config.LOCAL_ACCOUNT_NAME_MAP.clear()
    config.LOCAL_ACCOUNT_NAME_MAP.update(saved["LOCAL_ACCOUNT_NAME_MAP"])
    config.AUTO_ADD_LOCAL_CHARACTERS = saved["AUTO_ADD"]
    local_characters._pending_local_account = saved["pending"]
    local_characters.ON_UPDATED[:] = saved["on_updated"]
