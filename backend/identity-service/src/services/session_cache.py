"""Redis-backed RBAC cache for instant role/permission propagation."""

import json

from loguru import logger
from redis.exceptions import RedisError

from src.core.redis import get_redis

RBAC_KEY_PREFIX = "rbac:user:"
RBAC_TTL_SECONDS = 60

# Idempotency cache for token refresh — prevents concurrent refresh
# requests from triggering false reuse-attack detection.
REFRESH_IDEM_PREFIX = "refresh:idem:"
REFRESH_IDEM_TTL_SECONDS = 30


def _key(user_id: int) -> str:
    return f"{RBAC_KEY_PREFIX}{user_id}"


def _log_redis_degraded(action: str, exc: Exception) -> None:
    logger.warning(f"Redis unavailable during {action}; falling back gracefully: {exc}")


async def get_rbac(user_id: int) -> dict | None:
    """Return cached RBAC payload or None on miss."""
    try:
        redis = get_redis()
    except RuntimeError as exc:
        _log_redis_degraded("RBAC cache read", exc)
        return None

    try:
        raw = await redis.get(_key(user_id))
    except (RedisError, OSError, RuntimeError) as exc:
        _log_redis_degraded("RBAC cache read", exc)
        return None

    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"Corrupted RBAC cache for user {user_id}, evicting")
        try:
            await redis.delete(_key(user_id))
        except (RedisError, OSError, RuntimeError) as exc:
            _log_redis_degraded("RBAC cache eviction", exc)
        return None


async def set_rbac(
    user_id: int,
    roles: list[str],
    permissions: list[dict[str, str]],
    workspace_roles: dict | None = None,
) -> None:
    """Store RBAC data with TTL."""
    try:
        redis = get_redis()
    except RuntimeError as exc:
        _log_redis_degraded("RBAC cache write", exc)
        return

    data: dict = {"roles": roles, "permissions": permissions}
    if workspace_roles:
        data["workspace_roles"] = workspace_roles
    payload = json.dumps(data)
    try:
        await redis.set(_key(user_id), payload, ex=RBAC_TTL_SECONDS)
    except (RedisError, OSError, RuntimeError) as exc:
        _log_redis_degraded("RBAC cache write", exc)


async def invalidate_rbac(user_id: int) -> None:
    """Immediately remove cached RBAC for a user."""
    try:
        redis = get_redis()
    except RuntimeError as exc:
        _log_redis_degraded("RBAC cache invalidation", exc)
        return

    try:
        await redis.delete(_key(user_id))
    except (RedisError, OSError, RuntimeError) as exc:
        _log_redis_degraded("RBAC cache invalidation", exc)
        return

    logger.info(f"RBAC cache invalidated for user {user_id}")


def _refresh_idem_key(token_hash: str) -> str:
    return f"{REFRESH_IDEM_PREFIX}{token_hash}"


async def get_refresh_idem(token_hash: str) -> dict | None:
    """Return cached token pair for an already-rotated refresh token, or None on miss."""
    try:
        redis = get_redis()
    except RuntimeError as exc:
        _log_redis_degraded("refresh idem read", exc)
        return None

    try:
        raw = await redis.get(_refresh_idem_key(token_hash))
    except (RedisError, OSError, RuntimeError) as exc:
        _log_redis_degraded("refresh idem read", exc)
        return None

    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def set_refresh_idem(token_hash: str, access_token: str, refresh_token: str) -> None:
    """Cache the new token pair produced by a refresh rotation (TTL=30s).

    A subsequent concurrent request with the same old refresh token will hit
    this cache and get back the already-issued pair instead of triggering
    the reuse-attack detection path.
    """
    try:
        redis = get_redis()
    except RuntimeError as exc:
        _log_redis_degraded("refresh idem write", exc)
        return

    payload = json.dumps({"access_token": access_token, "refresh_token": refresh_token})
    try:
        await redis.set(_refresh_idem_key(token_hash), payload, ex=REFRESH_IDEM_TTL_SECONDS)
    except (RedisError, OSError, RuntimeError) as exc:
        _log_redis_degraded("refresh idem write", exc)
