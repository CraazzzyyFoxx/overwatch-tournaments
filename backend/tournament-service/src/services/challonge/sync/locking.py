"""The per-tournament, per-direction Redis sync lock and its pooled client."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis import asyncio as redis_async

from shared.core.errors import BaseAPIException as HTTPException
from shared.services.distributed_lock import DistributedLockUnavailable, distributed_lock
from src.core import config

SYNC_LOCK_TTL_SECONDS = 5 * 60
#: How long an admin's import or export waits for a run already holding the lock before answering 409.
ADMIN_LOCK_WAIT_SECONDS = 3

_redis_client: redis_async.Redis | None = None


async def _get_redis() -> redis_async.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_async.from_url(str(config.settings.redis_url), decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is None:
        return
    await _redis_client.aclose()
    _redis_client = None


@asynccontextmanager
async def _sync_job_lock(tournament_id: int, direction: str, *, wait_seconds: float) -> AsyncIterator[str]:
    """The per-tournament, per-direction sync lock, renewed while held; contention is a 409."""
    redis = await _get_redis()
    key = f"challonge:sync:{tournament_id}:{direction}"
    try:
        async with distributed_lock(
            redis, key, ttl_seconds=SYNC_LOCK_TTL_SECONDS, acquire_timeout_seconds=wait_seconds
        ) as token:
            yield token.value
    except DistributedLockUnavailable as exc:
        raise HTTPException(
            status_code=409, detail=f"A Challonge {direction} of this tournament is already running"
        ) from exc
