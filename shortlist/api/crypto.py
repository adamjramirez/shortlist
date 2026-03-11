"""Fernet encryption for storing user API keys."""
import os
from functools import lru_cache

from cryptography.fernet import Fernet


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY not set")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns base64-encoded ciphertext."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext. Returns plaintext."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
