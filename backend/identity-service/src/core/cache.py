"""Namespaced Redis access with an explicit degradation contract.

Every Redis-backed store in this service (RBAC cache, revoked-session list,
refresh idempotency, cross-domain tickets, OAuth state nonces) goes through here,
under one of two postures:

* **fail-soft** (``get_json``/``put_json``/``drop``/``take_json``) — Redis is an
  optimization; an outage costs a DB round trip or a shorter-lived guarantee,
  never a failed request.
* **strict** (``put_json_strict``/``claim``) — the value has no fallback. A
  cross-domain SSO/link ticket that was never stored can never be redeemed, and
  a single-use nonce whose use was never recorded can be replayed, so an
  explicit error beats a silent failure or a silent bypass.

``get_redis`` is imported at module scope on purpose: tests swap it out to point
a whole store at a fake client.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from redis.exceptions import RedisError

from src.core.metrics import REDIS_DEGRADED_TOTAL
from src.core.redis import get_redis

# ``RuntimeError`` covers "Redis was never initialised" (see ``get_redis``), which
# is indistinguishable from an outage as far as every caller here is concerned.
_UNAVAILABLE = (RedisError, OSError, RuntimeError)


class RedisStore:
    """One key namespace with a default TTL."""

    __slots__ = ("prefix", "ttl", "purpose")

    def __init__(self, prefix: str, *, ttl: int, purpose: str) -> None:
        self.prefix = prefix
        self.ttl = ttl
        self.purpose = purpose

    def key(self, suffix: str | int) -> str:
        return f"{self.prefix}{suffix}"

    def _degraded(self, action: str, exc: Exception) -> None:
        REDIS_DEGRADED_TOTAL.labels(store=self.purpose, action=action).inc()
        logger.warning(f"Redis unavailable during {self.purpose} {action}; falling back gracefully: {exc}")

    async def get_json(self, suffix: str | int) -> Any | None:
        """Decoded payload, or None on a miss, an outage, or a corrupt entry."""
        try:
            raw = await get_redis().get(self.key(suffix))
        except _UNAVAILABLE as exc:
            self._degraded("read", exc)
            return None
        return await self.decode(suffix, raw)

    async def decode(self, suffix: str | int, raw: str | None) -> Any | None:
        """``raw`` as read for ``suffix`` (by ``get_json`` or a caller's own MGET), decoded.

        A corrupt entry is evicted: it can only ever fail to decode again, and
        leaving it in place would pin the caller to the slow path until its TTL.
        """
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Corrupted {self.purpose} entry at {self.key(suffix)}, evicting")
            await self.drop(suffix)
            return None

    async def put_json(self, suffix: str | int, value: Any, *, ttl: int | None = None) -> None:
        try:
            await get_redis().set(self.key(suffix), json.dumps(value), ex=ttl or self.ttl)
        except _UNAVAILABLE as exc:
            self._degraded("write", exc)

    async def put_json_strict(self, suffix: str | int, value: Any, *, ttl: int | None = None) -> None:
        """Store or raise — for values with no usable fallback."""
        try:
            await get_redis().set(self.key(suffix), json.dumps(value), ex=ttl or self.ttl)
        except _UNAVAILABLE as exc:
            logger.error(f"Failed to store {self.purpose} entry: {exc}")
            raise

    async def take_json(self, suffix: str | int) -> Any | None:
        """Atomic read-and-delete (``GETDEL``): single-use by construction.

        Fails closed — an unknown key, an already-taken key, an expired key and
        an unreachable Redis are all indistinguishable from here, so a caller
        cannot leak which one it hit.
        """
        if not suffix:
            return None
        try:
            raw = await get_redis().getdel(self.key(suffix))
        except _UNAVAILABLE as exc:
            self._degraded("redeem", exc)
            return None

        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Corrupted {self.purpose} payload, discarding")
            return None

    async def mark(self, suffix: str | int, *, ttl: int | None = None) -> None:
        """Set a bare presence flag (no payload)."""
        try:
            await get_redis().set(self.key(suffix), "1", ex=ttl or self.ttl)
        except _UNAVAILABLE as exc:
            self._degraded("write", exc)

    async def claim(self, suffix: str | int, *, ttl: int | None = None) -> bool:
        """Set-if-absent. True when this caller won the claim.

        Fails CLOSED (raises on an outage): a single-use value whose first use
        cannot be recorded cannot be proven unused, so the caller must refuse it.
        """
        try:
            claimed = await get_redis().set(self.key(suffix), "1", nx=True, ex=ttl or self.ttl)
        except _UNAVAILABLE as exc:
            logger.error(f"Redis unavailable during {self.purpose} claim; refusing: {exc}")
            raise
        return bool(claimed)

    async def has(self, suffix: str | int) -> bool:
        """Whether the key is set; fails open (False) when Redis is unavailable."""
        if not suffix:
            return False
        try:
            return await get_redis().get(self.key(suffix)) is not None
        except _UNAVAILABLE as exc:
            self._degraded("read", exc)
            return False

    async def drop(self, suffix: str | int) -> None:
        try:
            await get_redis().delete(self.key(suffix))
        except _UNAVAILABLE as exc:
            self._degraded("invalidation", exc)
