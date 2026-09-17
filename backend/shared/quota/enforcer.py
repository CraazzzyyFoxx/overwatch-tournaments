"""Consumption accounting for the resolved quota policy.

One Lua script per call evaluates every applicable bucket and is
**all-or-nothing**: if any bucket would exceed its limit nothing is
incremented. Charging the workspace and then failing on the key would burn
tenant budget on every rejection -- a client in a retry loop would drain a
shared pool it never actually used.

Lease sets are sorted sets keyed by expiry, not plain sets with one TTL on the
whole key: a worker killed mid-job never releases its slot, and a per-member
score lets the next reservation prune it instead of the slot being held until
the set as a whole falls out of Redis.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis
from loguru import logger
from prometheus_client import Counter
from redis.exceptions import RedisError

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.quota.policy import PolicyStore, QuotaLimits, ResolvedQuota, Scope
from shared.rpc.identity import credential_type

__all__ = (
    "QUOTA_REJECTIONS_TOTAL",
    "QUOTA_UNAVAILABLE_TOTAL",
    "QuotaEnforcer",
    "QuotaLease",
    "principal_of",
)

QUOTA_REJECTIONS_TOTAL = Counter(
    "quota_rejections_total",
    "Metered calls refused by the shared quota gate.",
    ("operation", "limit_name", "scope"),
)
QUOTA_UNAVAILABLE_TOTAL = Counter(
    "quota_unavailable_total",
    "Metered calls that could not be accounted because Redis was unreachable.",
    ("operation", "outcome"),
)

RPM_WINDOW_SECONDS = 60
#: 25h, so the boundary between two UTC days is covered with slack.
DAY_TTL_SECONDS = 25 * 60 * 60
#: A concurrency refusal has no window to expire; tell the client to come back
#: in half a minute, as the balancer's own limiter has always done.
CONCURRENCY_RETRY_AFTER_SECONDS = 30
_UNLIMITED = -1

# KEYS 1-3: workspace rpm / day / lease set. KEYS 4-6: the same for the
# principal. An empty key name means "this scope bounds nothing", and the
# script then neither reads nor writes it -- an unconfigured workspace budget
# must not spawn a counter per tenant per minute.
CHARGE_SCRIPT = """
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local want_slot = tonumber(ARGV[3]) == 1
local lease_id = ARGV[4]
local lease_ttl = tonumber(ARGV[5])
local rpm_window = tonumber(ARGV[6])
local day_ttl = tonumber(ARGV[7])

local function lim(index)
  local value = tonumber(ARGV[index])
  if value < 0 then return nil end
  return value
end

local scopes = {
  {KEYS[1], KEYS[2], KEYS[3], lim(8),  lim(9),  lim(10), ARGV[14]},
  {KEYS[4], KEYS[5], KEYS[6], lim(11), lim(12), lim(13), ARGV[15]},
}

if want_slot then
  for _, scope in ipairs(scopes) do
    if scope[3] ~= "" then
      redis.call("ZREMRANGEBYSCORE", scope[3], "-inf", now)
    end
  end
end

for _, scope in ipairs(scopes) do
  local rpm_key, day_key, slot_key = scope[1], scope[2], scope[3]
  local rpm_limit, day_limit, slot_limit, name = scope[4], scope[5], scope[6], scope[7]
  if rpm_key ~= "" and rpm_limit and tonumber(redis.call("GET", rpm_key) or "0") + 1 > rpm_limit then
    local ttl = redis.call("TTL", rpm_key)
    if ttl < 1 then ttl = rpm_window end
    return {0, "requests_per_minute", name, ttl, rpm_limit}
  end
  if day_key ~= "" and day_limit and cost > 0 and tonumber(redis.call("GET", day_key) or "0") + cost > day_limit then
    local ttl = redis.call("TTL", day_key)
    if ttl < 1 then ttl = day_ttl end
    return {0, "heavy_per_day", name, ttl, day_limit}
  end
  if want_slot and slot_key ~= "" and slot_limit and redis.call("ZCARD", slot_key) >= slot_limit then
    return {0, "concurrent_heavy", name, ARGV[16], slot_limit}
  end
end

for _, scope in ipairs(scopes) do
  if scope[1] ~= "" then
    if redis.call("INCR", scope[1]) == 1 then
      redis.call("EXPIRE", scope[1], rpm_window)
    end
  end
  if scope[2] ~= "" and cost > 0 then
    if redis.call("INCRBY", scope[2], cost) == cost then
      redis.call("EXPIRE", scope[2], day_ttl)
    end
  end
  if want_slot and scope[3] ~= "" then
    redis.call("ZADD", scope[3], now + lease_ttl, lease_id)
    redis.call("EXPIRE", scope[3], lease_ttl + 60)
  end
end

