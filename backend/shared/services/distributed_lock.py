from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any


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


@asynccontextmanager
async def distributed_lock(
    redis: Any,
    key: str,
    *,
    ttl_seconds: int,
    acquire_timeout_seconds: float = 30.0,
    retry_interval_seconds: float = 0.1,
) -> AsyncIterator[DistributedLockToken]:
    token = await acquire_distributed_lock(
        redis,
        key,
        ttl_seconds=ttl_seconds,
        acquire_timeout_seconds=acquire_timeout_seconds,
        retry_interval_seconds=retry_interval_seconds,
    )
    try:
        yield token
    finally:
        await release_distributed_lock(redis, token)
