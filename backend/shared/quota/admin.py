"""Writes against the ``quota`` policy tables, with the one rule that matters.

A superuser may set any value at any scope -- that is the escape hatch for a
partner integration without moving a whole tier. A workspace admin may only
*lower* a value below what it would otherwise inherit, and that is checked here,
once, on the way in: the stored row is then always the truth, with no surprising
``min()`` at read time.

Propagation to other replicas is bounded by the policy cache TTL (60s). The
writing process drops its own cache immediately, so an admin sees the effect of
their own edit at once.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models import QuotaApiKeyLimit, QuotaOperation, QuotaPlan, QuotaPlanLimit, QuotaWorkspaceLimit, Workspace
from shared.quota.policy import _CAPS, _COUNTERS, DEFAULT_PLAN_SLUG
from shared.repository import (
    QuotaApiKeyLimitRepository,
    QuotaOperationRepository,
    QuotaPlanLimitRepository,
    QuotaPlanRepository,
    QuotaWorkspaceLimitRepository,
)

# Row access goes through the repositories, per the boundary in
# ``backend/docs/repository-boundaries.md``: what is interesting here is the
# authority rule, not the persistence.
_plans = QuotaPlanRepository()
_plan_limits = QuotaPlanLimitRepository()
_operations = QuotaOperationRepository()
_workspace_limits = QuotaWorkspaceLimitRepository()
_api_key_limits = QuotaApiKeyLimitRepository()

__all__ = (
    "DIMENSIONS",
    "apply_api_key_limits",
    "apply_workspace_limits",
    "inherited_limits",
    "load_operations",
    "load_plans",
    "plan_slug_for_workspace",
    "upsert_operation",
    "upsert_plan",
    "workspace_override",
)

#: The five dimensions, in the order every table declares them.
DIMENSIONS = (*_COUNTERS, *_CAPS)


def _reject_raise(dimension: str, requested: int, inherited: int | None) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "quota_above_inherited",
            "limit_name": dimension,
            "limit": inherited,
            "requested": requested,
        },
    )


async def plan_slug_for_workspace(session: Any, workspace_id: int) -> str:
    """Which plan a workspace runs on: its explicit assignment, else its tier."""
    row = (
        await session.execute(
            select(Workspace.verification_status, Workspace.quota_plan_id).where(Workspace.id == workspace_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    verification_status, plan_id = row
    if plan_id is not None:
        slug = (await session.execute(select(QuotaPlan.slug).where(QuotaPlan.id == int(plan_id)))).scalar_one_or_none()
        if slug:
            return str(slug)
    return str(verification_status or DEFAULT_PLAN_SLUG)


async def inherited_limits(
    session: Any,
    *,
    workspace_id: int,
    scope: str,
    skip_workspace_override: bool = False,
) -> dict[str, int | None]:
    """The ceiling a write must stay under, i.e. everything above that level.

    For a workspace-scope write that is the plan row alone; for a key write it
    is the plan row narrowed by the workspace's own override, because a tenant
    that tightened its keys must not be widened again by one of them.
    """
    plan_slug = await plan_slug_for_workspace(session, workspace_id)
    plan_row = (
        await session.execute(
            select(QuotaPlanLimit)
            .join(QuotaPlan, QuotaPlan.id == QuotaPlanLimit.plan_id)
            .where(QuotaPlan.slug == plan_slug, QuotaPlanLimit.scope == scope)
        )
    ).scalar_one_or_none()
    inherited = {name: (getattr(plan_row, name) if plan_row is not None else None) for name in DIMENSIONS}

    if skip_workspace_override:
        return inherited

    workspace_row = (
        await session.execute(
            select(QuotaWorkspaceLimit).where(
                QuotaWorkspaceLimit.workspace_id == workspace_id,
                QuotaWorkspaceLimit.scope == scope,
            )
        )
    ).scalar_one_or_none()
    if workspace_row is None:
        return inherited
    for name in _COUNTERS:
        value = getattr(workspace_row, name)
        if value is not None:
            inherited[name] = value
    for name in _CAPS:
        value = getattr(workspace_row, name)
        candidates = [item for item in (value, inherited[name]) if item is not None]
        inherited[name] = min(candidates) if candidates else None
    return inherited


async def workspace_override(session: Any, *, workspace_id: int, scope: str) -> dict[str, int | None]:
    """The stored override row as a flat dimension map, all-``None`` when absent.

    Distinct from ``inherited_limits`` on purpose: that answers "what will be
    enforced", this answers "what is written here", and an editor that cannot
    tell them apart offers a form whose empty state silently deletes the row.
    """
    row = (
        await session.execute(
            select(QuotaWorkspaceLimit).where(
                QuotaWorkspaceLimit.workspace_id == workspace_id,
                QuotaWorkspaceLimit.scope == scope,
            )
        )
    ).scalar_one_or_none()
    return {name: (getattr(row, name) if row is not None else None) for name in DIMENSIONS}


def _assert_within(values: dict[str, int | None], inherited: dict[str, int | None]) -> None:
    for dimension, requested in values.items():
        if requested is None:
            continue
        ceiling = inherited.get(dimension)
        # An inherited ``None`` is "unlimited", and a workspace admin lowering
        # an unlimited dimension is exactly the case this must allow.
        if ceiling is not None and requested > ceiling:
            _reject_raise(dimension, requested, ceiling)


async def apply_workspace_limits(
    session: Any,
    *,
    workspace_id: int,
    scope: str,
    values: dict[str, int | None],
    updated_by: int | None,
    allow_raise: bool,
) -> QuotaWorkspaceLimit | None:
    """Upsert one workspace override row, or delete it when fully unset."""
    if not allow_raise:
        _assert_within(
            values,
            await inherited_limits(session, workspace_id=workspace_id, scope=scope, skip_workspace_override=True),
        )

    if all(value is None for value in values.values()):
        await _workspace_limits.remove(session, workspace_id=workspace_id, scope=scope)
        return None

    return await _workspace_limits.upsert(
        session,
        workspace_id=workspace_id,
        scope=scope,
        values=values,
        updated_by=updated_by,
    )


async def apply_api_key_limits(
    session: Any,
    *,
    api_key_id: int,
    workspace_id: int,
    values: dict[str, int | None],
    updated_by: int | None,
    allow_raise: bool,
) -> QuotaApiKeyLimit | None:
    if not allow_raise:
        _assert_within(values, await inherited_limits(session, workspace_id=workspace_id, scope="key"))

    if all(value is None for value in values.values()):
        await _api_key_limits.remove(session, api_key_id=api_key_id)
        return None

    return await _api_key_limits.upsert(
        session,
        api_key_id=api_key_id,
        values=values,
        updated_by=updated_by,
    )


async def load_plans(session: Any) -> list[tuple[QuotaPlan, list[QuotaPlanLimit]]]:
    plans = await _plans.list_all(session)
    limits = await _plan_limits.list_all(session)
    by_plan: dict[int, list[QuotaPlanLimit]] = {}
    for limit in limits:
        by_plan.setdefault(int(limit.plan_id), []).append(limit)
    return [(plan, sorted(by_plan.get(int(plan.id), []), key=lambda row: row.scope)) for plan in plans]


async def upsert_plan(
    session: Any,
    *,
    slug: str,
    title: str,
    description: str | None,
    limits: list[dict[str, Any]],
) -> QuotaPlan:
    """Create or replace one plan and its scope rows.

    The scope rows are replaced wholesale rather than merged: a plan is read as
    a complete statement of its tier, and a partial update would leave a scope
    nobody remembers setting.
    """
    plan = await _plans.get_by_slug(session, slug)
    if plan is None:
        plan = await _plans.create_plan(session, slug=slug, title=title, description=description)
    else:
        plan.title = title
        plan.description = description

    await _plan_limits.replace_for_plan(
        session,
        plan_id=int(plan.id),
        rows=[
            {"scope": entry["scope"], **{dimension: entry.get(dimension) for dimension in DIMENSIONS}}
            for entry in limits
        ],
    )
    return plan


async def load_operations(session: Any) -> list[QuotaOperation]:
    return await _operations.list_all(session)


async def upsert_operation(
    session: Any,
    *,
    slug: str,
    cost: int,
    enabled: bool,
    description: str | None,
) -> QuotaOperation:
    return await _operations.upsert(session, slug=slug, cost=cost, enabled=enabled, description=description)
