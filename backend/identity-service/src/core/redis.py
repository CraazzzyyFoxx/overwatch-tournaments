"""Redis client singleton for auth-service."""

import redis.asyncio as aioredis
from loguru import logger
from redis.exceptions import RedisError

from src.core.config import settings

_redis: aioredis.Redis | None = None


async def init_redis() -> None:
    global _redis
    _redis = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )
    try:
        await _redis.ping()
    except RedisError as exc:
        logger.warning(f"Redis unavailable during startup, continuing with DB fallback: {exc}")
    else:
        logger.success("Redis connection established")


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed")


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis client is not initialised — call init_redis() first")
    return _redis
