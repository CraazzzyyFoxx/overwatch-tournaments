"""Admin routes for gamemode CRUD operations"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import auth, db, pagination
from src.schemas.admin import gamemode as admin_schemas
from src.services.admin import gamemode as admin_service

router = APIRouter(
    prefix="/gamemodes",
    tags=["admin", "gamemodes"],
)


@router.get("", response_model=pagination.Paginated[schemas.GamemodeRead])
async def get_gamemodes(
    params: admin_schemas.GamemodeListQueryParams = Depends(),
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("gamemode", "read")),
):
    """Get paginated list of gamemodes (admin only)"""
    gamemodes_list = await admin_service.get_gamemodes(
        session,
        admin_schemas.GamemodeListParams.from_query_params(params),
    )
    return gamemodes_list


@router.post("", response_model=schemas.GamemodeRead)
async def create_gamemode(
    data: admin_schemas.GamemodeCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("gamemode", "create")),
):
    """Create a new gamemode (admin only)"""
    created_gamemode = await admin_service.create_gamemode(session, data)
    return schemas.GamemodeRead.model_validate(created_gamemode, from_attributes=True)


@router.patch("/{gamemode_id}", response_model=schemas.GamemodeRead)
async def update_gamemode(
    gamemode_id: int,
    data: admin_schemas.GamemodeUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("gamemode", "update")),
):
    """Update gamemode fields (admin only)"""
    updated_gamemode = await admin_service.update_gamemode(session, gamemode_id, data)
    return schemas.GamemodeRead.model_validate(updated_gamemode, from_attributes=True)


@router.delete("/{gamemode_id}", status_code=204)
async def delete_gamemode(
    gamemode_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("gamemode", "delete")),
):
    """Delete gamemode (admin only)"""
    await admin_service.delete_gamemode(session, gamemode_id)
