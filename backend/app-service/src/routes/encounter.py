import typing

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src import schemas
from src.core import config, db, enums, pagination
from src.core.workspace import WorkspaceQuery
from src.services.encounter import flows as encounter_flows

router = APIRouter(prefix="/encounters", tags=[enums.RouteTag.ENCOUNTER])


@router.get(
    path="",
    response_model=pagination.Paginated[schemas.EncounterRead],
    description="Retrieve a paginated list of encounters. Supports search and filtering. Available entities: teams, matches, tournament_group, tournament. ",
    summary="Get all encounters",
)
async def get_all_encounters(
    session: AsyncSession = Depends(db.get_async_session),
    workspace_id: WorkspaceQuery = None,
    params: schemas.EncounterSearchQueryParams[
        typing.Literal[
            "id",
            "name",
            "home_score",
            "away_score",
            "round",
            "closeness",
            "status",
            "home_team_id",
            "away_team_id",
        ]
    ] = Depends(),
):
    return await encounter_flows.get_all_encounters(
        session, schemas.EncounterSearchParams.from_query_params(params),
        workspace_id=workspace_id,
    )


@router.get(
    path="/{id}",
    response_model=schemas.EncounterRead,
    description="Retrieve details of a specific encounter by its ID. "
    "Supports fetching additional related entities. "
    f"**Cache TTL: {config.settings.encounters_cache_ttl / 60} minutes.**",
    summary="Get encounter by ID",
)
async def get_one(
    id: int,
    session: AsyncSession = Depends(db.get_async_session),
    workspace_id: WorkspaceQuery = None,
    entities: list[str] = Query([]),
):
    return await encounter_flows.get_encounter(session, id, entities, workspace_id=workspace_id)
