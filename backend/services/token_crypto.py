"""Encryption at rest for OAuth refresh tokens (Fernet).

The key comes from ``TOKEN_ENCRYPTION_KEY`` (generate one with
``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``).
Every function fails closed: a missing or malformed key raises
``TokenCryptoError`` rather than falling back to plaintext.
"""

import os

from cryptography.fernet import Fernet, InvalidToken


class TokenCryptoError(Exception):
    """Encryption is unavailable (bad/missing key) or a ciphertext is unreadable."""


def _fernet() -> Fernet:
    key = os.getenv("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise TokenCryptoError("TOKEN_ENCRYPTION_KEY is not set")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as e:
        raise TokenCryptoError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key") from e


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise TokenCryptoError("Stored token could not be decrypted") from e
