import typing

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src import schemas
from src.core import config, db, enums, pagination
from src.core.workspace import (
    WorkspaceContextDep,
    WorkspaceQuery,
    get_division_grid,
)
from src.services.map import flows as map_flows
from src.services.user import flows as user_flows

router = APIRouter(prefix="/users", tags=[enums.RouteTag.USER])


@router.get(
    path="",
    response_model=pagination.Paginated[schemas.UserRead],
    description="Retrieve a list of users based on search parameters. "
    "Available entities: **discord, battle_tag, twitch.**",
    summary="Search for users",
)
async def get_all(
    params: pagination.PaginationSortSearchQueryParams[typing.Literal["id", "name", "similarity:name"]] = Depends(),
    session=Depends(db.get_async_session),
):
    return await user_flows.get_all(session, pagination.PaginationSortSearchParams.from_query_params(params))


@router.get(
    path="/search",
    response_model=list[schemas.UserSearch],
    description="Search for a list of users based on search parameters. ",
    summary="Search for users",
)
async def search_by_name(
    query: str = Query(default=""),
    fields: list[str] = Query([]),
    session=Depends(db.get_async_session),
):
    return await user_flows.search_by_name(session, query, fields)


@router.get(
    path="/overview",
    response_model=pagination.Paginated[schemas.UserOverviewRow],
    description="Retrieve an enriched, paginated list of users for frontend list views. "
    "Includes role divisions, top heroes with key metrics, tournaments/achievements counts and average results.",
    summary="Get users overview",
)
async def get_overview(
    ws: WorkspaceContextDep,
    params: schemas.UserOverviewQueryParams = Depends(),
    session: AsyncSession = Depends(db.get_async_session),
):
    return await user_flows.get_overview(
        session,
        schemas.UserOverviewParams.from_query_params(params),
        workspace_id=ws.id,
        grid=ws.grid,
        normalizer=ws.normalizer,
    )


@router.get(
    path="/overview/stats",
    response_model=schemas.UserOverviewStats,
    description="Aggregated KPI numbers (total players, players with logs, "
    "average tournaments/player, active in last 30 days, role counts) for the users hero header. "
    "Respects the same role/division/search filters as the main overview list.",
    summary="Get users overview KPI stats",
)
async def get_overview_stats(
    ws: WorkspaceContextDep,
    params: schemas.UserOverviewStatsQueryParams = Depends(),
    session: AsyncSession = Depends(db.get_async_session),
):
    return await user_flows.get_overview_stats(session, params, grid=ws.grid)


@router.get(
    path="/overview/catalog",
    response_model=schemas.UserCatalogResponse,
    description="Alphabetised catalog of users for the catalog view. Groups players "
    "by the first letter of their name (A-Z, plus '#' for non-alpha). "
    "Optional `letter` returns a single bucket; `per_letter` caps the number of "
    "cards per letter. Same role/division/query filters as the overview list.",
    summary="Get users alphabetical catalog",
)
async def get_overview_catalog(
    ws: WorkspaceContextDep,
    params: schemas.UserCatalogQueryParams = Depends(),
    session: AsyncSession = Depends(db.get_async_session),
):
    return await user_flows.get_catalog(
        session,
        schemas.UserCatalogParams.from_query_params(params),
        grid=ws.grid,
        normalizer=ws.normalizer,
    )


@router.get(
    path="/{id}/compare",
    response_model=schemas.UserCompareResponse,
    description="Compare one user against another user, global averages, or a rank cohort.",
    summary="Compare user overview metrics",
)
async def get_compare(
    id: int,
    params: schemas.UserCompareQueryParams = Depends(),
    session: AsyncSession = Depends(db.get_async_session),
):
    grid = await get_division_grid(session, None)
    return await user_flows.get_compare(session, id, schemas.UserCompareParams.from_query_params(params), grid=grid)


@router.get(
    path="/{id}/compare/heroes",
    response_model=schemas.UserHeroCompareResponse,
    description="Compare hero-level average per-10 metrics against a target user, global baseline, or role/division cohort, with optional map filter.",
    summary="Compare users by heroes",
)
async def get_hero_compare(
    id: int,
    params: schemas.UserHeroCompareQueryParams = Depends(),
    session: AsyncSession = Depends(db.get_async_session),
):
    grid = await get_division_grid(session, None)
    return await user_flows.get_hero_compare(session, id, schemas.UserHeroCompareParams.from_query_params(params), grid=grid)


@router.get(
    path="/{name}",
    response_model=schemas.UserRead,
    description="Search for a given player by using its discord or BattleTag (with # replaced by -). "
    "If you don't find the player by using the name, please try with the BattleTag. "
    "You should be able to find the associated player_id to use in order to request career data. "
    "Available entities: **discord, battle_tag, twitch."
    f"Cache TTL: {config.settings.users_cache_ttl / 60} minutes.**",
    summary="Get user by name",
)
async def get_by_name(
    name: str,
    session: AsyncSession = Depends(db.get_async_session),
    entities: list[str] = Query([]),
):
    name = name.replace("-", "#")
    if "#" in name:
        user = await user_flows.get_by_battle_tag(session, name, entities)
    else:
        user = await user_flows.get_by_discord(session, name, entities)
    return user


@router.get(
    path="/{id}/profile",
    response_model=schemas.UserProfile,
    description=f"Retrieve the profile information of a user by ID. **Cache TTL: {config.settings.users_cache_ttl / 60} minutes.**",
    summary="Get user profile",
)
async def get_profile(
    id: int,
    ws: WorkspaceContextDep,
    session=Depends(db.get_async_session),
):
    return await user_flows.get_profile(session, id, workspace_id=ws.id, grid=ws.grid)


