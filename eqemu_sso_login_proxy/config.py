import configparser
import socket


CONFIG = configparser.ConfigParser()
CONFIG.read("proxyconfig.ini")

APP_NAME = "P99 Login Proxy"

def hex_to_bytes(hex_str):
    return bytes.fromhex(hex_str.replace('\\x', ''))


def iv():
    return ENCRYPTION_IV[:]


LISTEN_HOST = CONFIG.get("DEFAULT", "listen_host", fallback="0.0.0.0")
LISTEN_PORT = CONFIG.getint("DEFAULT", "listen_port", fallback=5998)

TEST_USER = CONFIG.get("DEFAULT", "test_user").encode()
TEST_PASSWORD = CONFIG.get("DEFAULT", "test_password").encode()

ENCRYPTION_KEY = hex_to_bytes(CONFIG.get("encryption", "key"))
ENCRYPTION_IV = hex_to_bytes(CONFIG.get("encryption", "iv"))

SESSION_CLEANUP_INTERVAL = CONFIG.getint("DEFAULT", "session_cleanup_interval", fallback=5*60)

EQEMU_LOGIN_HOST = CONFIG.get("DEFAULT", "login_server", fallback="login.eqemulator.net")
EQEMU_PORT = CONFIG.getint("DEFAULT", "login_port", fallback=5998)
EQEMU_LOGIN_IP = socket.gethostbyname(EQEMU_LOGIN_HOST)
EQEMU_ADDR = (EQEMU_LOGIN_IP, EQEMU_PORT)

SSO_API = CONFIG.get("DEFAULT", "sso_api", fallback="https://proxy.p99loginproxy.net")

ALWAYS_ON_TOP = CONFIG.getboolean("DEFAULT", "always_on_top", fallback=False)

def set_always_on_top(value: bool):
    CONFIG.set("DEFAULT", "always_on_top", str(value))
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)
