from Crypto.Cipher import DES
import json
import re
import ssl

from utils.config import HIDDEN_PRIVATE_MESSAGE


SSL_CTX = ssl.create_default_context()
# aiohttp.client_exceptions.ClientConnectorError: Cannot connect to host tw.beanfun.com:443 ssl:default [None]
SSL_CTX.set_ciphers(
    "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:ECDH+AESGCM:DH+AESGCM:ECDH+AES256:DH+AES256:ECDH+AES128:DH+AES:ECDH+3DES:DH+3DES:RSA+AESGCM:RSA+AES:RSA+3DES:!aNULL:!MD5"  # noqa: E501
)


def extract_json(s, double_quotes: bool = False):
    match = re.search(r"\{.*\}", s)
    if match:
        json_str = match.group(0)
        if double_quotes:
            json_str = re.sub(r"(\w+)\s*:", r'"\1":', json_str)
        return json.loads(json_str)
    return {}


def decrypt_des_pkcs5_hex(text):
    # Split the text on ";"
    # The OTP endpoint returns the bare payload; the older handlers prefixed it
    # with a status segment.
    parts = text.split(";")
    payload = parts[1] if len(parts) > 1 else parts[0]

    if not payload:
        print("Decryption failed: empty payload")
        raise ValueError()

    # Extract key and encrypted value
    key = payload[:8]
    encrypted_value = bytes.fromhex(payload[8:])

    # Create a new DES cipher object
    cipher = DES.new(key.encode(), DES.MODE_ECB)

    # Decrypt the value
    try:
        decrypted_value = cipher.decrypt(encrypted_value).decode().rstrip("\0")
    except Exception as e:
        print(f"Decryption failed: {e}")
        raise ValueError()

    return decrypted_value


def hidden_message(msg):
    if HIDDEN_PRIVATE_MESSAGE:
        return f"||{msg}||"
    return msg
