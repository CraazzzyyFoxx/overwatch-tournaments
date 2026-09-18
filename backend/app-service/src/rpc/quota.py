"""Platform-wide quota policy: the plan/operation catalogue and usage reads.

The numbers every metered service enforces live in the ``quota`` schema, and
this is the only way to edit them. Plans and operations are global game rules
rather than tenant data, so both writes are superuser-only — the per-workspace
half of the surface (``rpc.app.workspaces.quota_set``) sits next to the other
workspace writes in ``rpc/workspaces.py`` instead.

Pure transport: ``shared.quota.admin`` owns the SQL and the authority rule, this
module decodes the envelope, runs the gate, stages the audit row and commits.
Each write ends with ``quota.invalidate_policy()`` so this worker stops serving
the ceiling it just replaced; the other replicas fall back to their own cache
TTL, which is what the shared invalidation rail is for elsewhere.

``workspace_usage`` reports the workspace bucket only. The per-key and
per-session buckets belong to principals the workspace's admin does not
necessarily own, and identity-service already answers for an API key. Its
``policy`` half is wider than its ``scopes`` half on purpose: all three override
rows live in this tenant's own ``quota.workspace_limit``, and the screen that
edits them has to show what is stored there before it can offer to replace it.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared import quota
from shared.core.errors import BaseAPIException as HTTPException
from shared.quota import admin as quota_admin
from shared.rpc.identity import ensure_workspace_permission
from shared.schemas.quota import (
    QUOTA_SCOPES,
    QuotaLimitsPayload,
    QuotaOperationRead,
    QuotaOperationWrite,
    QuotaPlanLimitRead,
    QuotaPlanRead,
    QuotaPlanWrite,
    QuotaScopePolicy,
    QuotaScopeUsage,
    QuotaUsageRead,
)
from shared.services.audit import record_admin_audit
from src.core import db

from . import _common as c

_SF = db.async_session_maker


def _workspace_id(data: dict[str, Any]) -> int:
    """``workspace_id`` as a path param, falling back to the query string."""
    raw = data.get("workspace_id")
    if raw is None:
        raw = c.q1(data, "workspace_id", int)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="workspace_id is required") from exc


def _plan_read(plan: Any, limits: list[Any]) -> QuotaPlanRead:
    return QuotaPlanRead.model_validate(
        {
            "id": plan.id,
            "slug": plan.slug,
            "title": plan.title,
            "description": plan.description,
            "limits": [QuotaPlanLimitRead.model_validate(row, from_attributes=True) for row in limits],
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
        }
    )


def _plan_snapshot(title: str, description: str | None, limits: list[Any]) -> dict[str, Any]:
    """What the journal keeps of a plan: the numbers, not the row identity."""
    return {
        "title": title,
        "description": description,
        "limits": [
            QuotaPlanLimitRead.model_validate(row, from_attributes=True).model_dump(mode="json") for row in limits
        ],
    }


async def _scope_policy(session: Any, workspace_id: int) -> list[QuotaScopePolicy]:
    """Every scope's stored row next to the ceiling ``quota_set`` holds it to.

    ``skip_workspace_override=True`` matches ``apply_workspace_limits``: the row
    being edited is never its own ceiling, so the bound reported here is the one
    a non-superuser write is actually measured against.
    """
    return [
        QuotaScopePolicy(
            scope=scope,
            override=QuotaLimitsPayload(
                **await quota_admin.workspace_override(session, workspace_id=workspace_id, scope=scope)
            ),
            inherited=QuotaLimitsPayload(
                **await quota_admin.inherited_limits(
                    session, workspace_id=workspace_id, scope=scope, skip_workspace_override=True
                )
            ),
        )
        for scope in QUOTA_SCOPES
    ]


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.quota.plans")
    async def _plans(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_superuser(c.actor(data))
            return [_plan_read(plan, limits) for plan, limits in await quota_admin.load_plans(session)]

        return await c.envelope(logger, "quota.plans", op, session_factory=_SF)

    @broker.subscriber("rpc.app.quota.plan_upsert")
    async def _plan_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_superuser(user)
            body = QuotaPlanWrite.model_validate(c.payload(data))
            existing = next(
                ((plan, limits) for plan, limits in await quota_admin.load_plans(session) if plan.slug == body.slug),
                None,
            )
            before = _plan_snapshot(existing[0].title, existing[0].description, existing[1]) if existing else None
            plan = await quota_admin.upsert_plan(
                session,
                slug=body.slug,
                title=body.title,
                description=body.description,
                limits=[row.model_dump() for row in body.limits],
            )
            await record_admin_audit(
                session,
                action="quota.plan_upsert",
                actor=user,
                data=data,
                workspace_id=None,
                entity_type="quota_plan",
                entity_id=plan.id,
                entity_label=body.slug,
                before=before,
                after=_plan_snapshot(body.title, body.description, body.limits),
            )
            await session.commit()
            quota.invalidate_policy()
            return _plan_read(plan, body.limits)

        return await c.envelope(logger, "quota.plan_upsert", op, session_factory=_SF)

    @broker.subscriber("rpc.app.quota.operations")
    async def _operations(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_superuser(c.actor(data))
            return [
                QuotaOperationRead.model_validate(row, from_attributes=True)
                for row in await quota_admin.load_operations(session)
            ]

        return await c.envelope(logger, "quota.operations", op, session_factory=_SF)

    @broker.subscriber("rpc.app.quota.operation_upsert")
    async def _operation_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_superuser(user)
            body = QuotaOperationWrite.model_validate(c.payload(data))
            existing = next((row for row in await quota_admin.load_operations(session) if row.slug == body.slug), None)
            before = (
                {"cost": existing.cost, "enabled": existing.enabled, "description": existing.description}
                if existing
                else None
            )
            row = await quota_admin.upsert_operation(
                session,
                slug=body.slug,
                cost=body.cost,
                enabled=body.enabled,
                description=body.description,
            )
            await record_admin_audit(
                session,
                action="quota.operation_upsert",
                actor=user,
                data=data,
                workspace_id=None,
                entity_type="quota_operation",
                entity_id=row.id,
                entity_label=body.slug,
                before=before,
                after={"cost": body.cost, "enabled": body.enabled, "description": body.description},
            )
            await session.commit()
            quota.invalidate_policy()
            return QuotaOperationRead.model_validate(row, from_attributes=True)

        return await c.envelope(logger, "quota.operation_upsert", op, session_factory=_SF)

    @broker.subscriber("rpc.app.quota.workspace_usage")
    async def _workspace_usage(data: dict, msg: RabbitMessage) -> dict:
        """What this tenant's shared pool has spent this minute and this day.

        Counted for the caller as a ``user`` principal, which is what puts the
        workspace bucket in the report; the principal's own session bucket is
        dropped, since "how much of my personal rate have I used" is not what an
        operator opens this screen for.
        """

        async def op(session: Any) -> Any:
            workspace_id = _workspace_id(data)
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "team", "create")
            # 404s an unknown workspace before Redis is touched.
            plan_slug = await quota_admin.plan_slug_for_workspace(session, workspace_id)
            report = await quota.usage(principal_kind="user", principal_id=int(user.id), workspace_id=workspace_id)
            return QuotaUsageRead(
                plan_slug=plan_slug,
                workspace_id=workspace_id,
                scopes=[
                    QuotaScopeUsage.model_validate(entry)
                    for entry in report.get("scopes", [])
                    if entry.get("scope") == "workspace"
                ],
                policy=await _scope_policy(session, workspace_id),
            )

        return await c.envelope(logger, "quota.workspace_usage", op, session_factory=_SF)
