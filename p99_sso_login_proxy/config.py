import configparser
import socket
import semver



from p99_sso_login_proxy import utils


CONFIG = configparser.ConfigParser()
CONFIG.read("proxyconfig.ini")

APP_NAME = "P99 Login Proxy"
APP_VERSION = semver.Version(
    major=1,
    minor=0,
    patch=0,
    prerelease="rc5"
)

# Ensure the app data directory exists
app_data_dir = utils.get_app_data_dir()
app_data_dir.mkdir(parents=True, exist_ok=True)

# Path to the encryption keys file
keys_file = app_data_dir / 'encryption_keys.json'

# Get the encryption keys
PASSWORD_ENCRYPTION_KEY, PASSWORD_ENCRYPTION_IV = utils.get_encryption_keys(keys_file)

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

# Get the encrypted debug password from config
ENCRYPTED_DEBUG_PASSWORD = CONFIG.get("DEFAULT", "debug_password", fallback="")

# Decrypt the password for use
DEBUG_PASSWORD = utils.decrypt_password(ENCRYPTED_DEBUG_PASSWORD, PASSWORD_ENCRYPTION_KEY, PASSWORD_ENCRYPTION_IV)

# Allow the user to provide a list of accounts to never SSO check
SKIP_SSO_ACCOUNTS = CONFIG.get("DEFAULT", "skip_sso_accounts", fallback="")
SKIP_SSO_ACCOUNTS = [account.strip() for account in SKIP_SSO_ACCOUNTS.split(",")]

iv = lambda: utils.iv(ENCRYPTION_IV)

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


def set_debug_password(password: str):
    """Encrypt and store the debug password"""
    encrypted = utils.encrypt_password(password, PASSWORD_ENCRYPTION_KEY, PASSWORD_ENCRYPTION_IV)
    CONFIG.set("DEFAULT", "debug_password", encrypted)
    global ENCRYPTED_DEBUG_PASSWORD, DEBUG_PASSWORD
    ENCRYPTED_DEBUG_PASSWORD = encrypted
    DEBUG_PASSWORD = password
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)
        CONFIG.write(configfile)
