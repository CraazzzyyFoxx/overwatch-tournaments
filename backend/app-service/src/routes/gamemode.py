import typing

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config, db, enums, pagination
from src.services.gamemode import flows as gamemode_flows

router = APIRouter(prefix="/gamemodes", tags=[enums.RouteTag.GAMEMODE])


@router.get(
    path="/lookup",
    response_model=list[schemas.LookupItem],
    description="Lightweight endpoint returning only id and name for dropdowns/selectors.",
    summary="Lookup gamemodes",
)
async def lookup_gamemodes(
    session: AsyncSession = Depends(db.get_async_session),
) -> list[schemas.LookupItem]:
    query = sa.select(models.Gamemode.id, models.Gamemode.name).order_by(models.Gamemode.name)
    result = await session.execute(query)
    return [schemas.LookupItem(id=row.id, name=row.name) for row in result.all()]


@router.get(
    path="",
    response_model=pagination.Paginated[schemas.GamemodeRead],
    description="Retrieve a paginated list of all gamemodes. Supports search and filtering.",
    summary="Get all gamemodes",
)
async def get_all(
    session: AsyncSession = Depends(db.get_async_session),
    params: pagination.PaginationSortSearchQueryParams[
        typing.Literal["id", "name", "slug", "similarity:name", "similarity:slug"]
    ] = Depends(),
):
    return await gamemode_flows.get_all(
        session, pagination.PaginationSortSearchParams.from_query_params(params)
    )


@router.get(
    path="/{id}",
    response_model=schemas.GamemodeRead,
    description=f"Retrieve details of a specific gamemode by its ID. **Cache TTL:** {config.settings.gamemodes_cache_ttl} minutes.",
    summary="Get gamemode by ID",
)
async def get(
    id: int,
    entities: list[str] = Query([]),
    session: AsyncSession = Depends(db.get_async_session),
):
    return await gamemode_flows.get(session, id, entities)
