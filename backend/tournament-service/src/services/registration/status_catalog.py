from __future__ import annotations

import sqlalchemy as sa
from fastapi import HTTPException, status
from shared.balancer_registration_statuses import (
    StatusScope,
    get_builtin_status_values,
    normalize_status_slug,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src import models


async def ensure_workspace_exists(
    session: AsyncSession,
    workspace_id: int,
) -> models.Workspace:
    workspace = await session.get(models.Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return workspace


async def list_status_catalog(
    session: AsyncSession,
    workspace_id: int,
) -> list[models.BalancerRegistrationStatus]:
    await ensure_workspace_exists(session, workspace_id)
    result = await session.execute(
        sa.select(models.BalancerRegistrationStatus).where(
            sa.or_(
                models.BalancerRegistrationStatus.workspace_id == workspace_id,
                models.BalancerRegistrationStatus.workspace_id.is_(None),
            )
        )
    )
    rows = list(result.scalars().all())
    merged: dict[tuple[str, str], models.BalancerRegistrationStatus] = {}
    for row in sorted(
        rows,
        key=lambda item: (
            item.scope,
            0 if item.workspace_id is None else 1,
            0 if item.kind == "builtin" else 1,
            item.name.lower(),
            item.id,
        ),
    ):
        merged[(row.scope, row.slug)] = row
    return sorted(
        merged.values(),
        key=lambda item: (
            item.scope,
            0 if item.kind == "builtin" else 1,
            item.name.lower(),
            item.id,
        ),
    )


async def list_custom_statuses(
    session: AsyncSession,
    workspace_id: int,
) -> list[models.BalancerRegistrationStatus]:
    await ensure_workspace_exists(session, workspace_id)
    result = await session.execute(
        sa.select(models.BalancerRegistrationStatus)
        .where(
            models.BalancerRegistrationStatus.workspace_id == workspace_id,
            models.BalancerRegistrationStatus.kind == "custom",
        )
        .order_by(
            models.BalancerRegistrationStatus.scope.asc(),
            models.BalancerRegistrationStatus.name.asc(),
            models.BalancerRegistrationStatus.id.asc(),
        )
    )
    return list(result.scalars().all())


async def get_custom_status_by_id(
    session: AsyncSession,
    workspace_id: int,
    status_id: int,
) -> models.BalancerRegistrationStatus:
    result = await session.execute(
        sa.select(models.BalancerRegistrationStatus).where(
            models.BalancerRegistrationStatus.id == status_id,
            models.BalancerRegistrationStatus.workspace_id == workspace_id,
            models.BalancerRegistrationStatus.kind == "custom",
        )
    )
    status_row = result.scalar_one_or_none()
    if status_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom status not found",
        )
    return status_row


async def get_builtin_canonical_status(
    session: AsyncSession,
    *,
    scope: StatusScope,
    slug: str,
) -> models.BalancerRegistrationStatus:
    result = await session.execute(
        sa.select(models.BalancerRegistrationStatus).where(
            models.BalancerRegistrationStatus.workspace_id.is_(None),
            models.BalancerRegistrationStatus.kind == "builtin",
            models.BalancerRegistrationStatus.scope == scope,
            models.BalancerRegistrationStatus.slug == slug,
        )
    )
    status_row = result.scalar_one_or_none()
    if status_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Built-in status not found",
        )
    return status_row


async def _ensure_custom_slug_available(
    session: AsyncSession,
    *,
    workspace_id: int,
    scope: StatusScope,
    slug: str,
    exclude_status_id: int | None = None,
) -> None:
    if slug in get_builtin_status_values(scope):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Slug '{slug}' is reserved for a built-in {scope} status",
        )

    query = sa.select(models.BalancerRegistrationStatus.id).where(
        models.BalancerRegistrationStatus.workspace_id == workspace_id,
        models.BalancerRegistrationStatus.scope == scope,
        models.BalancerRegistrationStatus.slug == slug,
    )
    if exclude_status_id is not None:
        query = query.where(models.BalancerRegistrationStatus.id != exclude_status_id)

    existing_id = await session.scalar(query)
    if existing_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Slug '{slug}' already exists in workspace",
        )


def _normalize_name_to_slug(name: str) -> str:
    slug = normalize_status_slug(name)
    if not slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status name must contain letters or digits",
        )
    return slug


