import typing

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src import schemas
from src.core import config, db, enums, pagination
from src.core.workspace import WorkspaceQuery

from src.services.encounter import flows as encounter_flows

router = APIRouter(prefix="/matches", tags=[enums.RouteTag.MATCH])


@router.get(
    path="",
    response_model=pagination.Paginated[schemas.MatchRead],
    description="Retrieve a paginated list of matches. Supports search and filtering. Available entities: teams, encounter, map. ",
    summary="Get all matches",
)
async def get_all_matches(
    session: AsyncSession = Depends(db.get_async_session),
    params: schemas.MatchSearchQueryParams[
        typing.Literal[
            "id",
            "home_team_id",
            "away_team_id",
            "home_score",
            "away_score",
            "encounter_id",
            "map_id",
            "log_name",
        ]
    ] = Depends(),
    workspace_id: WorkspaceQuery = None,
):
    return await encounter_flows.get_all_matches(
        session, schemas.MatchSearchParams.from_query_params(params), workspace_id=workspace_id
    )


@router.get(
    path="/{id}",
    response_model=schemas.MatchReadWithStats,
    description="Retrieve details of a specific match by its ID, including associated statistics. "
    f"**Cache TTL: {config.settings.encounters_cache_ttl / 60} minutes.**",
    summary="Get match by ID",
)
async def get_match(
    id: int,
    session: AsyncSession = Depends(db.get_async_session),
    workspace_id: WorkspaceQuery = None,
    entities: list[str] = Query([]),
):
    return await encounter_flows.get_match_with_stats(session, id, entities, workspace_id=workspace_id)
