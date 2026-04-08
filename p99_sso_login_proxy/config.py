import configparser
import datetime
import re
import socket

from p99_sso_login_proxy import __version_semver__, utils

CONFIG = configparser.ConfigParser()
CONFIG.optionxform = str
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
if __version_semver__.prerelease:
    SSO_API_OPTIONS.append(("Localhost", "http://localhost:5998"))

if CONFIG.has_section("sso_backends"):
    _known_names = {name for name, _ in SSO_API_OPTIONS}
    _default_keys = set(CONFIG.defaults())
    for name, url in CONFIG.items("sso_backends"):
        if name in _default_keys:
            continue
        if name not in _known_names:
            SSO_API_OPTIONS.append((name, url))
            _known_names.add(name)

SSO_API = CONFIG.get("DEFAULT", "sso_api", fallback=SSO_API_OPTIONS[0][1])
_url_to_name = {}
for _n, _u in SSO_API_OPTIONS:
    if _u not in _url_to_name:
        _url_to_name[_u] = _n
SSO_API_NAME = CONFIG.get("DEFAULT", "sso_api_name", fallback=_url_to_name.get(SSO_API, SSO_API))

SSO_TIMEOUT = CONFIG.getint("DEFAULT", "sso_timeout", fallback=10)
SSO_CA_BUNDLE = CONFIG.get("DEFAULT", "sso_ca_bundle", fallback=True)
SSO_VERIFY_TLS = CONFIG.getboolean("DEFAULT", "sso_verify_tls", fallback=True)

ALWAYS_ON_TOP = CONFIG.getboolean("DEFAULT", "always_on_top", fallback=False)

# Fusion dark theme (False = light palette + QSS)
DARK_MODE = CONFIG.getboolean("DEFAULT", "dark_mode", fallback=True)

WARN_RUSTLE = CONFIG.getboolean("DEFAULT", "warn_rustle", fallback=False)

OPT_INTO_PRERELEASES = CONFIG.getboolean("DEFAULT", "opt_into_prereleases", fallback=False)

EQ_DIRECTORY = CONFIG.get("DEFAULT", "eq_directory", fallback="")

# Optional second EverQuest install root: same role as eq_directory for Logs/, *-Inventory.txt, Rustle scan
EQ_SECONDARY_DIRECTORY = CONFIG.get("DEFAULT", "eq_secondary_directory", fallback="").strip()

# Whether to run in proxy-only mode (no SSO authentication)
PROXY_ONLY = CONFIG.getboolean("DEFAULT", "proxy_only", fallback=False)

# Whether to run in proxy mode
PROXY_ENABLED = CONFIG.getboolean("DEFAULT", "proxy_enabled", fallback=True)

# Per-backend API tokens keyed by backend display name
_API_TOKENS_SECTION = "api_tokens"
_legacy_token = CONFIG.get("DEFAULT", "user_api_token", fallback="")

if not CONFIG.has_section(_API_TOKENS_SECTION):
    CONFIG.add_section(_API_TOKENS_SECTION)
    if _legacy_token:
        CONFIG.set(_API_TOKENS_SECTION, SSO_API_NAME, _legacy_token)
        with open("proxyconfig.ini", "w") as _f:
            CONFIG.write(_f)

USER_API_TOKEN = CONFIG.get(_API_TOKENS_SECTION, SSO_API_NAME, fallback=_legacy_token)

# Variables to store account list and timestamp
ALL_CACHED_NAMES = []
ACCOUNTS_CACHED = {}
CHARACTERS_CACHED = []
ACCOUNTS_CACHE_REAL_COUNT = 0
ACCOUNTS_CACHE_TIMESTAMP = datetime.datetime.min

ACTIVITY_FADE_SECONDS = 90

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


def set_dark_mode(value: bool):
    _set_config("DARK_MODE", "dark_mode", value)


def set_proxy_only(value: bool):
    """Set whether to run in proxy-only mode"""
    _set_config("PROXY_ONLY", "proxy_only", value)


def get_api_token(name: str) -> str:
    """Return the stored API token for a given backend name."""
    return CONFIG.get(_API_TOKENS_SECTION, name, fallback="")


def set_api_token_for_backend(name: str, token: str):
    """Save an API token for a specific backend name.

    Also keeps the legacy user_api_token in DEFAULT in sync when
    the token belongs to the currently active backend.
    """
    CONFIG.set(_API_TOKENS_SECTION, name, token)
    if name == globals()["SSO_API_NAME"]:
        globals()["USER_API_TOKEN"] = token
        CONFIG.set("DEFAULT", "user_api_token", token)
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)


