from fastapi import HTTPException, status
from shared.domain.player_sub_roles import normalize_role, normalize_sub_role
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.schemas.admin import player_sub_role as schemas


def _normalize_role_or_raise(role: str | None) -> str:
    normalized = normalize_role(role)
    if normalized is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role is required.",
        )
    return normalized


def _normalize_slug_or_raise(slug: str | None, label: str | None) -> str:
    normalized = normalize_sub_role(slug or label)
    if normalized is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sub-role slug or label is required.",
        )
    return normalized


async def list_sub_roles(
    session: AsyncSession,
    *,
    workspace_id: int,
    role: str | None = None,
    include_inactive: bool = False,
) -> list[models.PlayerSubRole]:
    query = select(models.PlayerSubRole).where(models.PlayerSubRole.workspace_id == workspace_id)
    if role is not None:
        query = query.where(models.PlayerSubRole.role == _normalize_role_or_raise(role))
    if not include_inactive:
        query = query.where(models.PlayerSubRole.is_active.is_(True))

    query = query.order_by(
        models.PlayerSubRole.role.asc(),
        models.PlayerSubRole.sort_order.asc(),
        models.PlayerSubRole.label.asc(),
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_sub_role(session: AsyncSession, sub_role_id: int) -> models.PlayerSubRole:
    result = await session.execute(select(models.PlayerSubRole).where(models.PlayerSubRole.id == sub_role_id))
    sub_role = result.scalar_one_or_none()
    if sub_role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player sub-role not found.",
        )
    return sub_role


async def create_sub_role(
    session: AsyncSession,
    data: schemas.PlayerSubRoleCreate,
) -> models.PlayerSubRole:
    role = _normalize_role_or_raise(data.role)
    slug = _normalize_slug_or_raise(data.slug, data.label)

    existing = await session.execute(
        select(models.PlayerSubRole).where(
            models.PlayerSubRole.workspace_id == data.workspace_id,
            models.PlayerSubRole.role == role,
            models.PlayerSubRole.slug == slug,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player sub-role already exists for this workspace and role.",
        )

    sub_role = models.PlayerSubRole(
        workspace_id=data.workspace_id,
        role=role,
        slug=slug,
        label=data.label.strip(),
        description=data.description,
        sort_order=data.sort_order,
        is_active=data.is_active,
    )
    session.add(sub_role)
    await session.commit()
    await session.refresh(sub_role)
    return sub_role


async def update_sub_role(
    session: AsyncSession,
    sub_role_id: int,
    data: schemas.PlayerSubRoleUpdate,
) -> models.PlayerSubRole:
    sub_role = await get_sub_role(session, sub_role_id)
    update_data = data.model_dump(exclude_unset=True)

    if "role" in update_data:
        update_data["role"] = _normalize_role_or_raise(update_data["role"])
    if "slug" in update_data:
        update_data["slug"] = _normalize_slug_or_raise(
            update_data["slug"],
            update_data.get("label", sub_role.label),
        )
    if "label" in update_data and update_data["label"] is not None:
        update_data["label"] = update_data["label"].strip()

    next_role = update_data.get("role", sub_role.role)
    next_slug = update_data.get("slug", sub_role.slug)
    if next_role != sub_role.role or next_slug != sub_role.slug:
        existing = await session.execute(
            select(models.PlayerSubRole).where(
                models.PlayerSubRole.workspace_id == sub_role.workspace_id,
                models.PlayerSubRole.role == next_role,
                models.PlayerSubRole.slug == next_slug,
                models.PlayerSubRole.id != sub_role.id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Player sub-role already exists for this workspace and role.",
            )

    for field, value in update_data.items():
        setattr(sub_role, field, value)

    await session.commit()
    await session.refresh(sub_role)
    return sub_role


async def deactivate_sub_role(session: AsyncSession, sub_role_id: int) -> None:
    sub_role = await get_sub_role(session, sub_role_id)
    sub_role.is_active = False
    await session.commit()
