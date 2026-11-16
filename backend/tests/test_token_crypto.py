"""Tests for refresh-token encryption at rest."""

import pytest
from cryptography.fernet import Fernet

from services.token_crypto import TokenCryptoError, decrypt_token, encrypt_token


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())


def test_round_trip():
    assert decrypt_token(encrypt_token("1//refresh-token")) == "1//refresh-token"


def test_ciphertext_is_not_plaintext():
    assert "refresh-token" not in encrypt_token("1//refresh-token")


def test_missing_key_fails_closed(monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY")
    with pytest.raises(TokenCryptoError):
        encrypt_token("x")
    with pytest.raises(TokenCryptoError):
        decrypt_token("x")


def test_invalid_key_fails_closed(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(TokenCryptoError):
        encrypt_token("x")


def test_wrong_key_cannot_decrypt(monkeypatch):
    ct = encrypt_token("secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(TokenCryptoError):
        decrypt_token(ct)
