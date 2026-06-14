from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db
from src.schemas.admin import player_sub_role as schemas
from src.services.admin import player_sub_role as service

router = APIRouter(
    prefix="/player-sub-roles",
    tags=["admin", "player-sub-roles"],
)


@router.get("", response_model=list[schemas.PlayerSubRoleRead])
async def list_player_sub_roles(
    workspace_id: int,
    role: str | None = None,
    include_inactive: bool = False,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("player", "read")),
):
    return await service.list_sub_roles(
        session,
        workspace_id=workspace_id,
        role=role,
        include_inactive=include_inactive,
    )


@router.post("", response_model=schemas.PlayerSubRoleRead)
async def create_player_sub_role(
    data: schemas.PlayerSubRoleCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    await auth._require_workspace_permission(
        user,
        workspace_id=data.workspace_id,
        resource="player",
        action="create",
    )
    return await service.create_sub_role(session, data)


@router.patch("/{sub_role_id}", response_model=schemas.PlayerSubRoleRead)
async def update_player_sub_role(
    sub_role_id: int,
    data: schemas.PlayerSubRoleUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_player_sub_role_permission("player", "update")),
):
    return await service.update_sub_role(session, sub_role_id, data)


@router.delete("/{sub_role_id}", status_code=204)
async def delete_player_sub_role(
    sub_role_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_player_sub_role_permission("player", "delete")),
):
    await service.deactivate_sub_role(session, sub_role_id)
