import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


CURRENT_KEY_VERSION = 1


def encrypt_value(plaintext: str, key: bytes, key_version: int = CURRENT_KEY_VERSION) -> str:
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    version_byte = key_version.to_bytes(1, "big")
    return (version_byte + nonce + ct).hex()


def decrypt_value(ciphertext_hex: str, key: bytes) -> tuple[str, int]:
    raw = bytes.fromhex(ciphertext_hex)
    key_version = raw[0]
    nonce = raw[1:13]
    ct = raw[13:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ct, None)
    return plaintext.decode("utf-8"), key_version


def mask_id_number(value: str) -> str:
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


def mask_dob(dob_str: str) -> str:
    parts = dob_str.split("/")
    if len(parts) == 3:
        return f"**/**/{ parts[2]}"
    return "**/**/****"


def mask_legal_name(name: str) -> str:
    if not name:
        return "****"
    return name[0] + "*" * (len(name) - 1)
