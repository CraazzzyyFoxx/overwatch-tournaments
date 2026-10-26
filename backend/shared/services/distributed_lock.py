from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any

from loguru import logger


class DistributedLockUnavailable(RuntimeError):
    """Raised when a distributed lock cannot be acquired before timeout."""


@dataclass(frozen=True)
class DistributedLockToken:
    key: str
    value: str


_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

_RENEW_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("pexpire", KEYS[1], ARGV[2])
end
return 0
"""


async def acquire_distributed_lock(
    redis: Any,
    key: str,
    *,
    ttl_seconds: int,
    acquire_timeout_seconds: float = 30.0,
    retry_interval_seconds: float = 0.1,
    token: str | None = None,
) -> DistributedLockToken:
    lock_token = token or str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    deadline = loop.time() + acquire_timeout_seconds
    delay = retry_interval_seconds

    while True:
        if await redis.set(key, lock_token, nx=True, ex=ttl_seconds):
            return DistributedLockToken(key=key, value=lock_token)

        remaining = deadline - loop.time()
        if remaining <= 0:
            raise DistributedLockUnavailable(f"Timed out acquiring distributed lock {key!r}")

        await asyncio.sleep(min(delay, remaining))
        delay = min(delay * 2, 1.0)


async def release_distributed_lock(redis: Any, token: DistributedLockToken) -> bool:
    released = await redis.eval(_RELEASE_LOCK_SCRIPT, 1, token.key, token.value)
    return bool(released)


async def renew_distributed_lock(redis: Any, token: DistributedLockToken, *, ttl_seconds: int) -> bool:
    """Extend the lock TTL iff we still hold it (token matches). Returns False if lost."""
    renewed = await redis.eval(_RENEW_LOCK_SCRIPT, 1, token.key, token.value, str(int(ttl_seconds * 1000)))
    return bool(renewed)


async def _renew_while_held(redis: Any, token: DistributedLockToken, *, ttl_seconds: int) -> None:
    """Extend the lock every third of its TTL until cancelled, or until it was lost to an expiry.

    A failed renewal (Redis unreachable for a moment) is logged and retried on the next tick, a third of the TTL
    later -- still before the key expires, so one failure in a row is survived. Two in a row let it lapse; the next
    renewal then finds the key gone, logs the loss and stops. Ending at the first failure instead would let the lock
    lapse under a body that is still running.
    """
    while True:
        await asyncio.sleep(ttl_seconds / 3)
        try:
            renewed = await renew_distributed_lock(redis, token, ttl_seconds=ttl_seconds)
        except Exception as exc:  # noqa: BLE001 - any client error; the next tick retries
            logger.warning("Renewing distributed lock {} failed, retrying next tick: {!r}", token.key, exc)
            continue
        if not renewed:
            logger.warning("Distributed lock {} was lost (expired or taken) while held", token.key)
            return


@asynccontextmanager
async def distributed_lock(
    redis: Any,
    key: str,
    *,
    ttl_seconds: int,
    acquire_timeout_seconds: float = 30.0,
    retry_interval_seconds: float = 0.1,
) -> AsyncIterator[DistributedLockToken]:
    """Hold ``key`` for the body, renewed in the background so a body longer than ``ttl_seconds`` keeps it.

    The TTL only bounds how long a crashed holder blocks the next one.
    """
    token = await acquire_distributed_lock(
        redis,
        key,
        ttl_seconds=ttl_seconds,
        acquire_timeout_seconds=acquire_timeout_seconds,
        retry_interval_seconds=retry_interval_seconds,
    )
    renewer = asyncio.create_task(_renew_while_held(redis, token, ttl_seconds=ttl_seconds))
    try:
        yield token
    finally:
        renewer.cancel()
        try:
            # Awaited so a renewer that died of anything unexpected surfaces here instead of as an unretrieved task
            # exception at garbage collection.
            with suppress(asyncio.CancelledError):
                await renewer
        finally:
            await release_distributed_lock(redis, token)
