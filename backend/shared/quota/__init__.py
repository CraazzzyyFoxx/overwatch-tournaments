"""Per-principal quotas, shared by every service that can spend real resources.

Two scopes are enforced on every metered call: the **workspace**, a budget every
API key and every member's session in that tenant shares, and the **principal**
(one key, or one interactive user), so a single runaway client cannot eat the
tenant's whole allowance. The tighter of the two refuses, and the error names
which one did.

A call site passes facts it already holds and never a number::

    await quota.charge(user, "parser.logs.upload", workspace_id=ws, item_count=len(files))

    lease = await quota.lease(user, "balancer.job", workspace_id=ws, ttl_seconds=ttl)
    try:
        ...
    finally:
        await quota.release(lease)

Policy lives in the ``quota`` schema (plans per tier, per-operation cost,
per-workspace and per-key overrides) and consumption in Redis. ``configure`` is
called once per service at startup; ``QUOTA_ENABLED=false`` turns every verdict
into "allow" without touching a row.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from shared.quota.enforcer import (
    QUOTA_REJECTIONS_TOTAL,
    QUOTA_UNAVAILABLE_TOTAL,
    QuotaEnforcer,
    QuotaLease,
    principal_of,
)
from shared.quota.policy import PolicyStore, QuotaLimits, ResolvedQuota, Scope

__all__ = (
    "QUOTA_REJECTIONS_TOTAL",
    "QUOTA_UNAVAILABLE_TOTAL",
    "PolicyStore",
    "QuotaEnforcer",
    "QuotaLease",
    "QuotaLimits",
    "ResolvedQuota",
    "Scope",
    "charge",
    "check_payload",
    "close",
    "configure",
    "enforcer",
    "invalidate_policy",
    "lease",
    "principal_of",
    "release",
    "release_ids",
    "set_enforcer",
    "usage",
)

_enforcer: QuotaEnforcer | None = None


def configure(
    *,
    session_factory: Callable[[], Any],
    redis_url: str,
    enabled: bool = True,
) -> QuotaEnforcer:
    """Wire the process-global enforcer. Idempotent per process."""
    global _enforcer
    if _enforcer is None:
        _enforcer = QuotaEnforcer(
            policy=PolicyStore(session_factory),
            redis_url=redis_url,
            enabled=enabled,
        )
    return _enforcer


def set_enforcer(instance: QuotaEnforcer | None) -> None:
    """Install an enforcer directly. For tests and for a service that builds its own."""
    global _enforcer
    _enforcer = instance


def enforcer() -> QuotaEnforcer:
    if _enforcer is None:
        raise RuntimeError("shared.quota is not configured; call quota.configure() at startup")
    return _enforcer


def invalidate_policy() -> None:
    """Drop cached policy after a write, instead of waiting out the TTL."""
    if _enforcer is not None:
        _enforcer.policy.invalidate()


async def charge(
    user: Any,
    operation: str,
    *,
    workspace_id: int | None = None,
    size_bytes: int | None = None,
    item_count: int | None = None,
) -> None:
    await enforcer().charge(
        user,
        operation,
        workspace_id=workspace_id,
        size_bytes=size_bytes,
        item_count=item_count,
    )


async def check_payload(
    user: Any,
    operation: str,
    *,
    workspace_id: int | None = None,
    size_bytes: int | None = None,
    item_count: int | None = None,
) -> None:
    await enforcer().check_payload(
        user,
        operation,
        workspace_id=workspace_id,
        size_bytes=size_bytes,
        item_count=item_count,
    )


async def lease(
    user: Any,
    operation: str,
    *,
    ttl_seconds: int,
    workspace_id: int | None = None,
    lease_id: str | None = None,
    size_bytes: int | None = None,
    item_count: int | None = None,
) -> QuotaLease:
    return await enforcer().lease(
        user,
        operation,
        ttl_seconds=ttl_seconds,
        workspace_id=workspace_id,
        lease_id=lease_id,
        size_bytes=size_bytes,
        item_count=item_count,
    )


async def usage(
    *,
    principal_kind: str,
    principal_id: int,
    workspace_id: int | None = None,
) -> dict[str, Any]:
    return await enforcer().usage(
        principal_kind=principal_kind,
        principal_id=principal_id,
        workspace_id=workspace_id,
    )


async def release(held: QuotaLease | None) -> None:
    if _enforcer is not None:
        await _enforcer.release(held)


async def release_ids(
    *,
    lease_id: str,
    principal_kind: str,
    principal_id: int,
    workspace_id: int | None = None,
) -> None:
    if _enforcer is not None:
        await _enforcer.release_ids(
            lease_id=lease_id,
            principal_kind=principal_kind,
            principal_id=principal_id,
            workspace_id=workspace_id,
        )


async def close() -> None:
    global _enforcer
    if _enforcer is None:
        return
    await _enforcer.close()
    _enforcer = None
