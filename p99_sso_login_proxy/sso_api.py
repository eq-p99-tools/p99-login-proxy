import requests

from p99_sso_login_proxy import config


def check_sso_login(username: str, password: str) -> tuple[str, str]:
    """
    Check the SSO login credentials.
    
    Args:
        username (str): The username to check.
        password (str): The password to check.
        
    Returns:
        tuple[str, str]: A tuple containing the real username and password.
    """
    print(f"[SSO] Checking login for {username}")
    # Use a custom CA bundle if provided in config, otherwise default
    verify = getattr(config, 'SSO_CA_BUNDLE', True)
    print(f"[SSO] Using CA bundle: {verify}")

    response = requests.post(f"{config.SSO_API}/auth", json={
        "username": username,
        "password": password
    }, timeout=config.SSO_TIMEOUT, verify=verify)

    if response.status_code != 200:
        return None, None

    return response.json()["real_user"], response.json()["real_pass"]