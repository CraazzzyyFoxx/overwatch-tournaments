"""Admin routes for hero CRUD operations"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import auth, db, pagination
from src.schemas.admin import hero as admin_schemas
from src.services.admin import hero as admin_service

router = APIRouter(
    prefix="/heroes",
    tags=["admin", "heroes"],
)


@router.get("", response_model=pagination.Paginated[schemas.HeroRead])
async def get_heroes(
    params: admin_schemas.HeroListQueryParams = Depends(),
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("hero", "read")),
):
    """Get paginated list of heroes (admin only)"""
    heroes_list = await admin_service.get_heroes(
        session,
        admin_schemas.HeroListParams.from_query_params(params),
    )
    return heroes_list


@router.post("", response_model=schemas.HeroRead)
async def create_hero(
    data: admin_schemas.HeroCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("hero", "create")),
):
    """Create a new hero (admin only)"""
    created_hero = await admin_service.create_hero(session, data)
    return schemas.HeroRead.model_validate(created_hero, from_attributes=True)


@router.patch("/{hero_id}", response_model=schemas.HeroRead)
async def update_hero(
    hero_id: int,
    data: admin_schemas.HeroUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("hero", "update")),
):
    """Update hero fields (admin only)"""
    updated_hero = await admin_service.update_hero(session, hero_id, data)
    return schemas.HeroRead.model_validate(updated_hero, from_attributes=True)


@router.delete("/{hero_id}", status_code=204)
async def delete_hero(
    hero_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("hero", "delete")),
):
    """Delete hero (admin only)"""
    await admin_service.delete_hero(session, hero_id)
