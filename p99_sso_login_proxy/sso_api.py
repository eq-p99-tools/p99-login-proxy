import datetime
import requests

from p99_sso_login_proxy import config
from p99_sso_login_proxy import utils


def fetch_user_accounts():
    """
    Fetch the list of accounts associated with the provided API token.

    Returns:
        list[str]: A list of account names.
    """
    accounts = {}
    all_account_names = []
    real_account_count = 0

    if config.USER_API_TOKEN:
        # Use a custom CA bundle if provided in config, otherwise default
        verify = getattr(config, 'SSO_CA_BUNDLE', True)

        response = requests.post(f"{config.SSO_API}/list_accounts", json={
            "access_key": config.USER_API_TOKEN
        }, timeout=config.SSO_TIMEOUT, verify=verify)

        if response.status_code == 200:
            accounts = response.json().get("account_tree", {})
            real_account_names = accounts.keys()
            real_account_count = len(real_account_names)
            aliases = []
            tags = []
            characters = []

            for account_data in accounts.values():
                if account_data.get("aliases"):
                    aliases.extend(account_data.get("aliases"))
                if account_data.get("tags"):
                    tags.extend(account_data.get("tags"))
                if account_data.get("characters"):
                    characters.extend(account_data.get("characters"))

            dynamic_tag_zones = response.json().get("dynamic_tag_zones", {})
            dynamic_tag_classes = response.json().get("dynamic_tag_classes", {})
            dynamic_tags = utils.get_dynamic_tag_list(dynamic_tag_zones, dynamic_tag_classes)

            print(f"[SSO] Successfully fetched {real_account_count} accounts (and {len(aliases) + len(tags)} aliases/tags)")

            # Add real accounts, aliases, and tags to the flat login list
            all_account_names.extend(real_account_names)
            all_account_names.extend(aliases)
            all_account_names.extend(tags)
            all_account_names.extend(dynamic_tags)
        else:
            print(f"[SSO] Failed to fetch account list: {response.status_code} {response.text}")

    config.ALL_CACHED_NAMES = all_account_names
    config.ACCOUNTS_CACHE_REAL_COUNT = real_account_count
    config.ACCOUNTS_CACHE_TIMESTAMP = datetime.datetime.now()
    config.ACCOUNTS_CACHED = accounts

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