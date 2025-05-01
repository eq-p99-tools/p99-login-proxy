import configparser
import socket
import semver
import base64
import os
import json
from pathlib import Path
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad, unpad
from Cryptodome.Random import get_random_bytes


CONFIG = configparser.ConfigParser()
CONFIG.read("proxyconfig.ini")

APP_NAME = "P99 Login Proxy"
APP_VERSION = semver.Version(
    major=1,
    minor=0,
    patch=0,
    prerelease="rc3"
)

def hex_to_bytes(hex_str):
    return bytes.fromhex(hex_str.replace('\\x', ''))


def iv():
    return ENCRYPTION_IV[:]


# Get the application data directory for storing encryption keys
def get_app_data_dir():
    """Get the application data directory for storing encryption keys"""
    app_name = "P99LoginProxy"
    if os.name == 'nt':  # Windows
        app_data = os.environ.get('APPDATA')
        if app_data:
            return Path(app_data) / app_name
    else:  # Linux/Mac
        app_data = os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')
        return Path(app_data) / app_name
    
    # Fallback to current directory if we can't find AppData
    return Path(os.getcwd()) / '.p99proxy'

# Ensure the app data directory exists
app_data_dir = get_app_data_dir()
app_data_dir.mkdir(parents=True, exist_ok=True)

# Path to the encryption keys file
keys_file = app_data_dir / 'encryption_keys.json'

# Generate or load encryption keys
def get_encryption_keys():
    """Generate or load encryption keys"""
    if keys_file.exists():
        try:
            with open(keys_file, 'r') as f:
                keys_data = json.load(f)
                password_key = base64.b64decode(keys_data.get('password_key'))
                password_iv = base64.b64decode(keys_data.get('password_iv'))
                return password_key, password_iv
        except Exception as e:
            print(f"Error loading encryption keys: {e}")
            # If there's an error, we'll generate new keys
    
    # Generate new keys
    password_key = get_random_bytes(16)  # AES-128 key
    password_iv = get_random_bytes(16)   # AES block size
    
    # Save the keys
    try:
        with open(keys_file, 'w') as f:
            keys_data = {
                'password_key': base64.b64encode(password_key).decode('utf-8'),
                'password_iv': base64.b64encode(password_iv).decode('utf-8')
            }
            json.dump(keys_data, f)
    except Exception as e:
        print(f"Error saving encryption keys: {e}")
    
    return password_key, password_iv

# Get the encryption keys
PASSWORD_ENCRYPTION_KEY, PASSWORD_ENCRYPTION_IV = get_encryption_keys()


def encrypt_password(password):
    """Encrypt a password using AES"""
    if not password:
        return ""
    cipher = AES.new(PASSWORD_ENCRYPTION_KEY, AES.MODE_CBC, PASSWORD_ENCRYPTION_IV)
    ct_bytes = cipher.encrypt(pad(password.encode('utf-8'), AES.block_size))
    return base64.b64encode(ct_bytes).decode('utf-8')


def decrypt_password(encrypted_password):
    """Decrypt a password using AES"""
    if not encrypted_password:
        return ""
    try:
        ct_bytes = base64.b64decode(encrypted_password)
        cipher = AES.new(PASSWORD_ENCRYPTION_KEY, AES.MODE_CBC, PASSWORD_ENCRYPTION_IV)
        pt_bytes = unpad(cipher.decrypt(ct_bytes), AES.block_size)
        return pt_bytes.decode('utf-8')
    except Exception:
        # If decryption fails, return empty string
        return ""


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
SSO_CA_BUNDLE = CONFIG.get("DEFAULT", "sso_ca_bundle", fallback=True)

ALWAYS_ON_TOP = CONFIG.getboolean("DEFAULT", "always_on_top", fallback=False)

# Get the encrypted debug password from config
ENCRYPTED_DEBUG_PASSWORD = CONFIG.get("DEFAULT", "debug_password", fallback="")

# Decrypt the password for use
DEBUG_PASSWORD = decrypt_password(ENCRYPTED_DEBUG_PASSWORD)

def set_always_on_top(value: bool):
    CONFIG.set("DEFAULT", "always_on_top", str(value))
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)


def set_debug_password(password: str):
    """Encrypt and store the debug password"""
    encrypted = encrypt_password(password)
    CONFIG.set("DEFAULT", "debug_password", encrypted)
    global ENCRYPTED_DEBUG_PASSWORD, DEBUG_PASSWORD
    ENCRYPTED_DEBUG_PASSWORD = encrypted
    DEBUG_PASSWORD = password
    with open("proxyconfig.ini", "w") as configfile:
        CONFIG.write(configfile)
