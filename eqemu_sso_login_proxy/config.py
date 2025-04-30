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

ENCRYPTION_KEY = hex_to_bytes(CONFIG.get("encryption", "key", fallback="\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00"))
ENCRYPTION_IV = hex_to_bytes(CONFIG.get("encryption", "iv", fallback="\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00"))

EQEMU_LOGIN_HOST = CONFIG.get("DEFAULT", "login_server", fallback="login.eqemulator.net")
EQEMU_PORT = CONFIG.getint("DEFAULT", "login_port", fallback=5998)
EQEMU_LOGIN_IP = socket.gethostbyname(EQEMU_LOGIN_HOST)
EQEMU_ADDR = (EQEMU_LOGIN_IP, EQEMU_PORT)

SSO_API = CONFIG.get("DEFAULT", "sso_api", fallback="https://proxy.p99loginproxy.net")
SSO_TIMEOUT = CONFIG.getint("DEFAULT", "sso_timeout", fallback=10)

ALWAYS_ON_TOP = CONFIG.getboolean("DEFAULT", "always_on_top", fallback=False)

def set_always_on_top(value: bool):
    CONFIG.set("DEFAULT", "always_on_top", str(value))
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)
