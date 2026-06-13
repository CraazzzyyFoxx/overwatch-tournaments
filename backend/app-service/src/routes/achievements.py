import typing

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src import schemas
from src.core import config, db, enums, errors, pagination
from src.core.workspace import WorkspaceQuery
from src.services.achievements import flows_v2 as achievements_flows

router = APIRouter(prefix="/achievements", tags=[enums.RouteTag.ACHIEVEMENTS])


@router.get(
    path="",
    response_model=pagination.Paginated[schemas.AchievementRead],
    description="Retrieve a paginated list of achievements. "
    "Supports search and filtering. "
    "Supports fetching additional related entities. "
    "Available entities: **hero**. ",
    summary="Get all achievements",
)
async def get_all(
    session: AsyncSession = Depends(db.get_async_session),
    params: pagination.PaginationSortQueryParams[
        typing.Literal["id", "name", "slug", "rarity", "similarity:name", "similarity:slug"]
    ] = Depends(),
    workspace_id: WorkspaceQuery = None,
):
    return await achievements_flows.get_all(session, pagination.PaginationSortParams.from_query_params(params), workspace_id=workspace_id)


@router.get(
    path="/{id}",
    response_model=schemas.AchievementRead,
    description="Retrieve details of a specific achievement by its ID. "
    "Supports fetching additional related entities."
    "Available entities: **hero**. "
    f"Cache TTL: {config.settings.achievements_cache_ttl / 60} minutes.",
    summary="Get achievement by ID",
)
async def get(
    id: int,
    entities: list[str] = Query([]),
    session: AsyncSession = Depends(db.get_async_session),
):
    return await achievements_flows.get(session, id, entities)


@router.get(
    path="/{id}/users",
    response_model=pagination.Paginated[schemas.AchievementEarned],
    description="Retrieve all users who have earned a specific achievement by its ID. Supports pagination.",
    summary="Get users who earned an achievement",
)
async def get_users_achievement(
    id: int,
    params: pagination.PaginationQueryParams = Depends(),
    session: AsyncSession = Depends(db.get_async_session),
):
    return await achievements_flows.get_achievement_users(
        session, id, pagination.PaginationParams.from_query_params(params)
    )


@router.get(
    path="/user/{user_id}",
    response_model=list[schemas.UserAchievementRead],
    description=""
    "Retrieve all achievements associated with a specific user by their user ID. "
    "Supports fetching additional related entities."
    "Available entities: **hero, tournaments**. "
    f"Cache TTL: {config.settings.achievements_cache_ttl / 60} minutes.",
    summary="Get user achievements",
)
async def get_user_achievements(
    user_id: int,
    entities: list[str] = Query([]),
    tournament_id: int | None = Query(None),
    without_tournament: bool = Query(False),
    include_locked: bool = Query(False),
    workspace_id: WorkspaceQuery = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    if tournament_id is not None and without_tournament:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="invalid_request",
                    msg="Use either tournament_id or without_tournament=true, not both.",
                )
            ],
        )

    return await achievements_flows.get_user_achievements(
        session,
        user_id,
        entities,
        tournament_id=tournament_id,
        without_tournament=without_tournament,
        workspace_id=workspace_id,
        include_locked=include_locked,
    )