async def create_custom_status(
    session: AsyncSession,
    *,
    workspace_id: int,
    scope: StatusScope,
    icon_slug: str | None,
    icon_color: str | None,
    name: str,
    description: str | None,
) -> models.BalancerRegistrationStatus:
    await ensure_workspace_exists(session, workspace_id)
    slug = _normalize_name_to_slug(name)
    await _ensure_custom_slug_available(
        session,
        workspace_id=workspace_id,
        scope=scope,
        slug=slug,
    )
    status_row = models.BalancerRegistrationStatus(
        workspace_id=workspace_id,
        scope=scope,
        slug=slug,
        kind="custom",
        icon_slug=icon_slug,
        icon_color=icon_color,
        name=name.strip(),
        description=description.strip() if description else None,
    )
    session.add(status_row)
    await session.commit()
    await session.refresh(status_row)
    return status_row


async def update_custom_status(
    session: AsyncSession,
    *,
    workspace_id: int,
    status_id: int,
    icon_slug: str | None,
    icon_color: str | None,
    name: str | None,
    description: str | None,
) -> models.BalancerRegistrationStatus:
    status_row = await get_custom_status_by_id(session, workspace_id, status_id)

    if name is not None:
        normalized_name = name.strip()
        if not normalized_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Status name must not be empty",
            )
        status_row.name = normalized_name
    if icon_slug is not None:
        status_row.icon_slug = icon_slug or None
    if icon_color is not None:
        status_row.icon_color = icon_color or None
    if description is not None:
        status_row.description = description.strip() or None

    await session.commit()
    await session.refresh(status_row)
    return status_row


async def delete_custom_status(
    session: AsyncSession,
    *,
    workspace_id: int,
    status_id: int,
) -> None:
    status_row = await get_custom_status_by_id(session, workspace_id, status_id)
    registration_column = (
        models.BalancerRegistration.status
        if status_row.scope == "registration"
        else models.BalancerRegistration.balancer_status
    )
    in_use = await session.scalar(
        sa.select(sa.func.count(models.BalancerRegistration.id)).where(
            models.BalancerRegistration.workspace_id == workspace_id,
            registration_column == status_row.slug,
        )
    )
    if in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Custom status is in use by registrations and cannot be deleted",
        )

    await session.delete(status_row)
    await session.commit()


async def upsert_builtin_override(
    session: AsyncSession,
    *,
    workspace_id: int,
    scope: StatusScope,
    slug: str,
    icon_slug: str | None,
    icon_color: str | None,
    name: str | None,
    description: str | None,
) -> models.BalancerRegistrationStatus:
    await ensure_workspace_exists(session, workspace_id)
    if slug not in get_builtin_status_values(scope):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Slug '{slug}' is not a built-in {scope} status",
        )
    canonical = await get_builtin_canonical_status(session, scope=scope, slug=slug)
    result = await session.execute(
        sa.select(models.BalancerRegistrationStatus).where(
            models.BalancerRegistrationStatus.workspace_id == workspace_id,
            models.BalancerRegistrationStatus.scope == scope,
            models.BalancerRegistrationStatus.slug == slug,
            models.BalancerRegistrationStatus.kind == "builtin",
        )
    )
    status_row = result.scalar_one_or_none()
    if status_row is None:
        status_row = models.BalancerRegistrationStatus(
            workspace_id=workspace_id,
            scope=scope,
            slug=slug,
            kind="builtin",
            icon_slug=canonical.icon_slug,
            icon_color=canonical.icon_color,
            name=canonical.name,
            description=canonical.description,
        )
        session.add(status_row)

    if icon_slug is not None:
        status_row.icon_slug = icon_slug or None
    if icon_color is not None:
        status_row.icon_color = icon_color or None
    if name is not None:
        normalized_name = name.strip()
        if not normalized_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Status name must not be empty",
            )
        status_row.name = normalized_name
    if description is not None:
        status_row.description = description.strip() or None

    await session.commit()
    await session.refresh(status_row)
    return status_row


async def reset_builtin_override(
    session: AsyncSession,
    *,
    workspace_id: int,
    scope: StatusScope,
    slug: str,
) -> None:
    result = await session.execute(
        sa.select(models.BalancerRegistrationStatus).where(
            models.BalancerRegistrationStatus.workspace_id == workspace_id,
            models.BalancerRegistrationStatus.scope == scope,
            models.BalancerRegistrationStatus.slug == slug,
            models.BalancerRegistrationStatus.kind == "builtin",
        )
    )
    status_row = result.scalar_one_or_none()
    if status_row is None:
        return
    await session.delete(status_row)
    await session.commit()
