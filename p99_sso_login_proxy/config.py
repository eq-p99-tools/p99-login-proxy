import configparser
import datetime
import re
import socket

from p99_sso_login_proxy import __version_semver__
from p99_sso_login_proxy import utils

CONFIG = configparser.ConfigParser()
CONFIG.read("proxyconfig.ini")

APP_NAME = "P99 Login Proxy"
APP_VERSION = __version_semver__
CHANGELOG = ""

LISTEN_HOST = CONFIG.get("DEFAULT", "listen_host", fallback="0.0.0.0")
LISTEN_PORT = CONFIG.getint("DEFAULT", "listen_port", fallback=5998)

ENCRYPTION_KEY = utils.hex_to_bytes(
    CONFIG.get("encryption", "key", fallback="\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00")
)
ENCRYPTION_IV = utils.hex_to_bytes(CONFIG.get("encryption", "iv", fallback="\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00"))

EQEMU_LOGIN_HOST = CONFIG.get("DEFAULT", "login_server", fallback="login.eqemulator.net")
EQEMU_PORT = CONFIG.getint("DEFAULT", "login_port", fallback=5998)
try:
    EQEMU_LOGIN_IP = socket.gethostbyname(EQEMU_LOGIN_HOST)
except socket.gaierror:
    # Fall back to the hostname itself if DNS resolution fails (e.g. no internet)
    EQEMU_LOGIN_IP = EQEMU_LOGIN_HOST
EQEMU_ADDR = (EQEMU_LOGIN_IP, EQEMU_PORT)

SSO_API_OPTIONS = [
    ("P99 Login Proxy", "https://proxy.p99loginproxy.net"),
]

SSO_API = CONFIG.get("DEFAULT", "sso_api", fallback=SSO_API_OPTIONS[0][1])
SSO_TIMEOUT = CONFIG.getint("DEFAULT", "sso_timeout", fallback=10)
SSO_CA_BUNDLE = CONFIG.get("DEFAULT", "sso_ca_bundle", fallback=True)

ALWAYS_ON_TOP = CONFIG.getboolean("DEFAULT", "always_on_top", fallback=False)

EQ_DIRECTORY = CONFIG.get("DEFAULT", "eq_directory", fallback="")

# Whether to run in proxy-only mode (no SSO authentication)
PROXY_ONLY = CONFIG.getboolean("DEFAULT", "proxy_only", fallback=False)

# Whether to run in proxy mode
PROXY_ENABLED = CONFIG.getboolean("DEFAULT", "proxy_enabled", fallback=True)

# Get the user API token from config
USER_API_TOKEN = CONFIG.get("DEFAULT", "user_api_token", fallback="")

# Variables to store account list and timestamp
ALL_CACHED_NAMES = []
ACCOUNTS_CACHED = {}
CHARACTERS_CACHED = []
ACCOUNTS_CACHE_REAL_COUNT = 0
ACCOUNTS_CACHE_TIMESTAMP = datetime.datetime.min

LOCAL_ACCOUNTS_FILE = CONFIG.get("DEFAULT", "local_accounts_file", fallback="local_accounts.csv")
LOCAL_ACCOUNTS, LOCAL_ACCOUNT_NAME_MAP = utils.load_local_accounts(LOCAL_ACCOUNTS_FILE)

# Allow the user to provide a list of accounts to never SSO check
SKIP_SSO_ACCOUNTS = CONFIG.get("DEFAULT", "skip_sso_accounts", fallback="")
SKIP_SSO_ACCOUNTS = [account.strip().lower() for account in SKIP_SSO_ACCOUNTS.split(",")]


def iv():
    return ENCRYPTION_IV[:]


def _set_config(global_name: str, config_key: str, value):
    """Update a module-level config global, persist it to proxyconfig.ini."""
    globals()[global_name] = value
    CONFIG.set("DEFAULT", config_key, str(value))
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)


def set_always_on_top(value: bool):
    _set_config("ALWAYS_ON_TOP", "always_on_top", value)


def set_proxy_only(value: bool):
    """Set whether to run in proxy-only mode"""
    _set_config("PROXY_ONLY", "proxy_only", value)


def set_user_api_token(token: str):
    """Store the user API token"""
    _set_config("USER_API_TOKEN", "user_api_token", token)


def set_sso_api(url: str):
    """Set the SSO API endpoint URL"""
    _set_config("SSO_API", "sso_api", url)


def set_eq_directory(path: str):
    """Set the EverQuest directory override path"""
    _set_config("EQ_DIRECTORY", "eq_directory", path)


def set_proxy_enabled(value: bool):
    """Set whether to run in proxy mode"""
    _set_config("PROXY_ENABLED", "proxy_enabled", value)


TIMESTAMP = r"\[(?P<time>\w{3} \w{3} \d{2} \d\d:\d\d:\d\d \d{4})\] +"
MATCH_ENTERED_ZONE = re.compile(f"{TIMESTAMP}You have entered (?P<zone>.*?)\.")
MATCH_CHARINFO = re.compile(f"{TIMESTAMP}You are currently bound in: (?P<zone>.*)")
