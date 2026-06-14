"""Admin routes for map CRUD operations"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import auth, db, pagination
from src.schemas.admin import map as admin_schemas
from src.services.admin import map as admin_service

router = APIRouter(
    prefix="/maps",
    tags=["admin", "maps"],
)


@router.get("", response_model=pagination.Paginated[schemas.MapRead])
async def get_maps(
    params: admin_schemas.MapListQueryParams = Depends(),
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("map", "read")),
):
    """Get paginated list of maps (admin only)"""
    maps_list = await admin_service.get_maps(
        session,
        admin_schemas.MapListParams.from_query_params(params),
    )
    return maps_list


@router.post("", response_model=schemas.MapRead)
async def create_map(
    data: admin_schemas.MapCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("map", "create")),
):
    """Create a new map (admin only)"""
    created_map = await admin_service.create_map(session, data)
    return schemas.MapRead.model_validate(created_map, from_attributes=True)


@router.patch("/{map_id}", response_model=schemas.MapRead)
async def update_map(
    map_id: int,
    data: admin_schemas.MapUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("map", "update")),
):
    """Update map fields (admin only)"""
    updated_map = await admin_service.update_map(session, map_id, data)
    return schemas.MapRead.model_validate(updated_map, from_attributes=True)


@router.delete("/{map_id}", status_code=204)
async def delete_map(
    map_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("map", "delete")),
):
    """Delete map (admin only)"""
    await admin_service.delete_map(session, map_id)
