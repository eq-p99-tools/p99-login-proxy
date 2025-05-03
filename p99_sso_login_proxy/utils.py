def hex_to_bytes(hex_str):
    return bytes.fromhex(hex_str.replace('\\x', ''))
