import typing

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import auth, config, db, enums, pagination
from src.core.workspace import WorkspaceQuery
from src.services.encounter import flows as encounter_flows

router = APIRouter(prefix="/encounters", tags=[enums.RouteTag.ENCOUNTER])


@router.get(
    path="",
    response_model=pagination.Paginated[schemas.EncounterRead],
    response_model_exclude_none=True,
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
            "best_of",
            "scheduled_at",
            "started_at",
            "ended_at",
            "updated_at",
        ]
    ] = Depends(),
    current_user: models.AuthUser | None = Depends(auth.get_current_user_optional),
):
    return await encounter_flows.get_all_encounters(
        session,
        schemas.EncounterSearchParams.from_query_params(params),
        workspace_id=workspace_id,
        viewer_auth_user_id=current_user.id if current_user is not None else None,
    )


@router.get(
    path="/overview",
    response_model=schemas.EncounterOverviewRead,
    response_model_exclude_none=True,
    summary="Get encounters overview metrics",
)
async def get_encounters_overview(
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
            "best_of",
            "scheduled_at",
            "started_at",
            "ended_at",
            "updated_at",
        ]
    ] = Depends(),
    current_user: models.AuthUser | None = Depends(auth.get_current_user_optional),
):
    return await encounter_flows.get_encounters_overview(
        session,
        schemas.EncounterSearchParams.from_query_params(params),
        workspace_id=workspace_id,
        viewer_auth_user_id=current_user.id if current_user is not None else None,
    )


@router.get(
    path="/views",
    response_model=list[schemas.EncounterSavedViewRead],
    response_model_exclude_none=True,
    summary="Get saved encounter views",
)
async def get_saved_views(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    return await encounter_flows.get_saved_views(session, workspace_id=workspace_id, auth_user_id=user.id)


@router.post(
    path="/views",
    response_model=schemas.EncounterSavedViewRead,
    response_model_exclude_none=True,
    summary="Save an encounter view",
)
async def save_view(
    data: schemas.EncounterSavedViewCreate,
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    return await encounter_flows.save_view(
        session,
        workspace_id=workspace_id,
        auth_user_id=user.id,
        data=data,
    )


@router.delete(
    path="/views/{saved_view_id}",
    status_code=204,
    summary="Delete a saved encounter view",
)
async def delete_view(
    saved_view_id: int,
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    await encounter_flows.delete_saved_view(
        session,
        workspace_id=workspace_id,
        auth_user_id=user.id,
        saved_view_id=saved_view_id,
    )


@router.get(
    path="/{id}",
    response_model=schemas.EncounterRead,
    response_model_exclude_none=True,
    description="Retrieve details of a specific encounter by its ID. "
    "Supports fetching additional related entities. "
    f"**Cache TTL: {config.settings.encounters_cache_ttl / 60} minutes.**",
    summary="Get encounter by ID",
)
async def get_one(
    id: int,
    session: AsyncSession = Depends(db.get_async_session),
    entities: list[str] = Query([]),
):
    return await encounter_flows.get_encounter(session, id, entities)
