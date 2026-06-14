from __future__ import annotations

import re
from typing import Literal, TypedDict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models

StatusScope = Literal["registration", "balancer"]
StatusKind = Literal["builtin", "custom"]


class StatusMeta(TypedDict):
    value: str
    scope: StatusScope
    is_builtin: bool
    kind: StatusKind
    is_override: bool
    can_edit: bool
    can_delete: bool
    can_reset: bool
    icon_slug: str | None
    icon_color: str | None
    name: str
    description: str | None


BUILTIN_STATUS_META: dict[StatusScope, dict[str, StatusMeta]] = {
    "registration": {
        "pending": {
            "value": "pending",
            "scope": "registration",
            "is_builtin": True,
            "kind": "builtin",
            "is_override": False,
            "can_edit": True,
            "can_delete": False,
            "can_reset": False,
            "icon_slug": "Clock",
            "icon_color": "#f59e0b",
            "name": "Pending",
            "description": "Waiting for moderator review.",
        },
        "approved": {
            "value": "approved",
            "scope": "registration",
            "is_builtin": True,
            "kind": "builtin",
            "is_override": False,
            "can_edit": True,
            "can_delete": False,
            "can_reset": False,
            "icon_slug": "CheckCircle2",
            "icon_color": "#10b981",
            "name": "Approved",
            "description": "Registration approved.",
        },
        "rejected": {
            "value": "rejected",
            "scope": "registration",
            "is_builtin": True,
            "kind": "builtin",
            "is_override": False,
            "can_edit": True,
            "can_delete": False,
            "can_reset": False,
            "icon_slug": "XCircle",
            "icon_color": "#ef4444",
            "name": "Rejected",
            "description": "Registration rejected.",
        },
        "withdrawn": {
            "value": "withdrawn",
            "scope": "registration",
            "is_builtin": True,
            "kind": "builtin",
            "is_override": False,
            "can_edit": True,
            "can_delete": False,
            "can_reset": False,
            "icon_slug": "Undo2",
            "icon_color": "#94a3b8",
            "name": "Withdrawn",
            "description": "Registration withdrawn by participant or admin.",
        },
        "banned": {
            "value": "banned",
            "scope": "registration",
            "is_builtin": True,
            "kind": "builtin",
            "is_override": False,
            "can_edit": True,
            "can_delete": False,
            "can_reset": False,
            "icon_slug": "ShieldBan",
            "icon_color": "#ef4444",
            "name": "Banned",
            "description": "Registration blocked.",
        },
        "insufficient_data": {
            "value": "insufficient_data",
            "scope": "registration",
            "is_builtin": True,
            "kind": "builtin",
            "is_override": False,
            "can_edit": True,
            "can_delete": False,
            "can_reset": False,
            "icon_slug": "AlertTriangle",
            "icon_color": "#f97316",
            "name": "Incomplete",
            "description": "Registration data is incomplete.",
        },
    },
    "balancer": {
        "not_in_balancer": {
            "value": "not_in_balancer",
            "scope": "balancer",
            "is_builtin": True,
            "kind": "builtin",
            "is_override": False,
            "can_edit": True,
            "can_delete": False,
            "can_reset": False,
            "icon_slug": "MinusCircle",
            "icon_color": "#94a3b8",
            "name": "Not Added",
            "description": "Registration is excluded from the balancer pool.",
        },
        "incomplete": {
            "value": "incomplete",
            "scope": "balancer",
            "is_builtin": True,
            "kind": "builtin",
            "is_override": False,
            "can_edit": True,
            "can_delete": False,
            "can_reset": False,
            "icon_slug": "AlertTriangle",
            "icon_color": "#f97316",
            "name": "Incomplete",
            "description": "Registration needs role or rank fixes before balancing.",
        },
        "ready": {
            "value": "ready",
            "scope": "balancer",
            "is_builtin": True,
            "kind": "builtin",
            "is_override": False,
            "can_edit": True,
            "can_delete": False,
            "can_reset": False,
            "icon_slug": "CheckCircle2",
            "icon_color": "#10b981",
            "name": "Ready",
            "description": "Registration is ready for the balancer pool.",
        },
    },
}

UNKNOWN_STATUS_META: dict[StatusScope, StatusMeta] = {
    "registration": {
        "value": "unknown",
        "scope": "registration",
        "is_builtin": False,
        "kind": "custom",
        "is_override": False,
        "can_edit": False,
        "can_delete": False,
        "can_reset": False,
        "icon_slug": "BadgeHelp",
        "icon_color": "#94a3b8",
        "name": "Unknown",
        "description": "Unknown registration status.",
    },
    "balancer": {
        "value": "unknown",
        "scope": "balancer",
        "is_builtin": False,
        "kind": "custom",
        "is_override": False,
        "can_edit": False,
        "can_delete": False,
        "can_reset": False,
        "icon_slug": "BadgeHelp",
        "icon_color": "#94a3b8",
        "name": "Unknown",
        "description": "Unknown balancer status.",
    },
}


