"""Domain-separated key derivation for the identity service.

Derives a distinct 32-byte subkey per purpose (refresh-token hashing, OAuth
``state`` signing, API-key secret hashing, the JWT signing key) from the master
secret with HKDF-SHA256 (RFC 5869, stdlib ``hashlib`` + ``hmac``). One key shared
across domains means a weakness or leak in any one usage compromises all of them
and opens cross-protocol confusion attacks.

Notes:
  * Access/service JWTs are signed with Ed25519 (EdDSA) whose 32-byte seed is
    ``jwt_signing_seed``; the gateway holds only the public key. The raw master
    secret is only read to accept legacy HS256 tokens during the post-upgrade
    window (``security.TokenCodec``).
  * Refresh-token and API-key hashes are verified against BOTH the derived and
    the raw-secret HMAC (``legacy_hmac_sha256_hex``) but written only in the
    derived form, so already-persisted hashes keep verifying.
"""

from __future__ import annotations

import hashlib
import hmac

# Bump the version suffix if a subkey ever needs rotation independent of the
# master secret.
_INFO_REFRESH_TOKEN = b"anak-identity:refresh-token:v1"
_INFO_OAUTH_STATE = b"anak-identity:oauth-state:v1"
_INFO_API_KEY = b"anak-identity:api-key:v1"
_INFO_JWT_SIGNING = b"anak-identity:jwt-signing:v1"

_HASH = hashlib.sha256
_HASH_LEN = _HASH().digest_size  # 32


def _hkdf(ikm: bytes, info: bytes, length: int = _HASH_LEN, salt: bytes = b"") -> bytes:
    """RFC 5869 HKDF-SHA256 (extract + expand)."""
    if not salt:
        salt = b"\x00" * _HASH_LEN
    prk = hmac.new(salt, ikm, _HASH).digest()  # extract
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), _HASH).digest()  # expand
        okm += block
        counter += 1
    return okm[:length]


def derive_key(master_secret: str, info: bytes) -> bytes:
    """Derive a purpose-bound subkey from the master secret."""
    return _hkdf(master_secret.encode("utf-8"), info)


def refresh_token_key(master_secret: str) -> bytes:
    return derive_key(master_secret, _INFO_REFRESH_TOKEN)


def oauth_state_key(master_secret: str) -> bytes:
    return derive_key(master_secret, _INFO_OAUTH_STATE)


def api_key_secret_key(master_secret: str) -> bytes:
    return derive_key(master_secret, _INFO_API_KEY)


def jwt_signing_seed(master_secret: str) -> bytes:
    """32-byte Ed25519 private-key seed for access/service JWTs."""
    return derive_key(master_secret, _INFO_JWT_SIGNING)


def hmac_sha256_hex(key: bytes, message: str) -> str:
    return hmac.new(key, message.encode("utf-8"), _HASH).hexdigest()


def legacy_hmac_sha256_hex(master_secret: str, message: str) -> str:
    """HMAC keyed with the raw master secret; verify-only.

    Matches refresh-token / API-key hashes persisted with the raw secret; never
    used for new writes.
    """
    return hmac.new(master_secret.encode("utf-8"), message.encode("utf-8"), _HASH).hexdigest()


def oauth_pkce_key(master_secret: str) -> bytes:
    """Key a flow's PKCE ``code_verifier`` is derived from (HMAC of its state nonce), so it is never stored."""
    return derive_key(master_secret, b"anak-identity:oauth-pkce:v1")