return {1, "", "", 0, 0}
"""


@dataclass(frozen=True, slots=True)
class QuotaLease:
    """A held concurrency slot. Pass it back to ``release`` when the work ends."""

    lease_id: str
    principal_kind: str
    principal_id: int
    workspace_id: int | None


def principal_of(user: Any) -> tuple[str, int] | None:
    """The ``(kind, id)`` bucket a call is accounted against.

    ``None`` means "not throttleable": a session principal with no id (a
    hand-built user in a test, an internal caller) is let through rather than
    being metered against a bucket that does not exist. An API-key principal
    without an id is a broken credential, not an unmetered one.
    """
    if credential_type(user) == "api_key":
        try:
            return ("api_key", int(getattr(user, "_api_key_id", None)))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key principal",
            ) from None
    try:
        return ("user", int(getattr(user, "id", None)))
    except (TypeError, ValueError):
        return None


def _scope_of(principal_kind: str) -> Scope:
    return "key" if principal_kind == "api_key" else "session"


def _namespace(principal_kind: str) -> str:
    return "key" if principal_kind == "api_key" else "user"


def _api_key_workspace(user: Any) -> int | None:
    try:
        return int(getattr(user, "_api_key_workspace_id", None))
    except (TypeError, ValueError):
        return None


def _limit_arg(value: int | None) -> int:
    return _UNLIMITED if value is None else value


class QuotaEnforcer:
    def __init__(
        self,
        *,
        policy: PolicyStore,
        redis_url: str | None = None,
        redis_client: Any = None,
        enabled: bool = True,
    ) -> None:
        if redis_client is None and redis_url is None:
            raise ValueError("QuotaEnforcer needs redis_url or redis_client")
        self._policy = policy
        self._redis = redis_client or redis.from_url(redis_url, decode_responses=True)
        self._enabled = enabled
        # Registered so the script runs as EVALSHA (with an automatic EVAL
        # fallback on NOSCRIPT) instead of re-sending the source every call.
        self._charge_script = self._redis.register_script(CHARGE_SCRIPT)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def policy(self) -> PolicyStore:
        return self._policy

    async def charge(
        self,
        user: Any,
        operation: str,
        *,
        workspace_id: int | None = None,
        size_bytes: int | None = None,
        item_count: int | None = None,
    ) -> None:
        """Account one metered call. Raises on refusal, returns on pass."""
        await self._spend(
            user,
            operation,
            workspace_id=workspace_id,
            size_bytes=size_bytes,
            item_count=item_count,
            lease_id=None,
            lease_ttl_seconds=None,
        )

    async def check_payload(
        self,
        user: Any,
        operation: str,
        *,
        workspace_id: int | None = None,
        size_bytes: int | None = None,
        item_count: int | None = None,
    ) -> None:
        """Settle the per-request caps alone, without spending any budget.

        For the caller that knows a payload's size before it knows anything
        else: an upload over the cap is refused before it is parsed, and it
        does not burn the request token it never got to use.
        """
        if not self._enabled or (size_bytes is None and item_count is None):
            return
        principal = principal_of(user)
        if principal is None:
            return
        principal_kind, principal_id = principal
        resolved = await self._policy.resolve(
            operation=operation,
            principal_scope=_scope_of(principal_kind),
            api_key_id=principal_id if principal_kind == "api_key" else None,
            workspace_id=workspace_id,
        )
        self._enforce_caps(operation, resolved, size_bytes=size_bytes, item_count=item_count)

    async def lease(
        self,
        user: Any,
        operation: str,
        *,
        ttl_seconds: int,
        workspace_id: int | None = None,
        lease_id: str | None = None,
        size_bytes: int | None = None,
        item_count: int | None = None,
    ) -> QuotaLease:
        """Account one metered call and hold a concurrency slot for its work.

        ``lease_id`` defaults to a fresh token; callers that persist the lease
        (a queued job releasing it from another process) pass their own id.
        """
        return await self._spend(
            user,
            operation,
            workspace_id=workspace_id,
            size_bytes=size_bytes,
            item_count=item_count,
            lease_id=lease_id or uuid.uuid4().hex,
            lease_ttl_seconds=ttl_seconds,
        )

    async def release(self, lease: QuotaLease | None) -> None:
        if lease is None:
            return
        await self.release_ids(
            lease_id=lease.lease_id,
            principal_kind=lease.principal_kind,
            principal_id=lease.principal_id,
            workspace_id=lease.workspace_id,
        )

    async def release_ids(
        self,
        *,
        lease_id: str,
        principal_kind: str,
        principal_id: int,
        workspace_id: int | None = None,
    ) -> None:
        """Release a slot from persisted identifiers rather than a live lease.

        A queued job is released by whichever worker finishes it, from the
        metadata it was created with, so the lease object itself never has to
        survive a process boundary.
        """
        keys = [self._slot_key(_namespace(principal_kind), principal_id)]
        if workspace_id is not None:
            keys.append(self._slot_key("ws", workspace_id))
        try:
            for key in keys:
                await self._redis.zrem(key, lease_id)
        except RedisError as exc:
            # The slot is not lost: its score expires it and the next
            # reservation prunes it.
            logger.warning(f"quota: failed to release lease {lease_id}: {exc}")

    async def usage(
        self,
        *,
        principal_kind: str,
        principal_id: int,
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Every applicable bucket's ceiling next to what has been spent.

        Answers for an arbitrary principal, not for the caller, because the one
        consumer is an admin looking at somebody else's key. Reads only; an
        unconfigured dimension comes back as ``None`` (unlimited) with its
        counter still reported, so "no limit yet" and "limit not reached" stay
        distinguishable.
        """
        resolved = await self._policy.resolve(
            operation="",
            principal_scope=_scope_of(principal_kind),
            api_key_id=principal_id if principal_kind == "api_key" else None,
            workspace_id=workspace_id,
        )
        scopes = [(resolved.principal_scope, _namespace(principal_kind), principal_id, resolved.principal)]
        if workspace_id is not None:
            scopes.insert(0, ("workspace", "ws", workspace_id, resolved.workspace))

        report: list[dict[str, Any]] = []
        for scope, namespace, bucket_id, limits in scopes:
            rpm_key = self._rpm_key(namespace, bucket_id)
            day_key = self._day_key(namespace, bucket_id)
            slot_key = self._slot_key(namespace, bucket_id)
            try:
                requests_used = int(await self._redis.get(rpm_key) or 0)
                requests_reset_in = int(await self._redis.ttl(rpm_key))
                heavy_used = int(await self._redis.get(day_key) or 0)
                heavy_reset_in = int(await self._redis.ttl(day_key))
                concurrent_used = int(await self._redis.zcard(slot_key))
            except RedisError as exc:
                QUOTA_UNAVAILABLE_TOTAL.labels(operation="usage", outcome="allowed").inc()
                logger.warning(f"quota: usage read unavailable: {exc}")
                requests_used = heavy_used = concurrent_used = 0
                requests_reset_in = heavy_reset_in = -1
            report.append(
                {
                    "scope": scope,
                    "requests_per_minute": limits.requests_per_minute,
                    "requests_used": requests_used,
                    "requests_reset_in": max(0, requests_reset_in) if requests_reset_in >= 0 else None,
                    "heavy_per_day": limits.heavy_per_day,
                    "heavy_used": heavy_used,
                    "heavy_reset_in": max(0, heavy_reset_in) if heavy_reset_in >= 0 else None,
                    "concurrent_heavy": limits.concurrent_heavy,
                    "concurrent_used": concurrent_used,
                    "max_upload_bytes": limits.max_upload_bytes,
                    "max_items_per_request": limits.max_items_per_request,
                }
            )
        return {"workspace_id": workspace_id, "scopes": report}

    async def close(self) -> None:
        await self._redis.aclose()

    @staticmethod
    def _rpm_key(namespace: str, principal_id: int) -> str:
        return f"q:{namespace}:{principal_id}:rpm"

    @staticmethod
    def _day_key(namespace: str, principal_id: int) -> str:
        day = datetime.now(UTC).strftime("%Y%m%d")
        return f"q:{namespace}:{principal_id}:heavy:{day}"

    @staticmethod
    def _slot_key(namespace: str, principal_id: int) -> str:
        return f"q:{namespace}:{principal_id}:heavy:active"

    def _keys_for(self, namespace: str, principal_id: int | None, limits: QuotaLimits) -> list[str]:
        if principal_id is None or not limits.counts_anything:
            return ["", "", ""]
        return [
            self._rpm_key(namespace, principal_id),
            self._day_key(namespace, principal_id),
            self._slot_key(namespace, principal_id),
        ]

    async def _spend(
        self,
        user: Any,
        operation: str,
        *,
        workspace_id: int | None,
        size_bytes: int | None,
        item_count: int | None,
        lease_id: str | None,
        lease_ttl_seconds: int | None,
    ) -> Any:
        if not self._enabled:
            return self._lease_or_none(lease_id, ("user", 0), workspace_id)

        principal = principal_of(user)
        if principal is None:
            return self._lease_or_none(lease_id, principal, workspace_id)
        principal_kind, principal_id = principal
        # An API key belongs to exactly one workspace, so its tenant is a
        # property of the credential and not of the request: a call site that
        # does not name a workspace must not thereby escape the tenant budget.
        workspace_id = workspace_id if workspace_id is not None else _api_key_workspace(user)

        resolved = await self._policy.resolve(
            operation=operation,
            principal_scope=_scope_of(principal_kind),
            api_key_id=principal_id if principal_kind == "api_key" else None,
            workspace_id=workspace_id,
        )

        # Payload caps need no state, so they are settled before Redis is
        # touched: a request that is too large by itself never consumes budget.
        self._enforce_caps(operation, resolved, size_bytes=size_bytes, item_count=item_count)

        workspace_keys = self._keys_for("ws", workspace_id, resolved.workspace)
        principal_keys = self._keys_for(_namespace(principal_kind), principal_id, resolved.principal)
        if not any(workspace_keys + principal_keys):
            return self._lease_or_none(lease_id, principal, workspace_id)

        try:
            verdict = await self._charge_script(
                keys=[*workspace_keys, *principal_keys],
                args=[
                    int(time.time()),
                    resolved.cost,
                    1 if lease_id is not None else 0,
                    lease_id or "",
                    lease_ttl_seconds or 0,
                    RPM_WINDOW_SECONDS,
                    DAY_TTL_SECONDS,
                    _limit_arg(resolved.workspace.requests_per_minute),
                    _limit_arg(resolved.workspace.heavy_per_day),
                    _limit_arg(resolved.workspace.concurrent_heavy),
                    _limit_arg(resolved.principal.requests_per_minute),
                    _limit_arg(resolved.principal.heavy_per_day),
                    _limit_arg(resolved.principal.concurrent_heavy),
                    "workspace",
                    resolved.principal_scope,
                    CONCURRENCY_RETRY_AFTER_SECONDS,
                ],
            )
        except RedisError as exc:
            return self._on_redis_error(operation, exc, lease_id, principal, workspace_id)

        if int(verdict[0]) != 1:
            limit_name, scope, retry_after, limit = str(verdict[1]), str(verdict[2]), int(verdict[3]), int(verdict[4])
            QUOTA_REJECTIONS_TOTAL.labels(operation=operation, limit_name=limit_name, scope=scope).inc()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "quota_exceeded",
                    "limit_name": limit_name,
                    "scope": scope,
                    "limit": limit,
                },
                headers={"Retry-After": str(max(1, retry_after))},
            )
        return self._lease_or_none(lease_id, principal, workspace_id)

    @staticmethod
    def _lease_or_none(
        lease_id: str | None,
        principal: tuple[str, int] | None,
        workspace_id: int | None,
    ) -> QuotaLease | None:
        if lease_id is None:
            return None
        kind, principal_id = principal or ("user", 0)
        return QuotaLease(
            lease_id=lease_id,
            principal_kind=kind,
            principal_id=principal_id,
            workspace_id=workspace_id,
        )

    def _on_redis_error(
        self,
        operation: str,
        exc: RedisError,
        lease_id: str | None,
        principal: tuple[str, int] | None,
        workspace_id: int | None,
    ) -> Any:
        """Counters fail open, slots fail closed.

        A lost increment is one over-served request while nginx still caps the
        flood; a lost slot is unbounded CPU or third-party spend, so a
        reservation that cannot be recorded must not be granted.
        """
        if lease_id is None:
            QUOTA_UNAVAILABLE_TOTAL.labels(operation=operation, outcome="allowed").inc()
            logger.warning(f"quota: allowing {operation} unaccounted, Redis unavailable: {exc}")
            return None
        QUOTA_UNAVAILABLE_TOTAL.labels(operation=operation, outcome="refused").inc()
        logger.warning(f"quota: refusing {operation}, Redis unavailable: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "quota_unavailable", "operation": operation},
            headers={"Retry-After": str(CONCURRENCY_RETRY_AFTER_SECONDS)},
        ) from exc

    @staticmethod
    def _enforce_caps(
        operation: str,
        resolved: ResolvedQuota,
        *,
        size_bytes: int | None,
        item_count: int | None,
    ) -> None:
        for value, dimension, code, http_status in (
            (
                size_bytes,
                "max_upload_bytes",
                "quota_payload_too_large",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            ),
            (
                item_count,
                "max_items_per_request",
                "quota_items_too_many",
                status.HTTP_400_BAD_REQUEST,
            ),
        ):
            if value is None:
                continue
            for scope, limits in (("workspace", resolved.workspace), (resolved.principal_scope, resolved.principal)):
                cap = getattr(limits, dimension)
                if cap is None:
                    continue
                try:
                    measured = int(value)
                except (TypeError, ValueError):
                    break
                if measured > cap:
                    QUOTA_REJECTIONS_TOTAL.labels(operation=operation, limit_name=dimension, scope=scope).inc()
                    raise HTTPException(
                        status_code=http_status,
                        detail={
                            "code": code,
                            "limit_name": dimension,
                            "scope": scope,
                            "limit": cap,
                        },
                    )
