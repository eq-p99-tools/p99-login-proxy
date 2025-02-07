import configparser

CONFIG = configparser.ConfigParser()
CONFIG.read("proxyconfig.ini")


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
