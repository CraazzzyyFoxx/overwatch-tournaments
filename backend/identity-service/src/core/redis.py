"""Redis client singleton for auth-service."""

import redis.asyncio as aioredis
from loguru import logger
from redis.exceptions import RedisError

from src.core.config import settings

_redis: aioredis.Redis | None = None


async def init_redis() -> None:
    global _redis
    # Redis sits on the gateway's per-request path: a stalled server must cost
    # 0.5 s and a fallback, never a hung request.
    _redis = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_timeout=0.5,
        socket_connect_timeout=0.5,
        health_check_interval=30,
        max_connections=128,
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
