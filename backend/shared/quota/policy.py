"""Effective quota limits, resolved from the ``quota`` schema.

Nothing here talks to Redis: this module answers "what may this principal do",
:mod:`shared.quota.enforcer` answers "has it already". The split matters because
policy is small, cacheable and read from Postgres, while consumption is hot,
ephemeral and read from Redis.

``None`` is the load-bearing value in both tables: in an override row it means
"inherit from the level above", in a plan row it means "unlimited". That is why
every dimension is ``int | None`` rather than an ``int`` with a sentinel.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select

from shared.models import (
    QuotaApiKeyLimit,
    QuotaOperation,
    QuotaPlan,
    QuotaPlanLimit,
    QuotaWorkspaceLimit,
    Workspace,
)

__all__ = (
    "PolicyStore",
    "QuotaLimits",
    "ResolvedQuota",
    "Scope",
)

Scope = Literal["workspace", "key", "session"]

#: Counter ceilings: the nearest level that sets one wins, so a superuser
#: override can raise a limit as well as lower it.
_COUNTERS = ("requests_per_minute", "heavy_per_day", "concurrent_heavy")
#: Per-request caps: the narrowest value set at any level wins, so a workspace
#: can tighten what its own keys may send without a superuser.
_CAPS = ("max_upload_bytes", "max_items_per_request")

DEFAULT_CACHE_TTL_SECONDS = 60.0

#: Plan for a principal acting outside any tenant -- a session user polling a
#: job by id, an internal caller with no workspace in the request. Without it a
#: call whose workspace cannot be named would resolve no plan at all, which
#: reads as "unlimited": the hole a smoke test found before this constant
#: existed. No workspace ever maps to this slug; the three tier plans do.
DEFAULT_PLAN_SLUG = "default"


@dataclass(frozen=True, slots=True)
class QuotaLimits:
    """One resolved or stored limit set. ``None`` = unset at this level."""

    requests_per_minute: int | None = None
    heavy_per_day: int | None = None
    concurrent_heavy: int | None = None
    max_upload_bytes: int | None = None
    max_items_per_request: int | None = None

    @property
    def counts_anything(self) -> bool:
        """Whether this scope has any counter at all.

        A scope that bounds nothing gets no Redis keys: an unconfigured
        workspace budget must not spawn a counter per tenant per minute just to
        compare it against ``None``.
        """
        return any(getattr(self, name) is not None for name in _COUNTERS)

    @classmethod
    def of(cls, row: Any) -> QuotaLimits:
        return cls(**{name: getattr(row, name) for name in (*_COUNTERS, *_CAPS)})


EMPTY = QuotaLimits()


@dataclass(frozen=True, slots=True)
class ResolvedQuota:
    """What one metered call is allowed to consume, per scope, plus its price."""

    workspace: QuotaLimits
    principal: QuotaLimits
    principal_scope: Scope
    cost: int


def _combine(nearest: QuotaLimits, wider: QuotaLimits) -> QuotaLimits:
    values: dict[str, int | None] = {}
    for name in _COUNTERS:
        near = getattr(nearest, name)
        values[name] = near if near is not None else getattr(wider, name)
    for name in _CAPS:
        candidates = [value for value in (getattr(nearest, name), getattr(wider, name)) if value is not None]
        values[name] = min(candidates) if candidates else None
    return QuotaLimits(**values)


def _merge(levels: Iterable[QuotaLimits]) -> QuotaLimits:
    """Fold override levels from nearest to widest."""
    merged = EMPTY
    for level in levels:
        merged = _combine(merged, level)
    return merged


@dataclass(slots=True)
class _Entry:
    value: Any
    expires_at: float


@dataclass(frozen=True, slots=True)
class _Global:
    #: plan slug -> scope -> limits
    plans: dict[str, dict[str, QuotaLimits]]
    #: plan id -> plan slug, for workspaces pinned to a plan explicitly
    plan_slugs: dict[int, str]
    #: operation slug -> heavy cost, enabled rows only
    costs: dict[str, int]


@dataclass(frozen=True, slots=True)
class _WorkspacePolicy:
    plan_slug: str | None
    #: scope -> override limits for this workspace
    overrides: dict[str, QuotaLimits]


class PolicyStore:
    """Reads and caches the ``quota`` policy tables.

    Opens its own short-lived session instead of borrowing the caller's: a
    policy ``SELECT`` inside a handler's failed transaction would raise, and the
    one caller with no session at all (``balance_inline``, which deliberately
    touches no Postgres) would otherwise have no way to be metered.

    Every cache is a flat TTL map. The tables are tiny -- a few plans, a few
    dozen operations, one row per configured tenant -- so a miss costs one
    small query and a hit costs a dict lookup.
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_factory = session_factory
        self._ttl = ttl_seconds
        self._clock = clock
        self._global: _Entry | None = None
        self._workspaces: dict[int, _Entry] = {}
        self._keys: dict[int, _Entry] = {}

    def invalidate(self) -> None:
        """Drop everything cached. Called after a policy write."""
        self._global = None
        self._workspaces.clear()
        self._keys.clear()

    def _fresh(self, entry: _Entry | None) -> Any | None:
        if entry is None or entry.expires_at <= self._clock():
            return None
        return entry.value

    def _store(self, value: Any) -> _Entry:
        return _Entry(value=value, expires_at=self._clock() + self._ttl)

    async def resolve(
        self,
        *,
        operation: str,
        principal_scope: Scope,
        api_key_id: int | None,
        workspace_id: int | None,
    ) -> ResolvedQuota:
        policy = await self._load_global()
        workspace = await self._load_workspace(workspace_id) if workspace_id is not None else None
        key_override = await self._load_key(api_key_id) if api_key_id is not None else EMPTY

        # A plan is a property of the tenant when there is one, and of the
        # platform when there is not.
        plan_slug = workspace.plan_slug if workspace is not None else None
        plan = policy.plans.get(plan_slug or DEFAULT_PLAN_SLUG, {})
        workspace_overrides = workspace.overrides if workspace is not None else {}

        return ResolvedQuota(
            workspace=_merge(
                (
                    workspace_overrides.get("workspace", EMPTY),
                    plan.get("workspace", EMPTY),
                )
            ),
            principal=_merge(
                (
                    key_override,
                    workspace_overrides.get(principal_scope, EMPTY),
                    plan.get(principal_scope, EMPTY),
                )
            ),
            principal_scope=principal_scope,
            cost=policy.costs.get(operation, 0),
        )

    async def _load_global(self) -> _Global:
        cached = self._fresh(self._global)
        if cached is not None:
            return cached
        async with self._session_factory() as session:
            plan_rows = (await session.execute(select(QuotaPlan.id, QuotaPlan.slug))).all()
            limit_rows = (await session.execute(select(QuotaPlanLimit))).scalars().all()
            cost_rows = (
                await session.execute(
                    select(QuotaOperation.slug, QuotaOperation.cost).where(QuotaOperation.enabled.is_(True))
                )
            ).all()

        slugs = {int(plan_id): str(slug) for plan_id, slug in plan_rows}
        plans: dict[str, dict[str, QuotaLimits]] = {slug: {} for slug in slugs.values()}
        for row in limit_rows:
            slug = slugs.get(int(row.plan_id))
            if slug is not None:
                plans[slug][str(row.scope)] = QuotaLimits.of(row)

        value = _Global(
            plans=plans,
            plan_slugs=slugs,
            costs={str(slug): int(cost) for slug, cost in cost_rows},
        )
        self._global = self._store(value)
        return value

    async def _load_workspace(self, workspace_id: int) -> _WorkspacePolicy:
        cached = self._fresh(self._workspaces.get(workspace_id))
        if cached is not None:
            return cached
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(Workspace.verification_status, Workspace.quota_plan_id).where(Workspace.id == workspace_id)
                )
            ).first()
            override_rows = (
                (
                    await session.execute(
                        select(QuotaWorkspaceLimit).where(QuotaWorkspaceLimit.workspace_id == workspace_id)
                    )
                )
                .scalars()
                .all()
            )

        plan_slug: str | None = None
        if row is not None:
            verification_status, plan_id = row
            # An explicit assignment wins; otherwise the plan named after the
            # tier, which is the axis a superuser already moves workspaces on.
            if plan_id is not None:
                policy = await self._load_global()
                plan_slug = policy.plan_slugs.get(int(plan_id))
            plan_slug = plan_slug or (str(verification_status) if verification_status else None)

        value = _WorkspacePolicy(
            plan_slug=plan_slug,
            overrides={str(override.scope): QuotaLimits.of(override) for override in override_rows},
        )
        self._workspaces[workspace_id] = self._store(value)
        return value

    async def _load_key(self, api_key_id: int) -> QuotaLimits:
        cached = self._fresh(self._keys.get(api_key_id))
        if cached is not None:
            return cached
        async with self._session_factory() as session:
            row = (
                await session.execute(select(QuotaApiKeyLimit).where(QuotaApiKeyLimit.api_key_id == api_key_id))
            ).scalar_one_or_none()
        value = QuotaLimits.of(row) if row is not None else EMPTY
        self._keys[api_key_id] = self._store(value)
        return value
