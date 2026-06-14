import typing

from fastapi import APIRouter, Depends, Query

from src import schemas
from src.core import config, db, enums, pagination
from src.core.workspace import WorkspaceQuery
from src.services.team import flows as team_flows

router = APIRouter(prefix="/teams", tags=[enums.RouteTag.TEAMS])


@router.get(
    path="/{id}",
    response_model=schemas.TeamRead,
    response_model_exclude_none=True,
    description="Retrieve details of a specific team by its ID. "
    "Supports fetching additional related entities. "
    "Available entities: tournament, players, captain, placement, group. "
    f"**Cache TTL: {config.settings.teams_cache_ttl / 60} minutes.**",
    summary="Get team by ID",
)
async def get_one(
    id: int,
    entities: list[str] = Query([]),
    session=Depends(db.get_async_session),
):
    return await team_flows.get_read(session, id, entities)


@router.get(
    path="",
    response_model=pagination.Paginated[schemas.TeamRead],
    response_model_exclude_none=True,
    description="Retrieve a paginated list of teams. "
    "Supports search and filtering. "
    "Available entities: tournament, players, captain, placement, group. ",
    summary="Get all teams",
)
async def get_all(
    params: schemas.TeamFilterQueryParams[
        typing.Literal["id", "name", "total_sr", "avg_sr", "placement", "group"]
    ] = Depends(),
    workspace_id: WorkspaceQuery = None,
    session=Depends(db.get_async_session),
):
    return await team_flows.get_all(
        session,
        schemas.TeamFilterParams.from_query_params(params),
        workspace_id=workspace_id,
    )
