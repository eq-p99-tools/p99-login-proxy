import logging

import httpx

from p99_sso_login_proxy import config

logger = logging.getLogger("sso_api")


def _get_verify():
    """Get the SSL verification setting (custom CA bundle path or True)."""
    return config.SSO_CA_BUNDLE


def check_sso_login(username: str, password: str) -> tuple[str, str]:
    """
    Check the SSO login credentials.

    Args:
        username (str): The username to check.
        password (str): The password to check.

    Returns:
        tuple[str, str]: A tuple containing the real username and password.
    """
    logger.info("Checking login for %s", username)
    logger.debug("Using CA bundle: %s", _get_verify())

    response = httpx.post(
        f"{config.SSO_API}/auth",
        json={"username": username, "password": password},
        timeout=config.SSO_TIMEOUT,
        verify=_get_verify(),
    )

    if response.status_code != 200:
        return None, None

    data = response.json()
    return data["real_user"], data["real_pass"]
