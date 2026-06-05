from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.composition import build_registration_status_use_cases
from src.core import auth, db
from src.presentation.http.admin_status_serializers import (
    serialize_status as _serialize_status,
)
from src.schemas.admin import balancer as admin_schemas

router = APIRouter(
    prefix="/ws/{workspace_id}/balancer-statuses",
    tags=["registration-status"],
    dependencies=[Depends(auth.require_admin_panel_access())],
)
use_cases = build_registration_status_use_cases()


@router.get("/catalog", response_model=list[admin_schemas.BalancerRegistrationStatusRead])
async def list_status_catalog(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "read")),
):
    statuses = await use_cases.list_status_catalog.execute(session=session, workspace_id=workspace_id)
    return [_serialize_status(status_row) for status_row in statuses]


@router.get("", response_model=list[admin_schemas.BalancerRegistrationStatusRead])
async def list_custom_statuses(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "read")),
):
    statuses = await use_cases.list_custom_statuses.execute(session=session, workspace_id=workspace_id)
    return [_serialize_status(status_row) for status_row in statuses]


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
    status_row = await use_cases.create_custom_status.execute(
        session=session,
        workspace_id=workspace_id,
        payload=data,
    )
    return _serialize_status(status_row)


@router.patch("/custom/{status_id}", response_model=admin_schemas.BalancerRegistrationStatusRead)
async def update_custom_status(
    workspace_id: int,
    status_id: int,
    data: admin_schemas.BalancerRegistrationStatusUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "update")),
):
    status_row = await use_cases.update_custom_status.execute(
        session=session,
        workspace_id=workspace_id,
        status_id=status_id,
        payload=data,
    )
    return _serialize_status(status_row)


@router.delete("/custom/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_status(
    workspace_id: int,
    status_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "update")),
):
    await use_cases.delete_custom_status.execute(
        session=session,
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
    status_row = await use_cases.upsert_builtin_override.execute(
        session=session,
        workspace_id=workspace_id,
        scope=scope,
        slug=slug,
        payload=data,
    )
    return _serialize_status(status_row)


@router.delete("/system/{scope}/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def reset_builtin_override(
    workspace_id: int,
    scope: admin_schemas.StatusScope,
    slug: str,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("team", "update")),
):
    await use_cases.reset_builtin_override.execute(
        session=session,
        workspace_id=workspace_id,
        scope=scope,
        slug=slug,
    )
