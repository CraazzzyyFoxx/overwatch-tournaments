"""AES-256-GCM sealing for short secrets kept at rest (OAuth provider tokens).

``encrypt`` returns ``"v1." + base64url(nonce12 + ciphertext_with_tag)`` (unpadded); ``decrypt`` hands back any
value without the ``v1.`` prefix unchanged, so rows written before sealing existed keep reading until they are
re-sealed. The key is ``OAUTH_TOKEN_ENCRYPTION_KEY``: 32 random bytes, base64url.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

__all__ = ("PREFIX", "decrypt", "encrypt", "load_key")

PREFIX = "v1."
_NONCE_BYTES = 12
_KEY_BYTES = 32


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_key(value: str | None) -> bytes:
    """The 32-byte key from its base64url setting (padding optional); ``ValueError`` when unset or malformed."""
    if not value:
        raise ValueError("encryption key is not set")
    try:
        key = _b64decode(value.strip())
    except ValueError as exc:
        raise ValueError("encryption key is not base64url") from exc
    if len(key) != _KEY_BYTES:
        raise ValueError(f"encryption key must decode to {_KEY_BYTES} bytes, got {len(key)}")
    return key


def encrypt(plaintext: str, key: bytes) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode("ascii").rstrip("=")


def decrypt(value: str, key: bytes) -> str:
    """``value`` in clear. A value without the prefix is legacy plaintext and comes back as is.

    Raises ``ValueError`` when a sealed value does not open with ``key`` (wrong key, or tampered).
    """
    if not value.startswith(PREFIX):
        return value
    try:
        raw = _b64decode(value[len(PREFIX) :])
        return AESGCM(key).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], None).decode("utf-8")
    except (InvalidTag, ValueError) as exc:
        raise ValueError("sealed value does not open with this key") from exc
