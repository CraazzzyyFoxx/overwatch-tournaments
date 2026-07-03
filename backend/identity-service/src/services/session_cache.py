"""Redis-backed RBAC cache for instant role/permission propagation."""

import json

from loguru import logger
from redis.exceptions import RedisError

from src.core.redis import get_redis

RBAC_CACHE_VERSION = 2  # v2: deny entries carry workspace_id (Phase A, Task 8)
RBAC_KEY_PREFIX = f"rbac:v{RBAC_CACHE_VERSION}:user:"
RBAC_TTL_SECONDS = 60

# Idempotency cache for token refresh — prevents concurrent refresh
# requests from triggering false reuse-attack detection.
REFRESH_IDEM_PREFIX = "refresh:idem:"
REFRESH_IDEM_TTL_SECONDS = 30

# Blacklist of revoked session ids (``sid`` JWT claim). Access tokens are
# stateless and short-lived (~15 min), so revoking a session (logout / revoke /
# reuse-detection) must also block any still-valid access token carrying that
# sid until it naturally expires. Entries are set with a TTL equal to the access
# token lifetime so the key self-expires once no live token can reference it.
SESSION_BLACKLIST_PREFIX = "auth:sid:revoked:"


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
    denies: list[dict[str, object]] | None = None,
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
    if denies:
        data["denies"] = denies
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


def _sid_key(session_id: str) -> str:
    return f"{SESSION_BLACKLIST_PREFIX}{session_id}"


async def blacklist_session(session_id: str, ttl_seconds: int) -> None:
    """Mark a session id as revoked for ``ttl_seconds`` (= access-token TTL).

    Best-effort: if Redis is unavailable the blacklist degrades to fail-open
    (the access token stays valid until it expires on its own), matching the
    graceful-degradation contract of the rest of this cache. Refresh-token
    revocation in the DB is the durable source of truth regardless.
    """
    if not session_id or ttl_seconds <= 0:
        return
    try:
        redis = get_redis()
    except RuntimeError as exc:
        _log_redis_degraded("session blacklist write", exc)
        return
    try:
        await redis.set(_sid_key(session_id), "1", ex=ttl_seconds)
    except (RedisError, OSError, RuntimeError) as exc:
        _log_redis_degraded("session blacklist write", exc)


async def is_session_blacklisted(session_id: str | None) -> bool:
    """Return True only when the session id is known-revoked.

    Fails open (returns False) on a Redis outage: we cannot prove the session
    was revoked, and the DB refresh-token revocation still applies on the next
    refresh, so a stale access token lives at most one access-token TTL.
    """
    if not session_id:
        return False
    try:
        redis = get_redis()
    except RuntimeError as exc:
        _log_redis_degraded("session blacklist read", exc)
        return False
    try:
        return await redis.get(_sid_key(session_id)) is not None
    except (RedisError, OSError, RuntimeError) as exc:
        _log_redis_degraded("session blacklist read", exc)
        return False


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
