from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis
from fastapi import HTTPException, status

from src.core.config import config

DEFAULT_LIMITS: dict[str, int] = {
    "requests_per_minute": 60,
    "jobs_per_day": 100,
    "concurrent_jobs": 2,
    "max_upload_bytes": 10 * 1024 * 1024,
    "max_players": 500,
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


class ApiKeyUsageLimiter:
    def __init__(self, redis_url: str | None = None) -> None:
        self._redis = redis.from_url(redis_url or config.redis_url, decode_responses=True)

    @staticmethod
    def _minute_key(api_key_id: int) -> str:
        return f"balancer:api_key:{api_key_id}:rpm"

    @staticmethod
    def _daily_key(api_key_id: int) -> str:
        day = datetime.now(UTC).strftime("%Y%m%d")
        return f"balancer:api_key:{api_key_id}:jobs:{day}"

    @staticmethod
    def active_jobs_key(api_key_id: int) -> str:
        return f"balancer:api_key:{api_key_id}:active_jobs"

    @staticmethod
    def _raise_limited(limit_name: str, retry_after: int) -> None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"API key limit exceeded: {limit_name}",
            headers={"Retry-After": str(max(1, retry_after))},
        )

    async def check_request(self, user: Any) -> None:
        if not is_api_key_principal(user):
            return
        api_key_id = get_api_key_id(user)
        if api_key_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key principal")
        limits = get_api_key_limits(user)
        result = await self._redis.eval(
            REQUEST_SCRIPT,
            1,
            self._minute_key(api_key_id),
            limits["requests_per_minute"],
            60,
        )
        if int(result[0]) != 1:
            self._raise_limited("requests_per_minute", int(result[1]))

    async def reserve_job(self, user: Any, job_id: str) -> None:
        if not is_api_key_principal(user):
            return
        api_key_id = get_api_key_id(user)
        if api_key_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key principal")
        limits = get_api_key_limits(user)
        result = await self._redis.eval(
            RESERVE_JOB_SCRIPT,
            2,
            self._daily_key(api_key_id),
            self.active_jobs_key(api_key_id),
            limits["jobs_per_day"],
            25 * 60 * 60,
            limits["concurrent_jobs"],
            job_id,
            config.balancer_job_ttl_seconds,
        )
        if int(result[0]) != 1:
            self._raise_limited(str(result[2]), int(result[1]))

    async def release_job(self, api_key_id: int, job_id: str) -> None:
        await self._redis.srem(self.active_jobs_key(api_key_id), job_id)

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
