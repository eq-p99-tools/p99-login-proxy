import configparser
import socket
import datetime

from p99_sso_login_proxy import __version_semver__
from p99_sso_login_proxy import utils

CONFIG = configparser.ConfigParser()
CONFIG.read("proxyconfig.ini")

APP_NAME = "P99 Login Proxy"
APP_VERSION = __version_semver__

LISTEN_HOST = CONFIG.get("DEFAULT", "listen_host", fallback="0.0.0.0")
LISTEN_PORT = CONFIG.getint("DEFAULT", "listen_port", fallback=5998)

ENCRYPTION_KEY = utils.hex_to_bytes(CONFIG.get("encryption", "key", fallback="\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00"))
ENCRYPTION_IV = utils.hex_to_bytes(CONFIG.get("encryption", "iv", fallback="\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00"))

EQEMU_LOGIN_HOST = CONFIG.get("DEFAULT", "login_server", fallback="login.eqemulator.net")
EQEMU_PORT = CONFIG.getint("DEFAULT", "login_port", fallback=5998)
EQEMU_LOGIN_IP = socket.gethostbyname(EQEMU_LOGIN_HOST)
EQEMU_ADDR = (EQEMU_LOGIN_IP, EQEMU_PORT)

SSO_API = CONFIG.get("DEFAULT", "sso_api", fallback="https://proxy.p99loginproxy.net")
SSO_TIMEOUT = CONFIG.getint("DEFAULT", "sso_timeout", fallback=10)
SSO_CA_BUNDLE = CONFIG.get("DEFAULT", "sso_ca_bundle", fallback=True)

ALWAYS_ON_TOP = CONFIG.getboolean("DEFAULT", "always_on_top", fallback=False)

# Whether to run in proxy-only mode (no SSO authentication)
PROXY_ONLY = CONFIG.getboolean("DEFAULT", "proxy_only", fallback=False)

# Whether to run in proxy mode
PROXY_ENABLED = CONFIG.getboolean("DEFAULT", "proxy_enabled", fallback=True)

# Get the user API token from config
USER_API_TOKEN = CONFIG.get("DEFAULT", "user_api_token", fallback="")

# Variables to store account list and timestamp
ACCOUNTS_CACHE = []
ACCOUNTS_CACHE_REAL_COUNT = 0
ACCOUNTS_CACHE_TIMESTAMP = datetime.datetime.min

# Allow the user to provide a list of accounts to never SSO check
SKIP_SSO_ACCOUNTS = CONFIG.get("DEFAULT", "skip_sso_accounts", fallback="")
SKIP_SSO_ACCOUNTS = [account.strip().lower() for account in SKIP_SSO_ACCOUNTS.split(",")]


def iv():
    return ENCRYPTION_IV[:]


def set_always_on_top(value: bool):
    CONFIG.set("DEFAULT", "always_on_top", str(value))
    global ALWAYS_ON_TOP
    ALWAYS_ON_TOP = value
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)


def set_proxy_only(value: bool):
    """Set whether to run in proxy-only mode"""
    CONFIG.set("DEFAULT", "proxy_only", str(value))
    global PROXY_ONLY
    PROXY_ONLY = value
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)


def set_user_api_token(token: str):
    """Store the user API token"""
    global USER_API_TOKEN
    USER_API_TOKEN = token
    CONFIG.set("DEFAULT", "user_api_token", token)
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)


def set_proxy_enabled(value: bool):
    """Set whether to run in proxy mode"""
    CONFIG.set("DEFAULT", "proxy_enabled", str(value))
    global PROXY_ENABLED
    PROXY_ENABLED = value
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)
