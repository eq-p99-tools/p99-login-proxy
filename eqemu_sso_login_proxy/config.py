import configparser

CONFIG = configparser.ConfigParser()
CONFIG.read("proxyconfig.ini")


def hex_to_bytes(hex_str):
    return bytes.fromhex(hex_str.replace('\\x', ''))


TEST_USER = CONFIG.get("DEFAULT", "test_user").encode()
TEST_PASSWORD = CONFIG.get("DEFAULT", "test_password").encode()

ENCRYPTION_KEY = hex_to_bytes(CONFIG.get("encryption", "key"))
ENCRYPTION_IV = hex_to_bytes(CONFIG.get("encryption", "iv"))


def iv():
    return ENCRYPTION_IV[:]
