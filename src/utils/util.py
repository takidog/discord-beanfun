from Crypto.Cipher import DES
import json
import re
import ssl


SSL_CTX = ssl.create_default_context()
# aiohttp.client_exceptions.ClientConnectorError: Cannot connect to host tw.beanfun.com:443 ssl:default [None]
SSL_CTX.set_ciphers(
    'ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:ECDH+AESGCM:DH+AESGCM:ECDH+AES256:DH+AES256:ECDH+AES128:DH+AES:ECDH+3DES:DH+3DES:RSA+AESGCM:RSA+AES:RSA+3DES:!aNULL:!MD5')  # noqa: E501


def extract_json(s):
    match = re.search(r'\{.*\}', s)
    if match:
        json_str = match.group(0)
        return json.loads(json_str)
    return {}


def decrypt_des_pkcs5_hex(text):
    # Split the text on ";"
    parts = text.split(";")

    # Check if the split parts are valid
    if len(parts) < 2:
        print("Decryption failed: value array is empty or length < 2")
        raise ValueError()

    # Extract key and encrypted value
    key = parts[1][:8]
    encrypted_value = bytes.fromhex(parts[1][8:])

    # Create a new DES cipher object
    cipher = DES.new(key.encode(), DES.MODE_ECB)

    # Decrypt the value
    try:
        decrypted_value = cipher.decrypt(encrypted_value).decode().rstrip('\0')
    except Exception as e:
        print(f"Decryption failed: {e}")
        raise ValueError()

    return decrypted_value
