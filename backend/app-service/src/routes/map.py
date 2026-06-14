import typing

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src import models, schemas
from src.core import config, db, enums, pagination

from src.services.map import flows as map_flows

router = APIRouter(prefix="/maps", tags=[enums.RouteTag.MAP])


@router.get(
    path="/lookup",
    response_model=list[schemas.LookupItem],
    description="Lightweight endpoint returning only id and name for dropdowns/selectors.",
    summary="Lookup maps",
)
async def lookup_maps(
    session: AsyncSession = Depends(db.get_async_session),
) -> list[schemas.LookupItem]:
    query = sa.select(models.Map.id, models.Map.name).order_by(models.Map.name)
    result = await session.execute(query)
    return [schemas.LookupItem(id=row.id, name=row.name) for row in result.all()]


@router.get(
    path="",
    response_model=pagination.Paginated[schemas.MapRead],
    description="Retrieve a list of maps with pagination. "
    "Available entities: **gamemode**. ",
    summary="Get all maps",
)
async def get_all(
    params: pagination.PaginationSortSearchQueryParams[
        typing.Literal["id", "gamemode_id", "name", "similarity:name"]
    ] = Depends(),
    session=Depends(db.get_async_session),
):
    return await map_flows.get_all(
        session, pagination.PaginationSortSearchParams.from_query_params(params)
    )


@router.get(
    path="/{id}",
    response_model=schemas.MapRead,
    description="Retrieve a map by its ID. "
    "Available entities: **gamemode**. "
    "**Cache TTL: 24 hours.**",
    summary="Get map by ID",
)
async def get_by_id(
    request: Request,
    id: int,
    session=Depends(db.get_async_session),
    entities: list[str] = Query([]),
):
    return await map_flows.get(session, id, entities)
