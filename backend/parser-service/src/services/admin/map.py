"""Admin service layer for map CRUD operations"""

import sqlalchemy as sa
from fastapi import HTTPException, status
from shared.repository import GamemodeRepository, MapRepository
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models
from src.schemas import MapRead
from src.schemas.admin import map as admin_schemas

_gamemode_repo = GamemodeRepository()
_map_repo = MapRepository()


async def get_maps(session: AsyncSession, params: admin_schemas.MapListParams) -> dict:
    """Get paginated list of maps"""
    filters: list[sa.ColumnElement[bool]] = []
    if params.search:
        search_term = f"%{params.search}%"
        filters.append(models.Map.name.ilike(search_term))

    if params.gamemode_id is not None:
        filters.append(models.Map.gamemode_id == params.gamemode_id)

    maps, total = await _map_repo.list(
        session,
        params,
        filters=filters,
        options=[selectinload(models.Map.gamemode)],
    )

    return {
        "results": [MapRead.model_validate(map_obj, from_attributes=True) for map_obj in maps],
        "total": total,
        "page": params.page,
        "per_page": params.per_page,
    }


async def create_map(session: AsyncSession, data: admin_schemas.MapCreate) -> models.Map:
    """Create a new map"""
    gamemode = await _gamemode_repo.get(session, data.gamemode_id)

    if not gamemode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gamemode not found")

    existing_map = await _map_repo.get_by_name(session, data.name)

    if existing_map:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Map with name '{data.name}' already exists",
        )

    map_obj = models.Map(name=data.name, gamemode_id=data.gamemode_id)

    await _map_repo.create(session, map_obj)
    await session.commit()
    await session.refresh(map_obj, ["gamemode"])

    return map_obj


async def update_map(session: AsyncSession, map_id: int, data: admin_schemas.MapUpdate) -> models.Map:
    """Update map fields"""
    map_obj = await _map_repo.get_with_gamemode(session, map_id)

    if not map_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")

    if data.gamemode_id:
        gamemode = await _gamemode_repo.get(session, data.gamemode_id)

        if not gamemode:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gamemode not found",
            )

    if data.name and data.name != map_obj.name:
        existing_map = await _map_repo.get_by_name(session, data.name)

        if existing_map:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Map with name '{data.name}' already exists",
            )

    update_data = data.model_dump(exclude_unset=True)
    await _map_repo.update_fields(session, map_obj, update_data)
    await session.commit()
    await session.refresh(map_obj, ["gamemode"])

    return map_obj


async def delete_map(session: AsyncSession, map_id: int) -> None:
    """Delete map"""
    map_obj = await _map_repo.get(session, map_id)

    if not map_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")

    await _map_repo.delete(session, map_obj)
    await session.commit()
