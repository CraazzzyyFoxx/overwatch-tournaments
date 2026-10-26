"""Password hashing and token minting — pure crypto, no database, no Redis.

Kept free of I/O on purpose: every other service depends on this module, so it
must stay at the bottom of the dependency graph.
"""

from __future__ import annotations

import asyncio
import base64
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import bcrypt
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from loguru import logger

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src.core import config, key_derivation
from src.core.metrics import PASSWORD_HASH_SECONDS

__all__ = ["PasswordHasher", "TokenCodec", "passwords", "token_codec"]

settings = config.settings

ACCESS_TOKEN_ISSUER = "owt-identity"
ACCESS_TOKEN_AUDIENCE = "owt"
# Every EdDSA token carries these; ``iss``/``aud`` must then match its ``type``.
_REQUIRED_CLAIMS = ["exp", "iat", "sub", "iss", "aud"]


# bcrypt costs ~250 ms of CPU per call at cost 12. It runs in a thread so the event loop keeps serving other RPCs,
# and at most two at a time so a login burst cannot take every core the process shares with that loop.
_BCRYPT_SLOTS = asyncio.Semaphore(2)


async def _bcrypt[T](op: str, fn: Callable[..., T], *args: bytes) -> T:
    with PASSWORD_HASH_SECONDS.labels(op=op).time():
        async with _BCRYPT_SLOTS:
            return await asyncio.to_thread(fn, *args)


class PasswordHasher:
    """bcrypt password hashing, off the event loop."""

    @staticmethod
    async def hash(password: str) -> str:
        hashed = await _bcrypt("hash", bcrypt.hashpw, password.encode("utf-8"), bcrypt.gensalt())
        return hashed.decode("utf-8")

    @staticmethod
    async def verify(plain_password: str, hashed_password: str) -> bool:
        return await _bcrypt("verify", bcrypt.checkpw, plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


class TokenCodec:
    """JWT minting/decoding plus the domain-separated refresh-token hashes."""

    def __init__(
        self,
        config: Any = settings,
        *,
        clock: Callable[[], float] = time.monotonic,
        started_at: float | None = None,
    ) -> None:
        self._config = config
        # Domain-separated subkey for refresh-token HMAC (never the raw JWT
        # secret). Derived once: HKDF is pure but not free, and the master
        # secret cannot change without a restart.
        self._refresh_key = key_derivation.refresh_token_key(config.JWT_SECRET_KEY)
        # Ed25519: the gateway verifies with the public half only, so it cannot mint tokens.
        self._signing_key = Ed25519PrivateKey.from_private_bytes(key_derivation.jwt_signing_seed(config.JWT_SECRET_KEY))
        self._verify_key = self._signing_key.public_key()
        # Raw 32 bytes, base64url without padding: the gateway's JWT_PUBLIC_KEY.
        self.public_key_b64 = base64.urlsafe_b64encode(self._verify_key.public_bytes_raw()).rstrip(b"=").decode()
        self._issuer_audience = {
            "access": (ACCESS_TOKEN_ISSUER, ACCESS_TOKEN_AUDIENCE),
            "service": (config.SERVICE_TOKEN_ISSUER, config.SERVICE_TOKEN_AUDIENCE),
        }
        # ponytail: transitional HS256 window for tokens the previous release signed with the raw JWT_SECRET_KEY,
        # open for one access-token lifetime after start; remove it once the EdDSA release has been live a day.
        self._clock = clock
        self._legacy_until = (clock() if started_at is None else started_at) + self.access_token_ttl_seconds

    @property
    def access_token_ttl_seconds(self) -> int:
        """Seconds a freshly issued access token remains valid (blacklist TTL)."""
        return max(int(self._config.ACCESS_TOKEN_EXPIRE_MINUTES), 1) * 60

    def _encode(self, claims: dict, *, delta: timedelta, token_type: str) -> str:
        now = datetime.now(UTC)
        to_encode = {**claims, "type": token_type, "iat": now, "exp": now + delta, "jti": uuid4().hex}
        return jwt.encode(to_encode, self._signing_key, algorithm="EdDSA")

    def access_token(self, claims: dict, *, expires_delta: timedelta | None = None) -> str:
        """Mint a user access token: the account (``sub``) and its session (``sid``), nothing else.

        Profile and RBAC are resolved per request by ``validate_token``, so any other claim is dropped.
        """
        delta = expires_delta or timedelta(minutes=self._config.ACCESS_TOKEN_EXPIRE_MINUTES)
        identity = {
            "sub": str(claims["sub"]),
            "sid": str(claims["sid"]),
            "iss": ACCESS_TOKEN_ISSUER,
            "aud": ACCESS_TOKEN_AUDIENCE,
        }
        return self._encode(identity, delta=delta, token_type="access")

    def service_token(self, claims: dict, *, expires_delta: timedelta | None = None) -> str:
        """Mint a machine-to-machine service token."""
        delta = expires_delta or timedelta(minutes=self._config.SERVICE_ACCESS_TOKEN_EXPIRE_MINUTES)
        return self._encode(claims, delta=delta, token_type="service")

    def decode(self, token: str) -> dict:
        """Verify a JWT, or raise 401.

        EdDSA with ``iss``/``aud`` matching the token ``type``; legacy HS256 only inside the post-start window. Each
        branch pins one algorithm to one key type, so a token cannot pick how it is verified.
        """
        try:
            alg = jwt.get_unverified_header(token).get("alg")
            if alg == "EdDSA":
                payload = jwt.decode(
                    token,
                    self._verify_key,
                    algorithms=["EdDSA"],
                    options={"require": _REQUIRED_CLAIMS, "verify_aud": False},
                )
                if (payload["iss"], payload["aud"]) != self._issuer_audience.get(payload.get("type")):
                    raise jwt.InvalidTokenError("iss/aud do not match the token type")
                return payload
            if alg == "HS256" and self._clock() < self._legacy_until:
                return jwt.decode(
                    token,
                    self._config.JWT_SECRET_KEY,
                    algorithms=["HS256"],
                    options={"require": ["exp", "sub"], "verify_aud": False},
                )
            raise jwt.InvalidAlgorithmError(f"algorithm {alg!r} is not accepted")
        except jwt.PyJWTError as e:
            logger.debug("Token decode error: {}", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    @staticmethod
    def new_refresh_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def new_session() -> tuple[UUID, datetime]:
        """A logical-session identifier reused across refresh rotation."""
        return uuid4(), datetime.now(UTC)

    def hash_refresh_token(self, token: str) -> str:
        """Hash a refresh token for persistence/lookup.

        Uses an HKDF-derived subkey (domain-separated from the JWT signing
        secret). Lookups accept the legacy raw-secret hash too — see
        ``refresh_token_hashes`` — so tokens issued before domain separation
        keep working without a migration or forced re-login.
        """
        return key_derivation.hmac_sha256_hex(self._refresh_key, token)

    def refresh_token_hashes(self, token: str) -> list[str]:
        """New (derived) plus legacy (raw-secret) hash of a refresh token.

        New tokens are always written with the derived hash; this list lets a
        lookup still match tokens persisted under the pre-domain-separation
        HMAC. They migrate to the derived hash naturally on the next rotation.
        """
        new_hash = self.hash_refresh_token(token)
        legacy_hash = key_derivation.legacy_hmac_sha256_hex(self._config.JWT_SECRET_KEY, token)
        if new_hash == legacy_hash:
            return [new_hash]
        return [new_hash, legacy_hash]


passwords = PasswordHasher()
token_codec = TokenCodec()
