import base64
import json
import os

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad, unpad
from Cryptodome.Random import get_random_bytes
import pathlib

def hex_to_bytes(hex_str):
    return bytes.fromhex(hex_str.replace('\\x', ''))


# Get the application data directory for storing encryption keys
def get_app_data_dir():
    """Get the application data directory for storing encryption keys"""
    app_name = "P99LoginProxy"
    if os.name == 'nt':  # Windows
        app_data = os.environ.get('APPDATA')
        if app_data:
            return pathlib.Path(app_data) / app_name
    else:  # Linux/Mac
        app_data = os.environ.get('XDG_DATA_HOME', pathlib.Path.home() / '.local' / 'share')
        return pathlib.Path(app_data) / app_name
    
    # Fallback to current directory if we can't find AppData
    return pathlib.Path(os.getcwd()) / '.p99proxy'


# Generate or load encryption keys
def get_encryption_keys(keys_file):
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


def encrypt_password(password, encryption_key, encryption_iv):
    """Encrypt a password using AES"""
    if not password:
        return ""
    cipher = AES.new(encryption_key, AES.MODE_CBC, iv(encryption_iv))
    ct_bytes = cipher.encrypt(pad(password.encode('utf-8'), AES.block_size))
    return base64.b64encode(ct_bytes).decode('utf-8')

def decrypt_password(encrypted_password, encryption_key, encryption_iv):
    """Decrypt a password using AES"""
    if not encrypted_password:
        return ""
    try:
        ct_bytes = base64.b64decode(encrypted_password)
        cipher = AES.new(encryption_key, AES.MODE_CBC, iv(encryption_iv))
        pt_bytes = unpad(cipher.decrypt(ct_bytes), AES.block_size)
        return pt_bytes.decode('utf-8')
    except Exception:
        # If decryption fails, return empty string
        return ""


def iv(encryption_iv):
    return encryption_iv[:]
