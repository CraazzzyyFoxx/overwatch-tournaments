"""Per-account password-login lock: 10 failures for one email in 15 minutes lock it for 15 minutes.

Keyed on ``sha256(lower(email))`` so Redis never holds an address, and counted for unknown emails too: whether an
account exists must not change the answer. Fail-open: a Redis outage disables the lock (logged and counted), never
sign-in itself.
"""

from __future__ import annotations

import hashlib

from loguru import logger

from src.core.cache import _UNAVAILABLE
from src.core.metrics import REDIS_DEGRADED_TOTAL
from src.core.redis import get_redis

__all__ = ("LOCKED_DETAIL", "LoginThrottle", "login_throttle")

KEY_PREFIX = "auth:login:fail:"
MAX_FAILURES = 10
WINDOW_SECONDS = 15 * 60
LOCKED_DETAIL = "Too many failed login attempts. Try again later."
_STORE = "login throttle"


def _key(email: str) -> str:
    return KEY_PREFIX + hashlib.sha256(email.lower().encode("utf-8")).hexdigest()


def _degraded(action: str, exc: Exception) -> None:
    REDIS_DEGRADED_TOTAL.labels(store=_STORE, action=action).inc()
    logger.warning(f"Redis unavailable during {_STORE} {action}; login lock not enforced: {exc}")


class LoginThrottle:
    async def is_locked(self, email: str) -> bool:
        """Whether the email is locked; checked before the password is looked at."""
        try:
            failures = await get_redis().get(_key(email))
        except _UNAVAILABLE as exc:
            _degraded("read", exc)
            return False
        return failures is not None and int(failures) >= MAX_FAILURES

    async def record_failure(self, email: str) -> None:
        key = _key(email)
        try:
            # The window starts at the first failure (SET NX EX) and the count rides on it (INCR keeps the TTL), in
            # one transaction, so no crash can leave a counter without an expiry.
            async with get_redis().pipeline(transaction=True) as pipeline:
                pipeline.set(key, 0, ex=WINDOW_SECONDS, nx=True)
                pipeline.incr(key)
                _, failures = await pipeline.execute()
            if failures == MAX_FAILURES:
                # The failure that locks the account restarts the clock: the lock lasts the full window.
                await get_redis().expire(key, WINDOW_SECONDS)
        except _UNAVAILABLE as exc:
            _degraded("write", exc)

    async def clear(self, email: str) -> None:
        try:
            await get_redis().delete(_key(email))
        except _UNAVAILABLE as exc:
            _degraded("invalidation", exc)


login_throttle = LoginThrottle()
