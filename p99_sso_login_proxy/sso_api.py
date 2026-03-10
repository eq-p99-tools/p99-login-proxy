import logging

import httpx

from p99_sso_login_proxy import config
from p99_sso_login_proxy import __version__

logger = logging.getLogger("sso_api")


def _get_verify():
    """Get the SSL verification setting (custom CA bundle path or True)."""
    return config.SSO_CA_BUNDLE


def check_sso_login(
    username: str,
    password: str,
    client_settings: dict | None = None,
) -> tuple[str | None, str | None, str | None]:
    """
    Check the SSO login credentials.

    Args:
        username (str): The username to check.
        password (str): The password to check (access key).
        client_settings (dict | None): Optional client settings to send
            (e.g. ``{"log_enabled": True}``).

    Returns:
        tuple[str | None, str | None, str | None]:
            ``(real_user, real_pass, error_detail)`` where ``error_detail``
            is a human-readable rejection reason from the server, or ``None``
            on success.
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
        try:
            detail = response.json().get("detail")
        except Exception:
            pass
        return None, None, detail

    data = response.json()
    return data["real_user"], data["real_pass"], None
