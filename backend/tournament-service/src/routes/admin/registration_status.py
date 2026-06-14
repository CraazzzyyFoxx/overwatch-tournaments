"""Admin endpoints for registration status catalog."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db
from src.schemas.admin import balancer as admin_schemas
from src.services.registration import status_catalog
from src.services.registration.serializers import serialize_status

router = APIRouter(
    prefix="/ws/{workspace_id}/balancer-statuses",
    tags=["registration-status"],
)


@router.get("/catalog", response_model=list[admin_schemas.BalancerRegistrationStatusRead])
async def list_status_catalog(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "read")),
):
    statuses = await status_catalog.list_status_catalog(session, workspace_id)
    return [serialize_status(status_row) for status_row in statuses]


@router.get("", response_model=list[admin_schemas.BalancerRegistrationStatusRead])
async def list_custom_statuses(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "read")),
):
    statuses = await status_catalog.list_custom_statuses(session, workspace_id)
    return [serialize_status(status_row) for status_row in statuses]


@router.post(
    "/custom",
    response_model=admin_schemas.BalancerRegistrationStatusRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_custom_status(
    workspace_id: int,
    data: admin_schemas.BalancerRegistrationStatusCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "update")),
):
    status_row = await status_catalog.create_custom_status(
        session,
        workspace_id=workspace_id,
        scope=data.scope,
        icon_slug=data.icon_slug,
        icon_color=data.icon_color,
        name=data.name,
        description=data.description,
    )
    return serialize_status(status_row)


@router.patch("/custom/{status_id}", response_model=admin_schemas.BalancerRegistrationStatusRead)
async def update_custom_status(
    workspace_id: int,
    status_id: int,
    data: admin_schemas.BalancerRegistrationStatusUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "update")),
):
    status_row = await status_catalog.update_custom_status(
        session,
        workspace_id=workspace_id,
        status_id=status_id,
        icon_slug=data.icon_slug,
        icon_color=data.icon_color,
        name=data.name,
        description=data.description,
    )
    return serialize_status(status_row)


@router.delete("/custom/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_status(
    workspace_id: int,
    status_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "update")),
):
    await status_catalog.delete_custom_status(
        session,
        workspace_id=workspace_id,
        status_id=status_id,
    )


@router.put("/system/{scope}/{slug}", response_model=admin_schemas.BalancerRegistrationStatusRead)
async def upsert_builtin_override(
    workspace_id: int,
    scope: admin_schemas.StatusScope,
    slug: str,
    data: admin_schemas.BalancerRegistrationStatusUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "update")),
):
    status_row = await status_catalog.upsert_builtin_override(
        session,
        workspace_id=workspace_id,
        scope=scope,
        slug=slug,
        icon_slug=data.icon_slug,
        icon_color=data.icon_color,
        name=data.name,
        description=data.description,
    )
    return serialize_status(status_row)


@router.delete("/system/{scope}/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def reset_builtin_override(
    workspace_id: int,
    scope: admin_schemas.StatusScope,
    slug: str,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "update")),
):
    await status_catalog.reset_builtin_override(
        session,
        workspace_id=workspace_id,
        scope=scope,
        slug=slug,
    )