@router.get(
    path="/{id}/tournaments",
    response_model=list[schemas.UserTournament],
    description=f"Retrieve the list of tournaments associated with a user by ID. **Cache TTL: {config.settings.users_cache_ttl / 60} minutes.**",
    summary="Get user tournaments",
)
async def get_tournaments(
    id: int,
    ws: WorkspaceContextDep,
    session: AsyncSession = Depends(db.get_async_session),
):
    return await user_flows.get_tournaments(session, id, workspace_id=ws.id, grid=ws.grid)


@router.get(
    path="/{id}/tournaments/{tournament_id}",
    response_model=schemas.UserTournamentWithStats,
    description=f"Retrieve detailed statistics for a specific tournament associated with a user. **Cache TTL: {config.settings.users_cache_ttl / 60} minutes.**",
    summary="Get user tournament details",
)
async def get_tournament(
    id: int,
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
):
    grid = await get_division_grid(session, None, tournament_id)
    tournament = await user_flows.get_tournament_with_stats(session, id, tournament_id, grid=grid)
    return tournament


@router.get(
    path="/{id}/maps",
    response_model=pagination.Paginated[schemas.UserMap],
    description=f"Retrieve the most played maps for a user by ID, with pagination and filtering. "
    f"Supports search (`query`) and minimum sample size (`min_count`). "
    f"Available entities: **gamemode, heroes, hero_stats**. "
    f"**Cache TTL: {config.settings.users_cache_ttl / 60} minutes.**",
    summary="Get user maps",
)
async def get_maps(
    id: int,
    session: AsyncSession = Depends(db.get_async_session),
    params: schemas.UserMapsSearchQueryParams[
        typing.Literal[
            "id",
            "count",
            "win",
            "loss",
            "draw",
            "winrate",
            "gamemode_id",
            "slug",
            "name",
        ]
    ] = Depends(),
    workspace_id: WorkspaceQuery = None,
):
    maps = await map_flows.get_top_user(session, id, schemas.UserMapsSearchParams.from_query_params(params), workspace_id=workspace_id)
    return maps


@router.get(
    path="/{id}/maps/summary",
    response_model=schemas.UserMapsSummary,
    description=f"Retrieve a summary (highlights and totals) for a user's maps. "
    f"Uses the same filters as `/users/{{id}}/maps` but always evaluates the full dataset. "
    f"Heavy entities like hero stats are ignored. "
    f"**Cache TTL: {config.settings.users_cache_ttl / 60} minutes.**",
    summary="Get user maps summary",
)
async def get_maps_summary(
    id: int,
    session: AsyncSession = Depends(db.get_async_session),
    params: schemas.UserMapsSearchQueryParams[
        typing.Literal[
            "id",
            "count",
            "win",
            "loss",
            "draw",
            "winrate",
            "gamemode_id",
            "slug",
            "name",
        ]
    ] = Depends(),
    workspace_id: WorkspaceQuery = None,
):
    summary = await map_flows.get_top_user_summary(session, id, schemas.UserMapsSearchParams.from_query_params(params), workspace_id=workspace_id)
    return summary


@router.get(
    path="/{id}/encounters",
    response_model=pagination.Paginated[schemas.EncounterReadWithUserStats],
    description=f"Retrieve the encounters data for a user by ID, with pagination. **Cache TTL: {config.settings.users_cache_ttl / 60} minutes.**",
    summary="Get user encounters",
)
async def get_encounters(
    id: int,
    session: AsyncSession = Depends(db.get_async_session),
    params: pagination.PaginationSortQueryParams[
        typing.Literal["id", "name", "home_team_id", "away_team_id", "closeness", "round"]
    ] = Depends(),
    result: typing.Literal["win", "loss", "draw"] | None = Query(None),
    stage: typing.Literal["group", "playoffs", "finals"] | None = Query(None),
    mvp1: bool = Query(False),
    has_logs: bool | None = Query(None),
    opponent: str | None = Query(None),
    workspace_id: WorkspaceQuery = None,
):
    encounters = await user_flows.get_encounters_by_user(
        session,
        id,
        pagination.PaginationSortParams.from_query_params(params),
        workspace_id=workspace_id,
        result=result,
        stage=stage,
        mvp1=mvp1,
        has_logs=has_logs,
        opponent=opponent,
    )
    return encounters


@router.get(
    path="/{id}/heroes",
    response_model=pagination.Paginated[schemas.HeroWithUserStats],
    description="Retrieve the list of heroes associated with a user by ID, along with their stats."
    f"**Cache TTL: {config.settings.users_cache_ttl / 60} minutes.**",
    summary="Get user heroes",
)
async def get_heroes(
    id: int,
    params: pagination.PaginationQueryParams = Depends(),
    stats: list[enums.LogStatsName] = Query([]),
    tournament_id: int | None = Query(default=None, ge=1),
    workspace_id: WorkspaceQuery = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    heroes = await user_flows.get_heroes(
        session,
        id,
        pagination.PaginationParams.from_query_params(params),
        stats,
        tournament_id=tournament_id,
        workspace_id=workspace_id,
    )
    return heroes


@router.get(
    path="/{id}/teammates",
    response_model=pagination.Paginated[schemas.UserBestTeammate],
    description=f"Retrieve the list of teammates associated with a user by ID. **Cache TTL: {config.settings.users_cache_ttl / 60} minutes.**",
    summary="Get user best teammates",
)
async def get_teammates(
    id: int,
    params: pagination.PaginationSortQueryParams[typing.Literal["id", "name", "winrate", "tournaments"]] = Depends(),
    workspace_id: WorkspaceQuery = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    teammates = await user_flows.get_best_teammates(
        session, id, pagination.PaginationSortParams.from_query_params(params), workspace_id=workspace_id
    )
    return teammates