def get_builtin_status_values(scope: StatusScope) -> set[str]:
    return set(BUILTIN_STATUS_META[scope].keys())


def get_builtin_status_meta(scope: StatusScope, value: str) -> StatusMeta | None:
    return BUILTIN_STATUS_META[scope].get(value)


def build_status_meta_from_model(
    status: models.BalancerRegistrationStatus,
) -> StatusMeta:
    is_builtin = status.kind == "builtin"
    is_override = is_builtin and status.workspace_id is not None
    return {
        "value": status.slug,
        "scope": status.scope,  # type: ignore[typeddict-item]
        "is_builtin": is_builtin,
        "kind": status.kind,  # type: ignore[typeddict-item]
        "is_override": is_override,
        "can_edit": True,
        "can_delete": status.kind == "custom",
        "can_reset": is_override,
        "icon_slug": status.icon_slug,
        "icon_color": status.icon_color,
        "name": status.name,
        "description": status.description,
    }


def build_unknown_status_meta(scope: StatusScope, value: str) -> StatusMeta:
    return {
        **UNKNOWN_STATUS_META[scope],
        "value": value,
        "name": value.replace("_", " ").strip().title() or UNKNOWN_STATUS_META[scope]["name"],
    }


async def list_workspace_status_rows(
    session: AsyncSession,
    workspace_id: int,
    scope: StatusScope | None = None,
) -> list[models.BalancerRegistrationStatus]:
    query = sa.select(models.BalancerRegistrationStatus).where(
        sa.or_(
            models.BalancerRegistrationStatus.workspace_id == workspace_id,
            models.BalancerRegistrationStatus.workspace_id.is_(None),
        )
    )
    if scope is not None:
        query = query.where(models.BalancerRegistrationStatus.scope == scope)
    query = query.order_by(
        models.BalancerRegistrationStatus.scope.asc(),
        sa.case((models.BalancerRegistrationStatus.workspace_id.is_(None), 0), else_=1).asc(),
        models.BalancerRegistrationStatus.kind.asc(),
        models.BalancerRegistrationStatus.name.asc(),
        models.BalancerRegistrationStatus.id.asc(),
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def list_custom_statuses(
    session: AsyncSession,
    workspace_id: int,
    scope: StatusScope | None = None,
) -> list[models.BalancerRegistrationStatus]:
    query = sa.select(models.BalancerRegistrationStatus).where(
        models.BalancerRegistrationStatus.workspace_id == workspace_id,
        models.BalancerRegistrationStatus.kind == "custom",
    )
    if scope is not None:
        query = query.where(models.BalancerRegistrationStatus.scope == scope)
    query = query.order_by(
        models.BalancerRegistrationStatus.scope.asc(),
        models.BalancerRegistrationStatus.name.asc(),
        models.BalancerRegistrationStatus.id.asc(),
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_status_meta(
    session: AsyncSession,
    *,
    workspace_id: int,
    scope: StatusScope,
    value: str,
) -> StatusMeta:
    workspace_result = await session.execute(
        sa.select(models.BalancerRegistrationStatus).where(
            models.BalancerRegistrationStatus.workspace_id == workspace_id,
            models.BalancerRegistrationStatus.scope == scope,
            models.BalancerRegistrationStatus.slug == value,
        )
    )
    workspace_status = workspace_result.scalar_one_or_none()
    if workspace_status is not None:
        return build_status_meta_from_model(workspace_status)

    builtin_result = await session.execute(
        sa.select(models.BalancerRegistrationStatus).where(
            models.BalancerRegistrationStatus.workspace_id.is_(None),
            models.BalancerRegistrationStatus.kind == "builtin",
            models.BalancerRegistrationStatus.scope == scope,
            models.BalancerRegistrationStatus.slug == value,
        )
    )
    builtin_status = builtin_result.scalar_one_or_none()
    if builtin_status is not None:
        return build_status_meta_from_model(builtin_status)

    builtin_fallback = get_builtin_status_meta(scope, value)
    if builtin_fallback is not None:
        return builtin_fallback
    return build_unknown_status_meta(scope, value)


async def get_status_metas_map(
    session: AsyncSession,
    *,
    workspace_id: int,
) -> dict[StatusScope, dict[str, StatusMeta]]:
    merged: dict[StatusScope, dict[str, StatusMeta]] = {
        "registration": {},
        "balancer": {},
    }

    rows = await list_workspace_status_rows(session, workspace_id)
    for row in rows:
        if row.workspace_id is None and row.kind != "builtin":
            continue
        merged[row.scope][row.slug] = build_status_meta_from_model(row)  # type: ignore[index]

    for scope, items in BUILTIN_STATUS_META.items():
        for slug, item in items.items():
            merged[scope].setdefault(slug, item)
    return merged


def normalize_status_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug[:32]