def set_sso_api(name: str, url: str) -> str:
    """Set the SSO API endpoint and swap the active API token.

    Returns the API token associated with the new backend.
    """
    globals()["SSO_API"] = url
    globals()["SSO_API_NAME"] = name
    CONFIG.set("DEFAULT", "sso_api", url)
    CONFIG.set("DEFAULT", "sso_api_name", name)
    token = get_api_token(name)
    globals()["USER_API_TOKEN"] = token
    CONFIG.set("DEFAULT", "user_api_token", token)
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)
    return token


def set_eq_directory(path: str):
    """Set the EverQuest directory override path"""
    _set_config("EQ_DIRECTORY", "eq_directory", path)


def set_proxy_enabled(value: bool):
    """Set whether to run in proxy mode"""
    _set_config("PROXY_ENABLED", "proxy_enabled", value)


TIMESTAMP = r"\[(?P<time>\w{3} \w{3} \d{2} \d\d:\d\d:\d\d \d{4})\] +"
MATCH_ENTERED_ZONE = re.compile(rf"{TIMESTAMP}You have entered (?P<zone>.*?)\.")
MATCH_WHO_ZONE = re.compile(rf"{TIMESTAMP}There (?:are|is) (?P<num>\d+) players? in (?P<zone>.+?)\.")
MATCH_WHO_SELF = re.compile(rf"{TIMESTAMP}\[(?P<level>\d+) [\w ]+\] (?P<name>\w+) ")
MATCH_CHARINFO = re.compile(f"{TIMESTAMP}You are currently bound in: (?P<zone>.*)")
MATCH_BIND_CONFIRM = re.compile(rf"{TIMESTAMP}You feel yourself bind to the area\.")
MATCH_LEVEL_UP = re.compile(rf"{TIMESTAMP}You have gained a level! Welcome to level (?P<level>\d+)!")
MATCH_FTE = re.compile(rf"{TIMESTAMP}(?P<mob>.+?) engages (?P<player>\w+)!")
MATCH_YOU_SLAIN = re.compile(rf"{TIMESTAMP}You have slain (?P<mob>.+?)!")
MATCH_MOB_SLAIN = re.compile(rf"{TIMESTAMP}(?P<mob>.+?) has been slain by (?P<slayer>.+?)!")
MATCH_VELIUM_VAPORS_GLOW = re.compile(rf"{TIMESTAMP}Your Vial of Velium Vapors begins to glow\.")

# Static lowercased names for raid targets whose death lines are relayed to Discord (see log_handler).
RAID_TARGETS = frozenset(
    name.lower()
    for name in (
        "a broken golem",
        "a dracoliche",
        "an angry goblin",
        "Aaryonar",
        "Casalen",
        "Cazic Thule",
        "Cekenar",
        "Dagarn the Destroyer",
        "Dain Frostreaver IV",
        "Derakor the Vindicator",
        "Dozekar the Cursed",
        "Dread",
        "Druushk",
        "Eashen of the Sky",
        "Essedera",
        "Faydedar",
        "Fright",
        "Gorenaire",
        "Gozzrem",
        "Grozzmel",
        "Guardian Kozzalym",
        "Hoshkar",
        "Ikatiar the Venom",
        "Innoruuk",
        "Jorlleag",
        "Kelorek`Dar",
        "Keldor Dek`Torek",
        "King Tormax",
        "Klandicar",
        "Krigara",
        "Lady Mirenilla",
        "Lady Nevederia",
        "Lady Vox",
        "Lendiniara the Keeper",
        "Lepethida",
        "Lodizal",
        "Lord Doljonijiarnimorinar",
        "Lord Feshlak",
        "Lord Kreizenn",
        "Lord Koi`Doken",
        "Lord Nagafen",
        "Lord Vyemm",
        "Lord Yelinak",
        "Master of the Guard",
        "Master Yael",
        "Midayor",
        "Myga",
        "Narandi the Wretched",
        "Nexona",
        "Nillipuss",
        "Noble Dojorn",
        "Phara Dar",
        "Phinigel Autropos",
        "Sevalak",
        "Severilous",
        "Silverwing",
        "Sir Lucan D`Lere",
        "Sontalak",
        "Stormfeather",
        "Talendor",
        "Tavekalem",
        "Telkorenar",
        "Terror",
        "The Final Arbiter",
        "The Progenitor",
        "The Statue of Rallos Zek",
        "Trakanon",
        "Tunare",
        "Vaniki",
        "Velketor the Sorcerer",
        "Venril Sathir",
        "Verina Tomb",
        "Vessel Drozlin",
        "Vilefang",
        "Vulak`Aerr",
        "Wraith of a Shissir",
        "Wuoshi",
        "Xygoz",
        "Ymmeln",
        "Zlandicar",
        "Zlexak",
        "Zordak Ragefire",
    )
)
