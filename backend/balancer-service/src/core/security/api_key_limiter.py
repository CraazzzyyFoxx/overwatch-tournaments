from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src.core.config import config

DEFAULT_LIMITS: dict[str, int] = {
    "requests_per_minute": 60,
    "jobs_per_day": 100,
    "concurrent_jobs": 2,
    "max_upload_bytes": 10 * 1024 * 1024,
    "max_players": 500,
}

# Finite-but-generous ceilings for interactive session principals (workspace
# members with ``team.import``). Previously these users were completely
# unbounded — no payload/player/concurrency cap — which let a single member
# exhaust CPU with large rosters or many parallel jobs (review H5). API keys
# keep their own per-key limits; these apply to everyone else.
SESSION_LIMITS: dict[str, int] = {
    "requests_per_minute": 120,
    "jobs_per_day": 500,
    "concurrent_jobs": 3,
    "max_upload_bytes": 25 * 1024 * 1024,
    "max_players": 1000,
}

REQUEST_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[2])
end
if current > tonumber(ARGV[1]) then
  local ttl = redis.call("TTL", KEYS[1])
  if ttl < 1 then ttl = tonumber(ARGV[2]) end
  return {0, ttl}
end
return {1, 0}
"""

RESERVE_JOB_SCRIPT = """
local active_count = redis.call("SCARD", KEYS[2])
if active_count >= tonumber(ARGV[3]) then
  return {0, 30, "concurrent_jobs"}
end

local daily_count = redis.call("INCR", KEYS[1])
if daily_count == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[2])
end
if daily_count > tonumber(ARGV[1]) then
  local ttl = redis.call("TTL", KEYS[1])
  if ttl < 1 then ttl = tonumber(ARGV[2]) end
  return {0, ttl, "jobs_per_day"}
end

redis.call("SADD", KEYS[2], ARGV[4])
redis.call("EXPIRE", KEYS[2], ARGV[5])
return {1, 0, "ok"}
"""


def is_api_key_principal(user: Any) -> bool:
    return getattr(user, "_credential_type", "access_token") == "api_key"


def get_api_key_id(user: Any) -> int | None:
    raw_value = getattr(user, "_api_key_id", None)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def get_api_key_limits(user: Any) -> dict[str, int]:
    payload = getattr(user, "_api_key_limits", None)
    limits = dict(DEFAULT_LIMITS)
    if isinstance(payload, dict):
        for key, default_value in DEFAULT_LIMITS.items():
            value = payload.get(key)
            try:
                limits[key] = max(0, int(value))
            except (TypeError, ValueError):
                limits[key] = default_value
    return limits


def get_effective_limits(user: Any) -> dict[str, int]:
    """Limits to apply to ``user``: per-key for API keys, generous session
    ceilings for everyone else (review H5)."""
    if is_api_key_principal(user):
        return get_api_key_limits(user)
    return dict(SESSION_LIMITS)


def get_principal(user: Any) -> tuple[str, int] | None:
    """Return the ``(kind, id)`` bucket a request/job is throttled against.

    ``("api_key", id)`` preserves the existing per-key namespace; ``("user", id)``
    buckets interactive session principals by their user id. ``None`` means the
    principal carries no usable id (an API-key principal without one is rejected
    by the callers; a session principal without an id is simply not throttled).
    """
    if is_api_key_principal(user):
        api_key_id = get_api_key_id(user)
        return ("api_key", api_key_id) if api_key_id is not None else None
    user_id = getattr(user, "id", None)
    try:
        return ("user", int(user_id))
    except (TypeError, ValueError):
        return None


class ApiKeyUsageLimiter:
    def __init__(self, redis_url: str | None = None) -> None:
        self._redis = redis.from_url(redis_url or config.redis_url, decode_responses=True)

    @staticmethod
    def _minute_key(kind: str, principal_id: int) -> str:
        return f"balancer:{kind}:{principal_id}:rpm"

    @staticmethod
    def _daily_key(kind: str, principal_id: int) -> str:
        day = datetime.now(UTC).strftime("%Y%m%d")
        return f"balancer:{kind}:{principal_id}:jobs:{day}"

    @staticmethod
    def active_jobs_key(kind: str, principal_id: int) -> str:
        # For ``kind == "api_key"`` this matches the historical
        # ``balancer:api_key:{id}:active_jobs`` key (backward compatible with
        # ``BalancerJobStore``'s release path).
        return f"balancer:{kind}:{principal_id}:active_jobs"

    @staticmethod
    def _raise_limited(limit_name: str, retry_after: int) -> None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Balancer rate limit exceeded: {limit_name}",
            headers={"Retry-After": str(max(1, retry_after))},
        )

    async def check_request(self, user: Any) -> None:
        principal = get_principal(user)
        if principal is None:
            if is_api_key_principal(user):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key principal")
            return
        kind, principal_id = principal
        limits = get_effective_limits(user)
        result = await self._redis.eval(
            REQUEST_SCRIPT,
            1,
            self._minute_key(kind, principal_id),
            limits["requests_per_minute"],
            60,
        )
        if int(result[0]) != 1:
            self._raise_limited("requests_per_minute", int(result[1]))

    async def reserve_job(self, user: Any, job_id: str) -> None:
        principal = get_principal(user)
        if principal is None:
            if is_api_key_principal(user):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key principal")
            return
        kind, principal_id = principal
        limits = get_effective_limits(user)
        result = await self._redis.eval(
            RESERVE_JOB_SCRIPT,
            2,
            self._daily_key(kind, principal_id),
            self.active_jobs_key(kind, principal_id),
            limits["jobs_per_day"],
            25 * 60 * 60,
            limits["concurrent_jobs"],
            job_id,
            config.balancer_job_ttl_seconds,
        )
        if int(result[0]) != 1:
            self._raise_limited(str(result[2]), int(result[1]))

    async def release_job(self, kind: str, principal_id: int, job_id: str) -> None:
        await self._redis.srem(self.active_jobs_key(kind, principal_id), job_id)

    async def close(self) -> None:
        await self._redis.aclose()


_api_key_limiter: ApiKeyUsageLimiter | None = None


def get_api_key_limiter() -> ApiKeyUsageLimiter:
    global _api_key_limiter
    if _api_key_limiter is None:
        _api_key_limiter = ApiKeyUsageLimiter()
    return _api_key_limiter


async def close_api_key_limiter() -> None:
    global _api_key_limiter
    if _api_key_limiter is None:
        return
    await _api_key_limiter.close()
    _api_key_limiter = None
