import datetime
import requests

from p99_sso_login_proxy import config


def fetch_user_accounts() -> list[str]:
    """
    Fetch the list of accounts associated with the provided API token.

    Returns:
        list[str]: A list of account names.
    """
    accounts = []
    real_account_count = 0

    if config.USER_API_TOKEN:
        # Use a custom CA bundle if provided in config, otherwise default
        verify = getattr(config, 'SSO_CA_BUNDLE', True)

        response = requests.post(f"{config.SSO_API}/list_accounts", json={
            "access_key": config.USER_API_TOKEN
        }, timeout=config.SSO_TIMEOUT, verify=verify)

        if response.status_code == 200:
            accounts = response.json().get("accounts", [])
            accounts = [account.lower() for account in accounts]
            real_account_count = response.json().get("count", 0)
            print(f"[SSO] Successfully fetched {real_account_count} accounts (and {len(accounts) - real_account_count} aliases/tags)")
        else:
            print(f"[SSO] Failed to fetch account list: {response.status_code} {response.text}")

    config.ACCOUNTS_CACHE = accounts
    config.ACCOUNTS_CACHE_REAL_COUNT = real_account_count
    config.ACCOUNTS_CACHE_TIMESTAMP = datetime.datetime.now()
    return accounts, real_account_count


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