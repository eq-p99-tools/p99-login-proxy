import contextlib
import logging

import httpx

from p99_sso_login_proxy import __version__, config

logger = logging.getLogger("sso_api")


def _get_verify():
    """Get the SSL verification setting (custom CA bundle path or True)."""
    return config.SSO_CA_BUNDLE


def check_sso_login(
    username: str,
    password: str,
    client_settings: dict | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Synchronous SSO login check (kept for backward compatibility).

    Returns ``(real_user, real_pass, error_detail)``.
    """
    logger.info("Checking login for %s", username)
    logger.debug("Using CA bundle: %s", _get_verify())

    body: dict = {"username": username, "password": password}
    if client_settings is not None:
        body["client_settings"] = client_settings

    response = httpx.post(
        f"{config.SSO_API}/auth",
        json=body,
        headers={"X-Client-Version": __version__},
        timeout=config.SSO_TIMEOUT,
        verify=_get_verify(),
    )

    if response.status_code != 200:
        detail: str | None = None
        with contextlib.suppress(Exception):
            detail = response.json().get("detail")
        return None, None, detail

    data = response.json()
    return data["real_user"], data["real_pass"], None
