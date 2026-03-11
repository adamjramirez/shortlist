"""Tests for API key encryption."""
import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def set_encryption_key(monkeypatch):
    from shortlist.api.crypto import _get_fernet
    _get_fernet.cache_clear()
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)


def test_encrypt_decrypt():
    from shortlist.api.crypto import encrypt, decrypt

    plaintext = "sk-ant-api03-very-secret-key"
    ciphertext = encrypt(plaintext)
    assert ciphertext != plaintext
    assert decrypt(ciphertext) == plaintext


def test_different_encryptions_differ():
    from shortlist.api.crypto import encrypt

    c1 = encrypt("same-key")
    c2 = encrypt("same-key")
    assert c1 != c2  # Fernet uses random IV


def test_decrypt_with_wrong_key(monkeypatch):
    from shortlist.api.crypto import encrypt, decrypt, _get_fernet

    ciphertext = encrypt("secret")

    # Change key and clear cache so new Fernet is created
    _get_fernet.cache_clear()
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())

    with pytest.raises(Exception):
        decrypt(ciphertext)


def test_missing_encryption_key(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    from shortlist.api.crypto import _get_fernet

    _get_fernet.cache_clear()
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY not set"):
        _get_fernet()
