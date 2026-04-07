"""Cron-style scheduling for automatic update checks (daily at local noon)."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from p99_sso_login_proxy import updater

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# If the machine sleeps past the scheduled run, still fire within this window (seconds)
_MISFIRE_GRACE_SEC = 3600


def start() -> None:
    """Start a background scheduler: silent update check every day at 12:00 local time."""
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        updater.check_update,
        "cron",
        hour=12,
        minute=0,
        id="p99_update_check_noon",
        misfire_grace_time=_MISFIRE_GRACE_SEC,
    )
    _scheduler.start()
    logger.info("Scheduled automatic update checks daily at 12:00 (local time)")


def shutdown() -> None:
    """Stop the scheduler (e.g. on application exit)."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.debug("Update scheduler stopped")
