
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from shared.services.division_grid_access import build_workspace_division_grid_normalizer
from shared.services.division_grid_normalization import DivisionGridNormalizationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.requests import Request

from src import models, schemas
from src.core import config, db, enums, pagination
from src.core.workspace import WorkspaceQuery, get_division_grid
from src.services.standings import flows as standings_flows
from src.services.tournament import flows as tournament_flows

router = APIRouter(prefix="/tournaments", tags=[enums.RouteTag.TOURNAMENT])


@router.get(
    path="/lookup",
    response_model=list[schemas.LookupItem],
    description="Lightweight endpoint returning only id and name for dropdowns/selectors.",
    summary="Lookup tournaments",
)
async def lookup_tournaments(
    workspace_id: WorkspaceQuery = None,
    is_league: bool | None = None,
    session: AsyncSession = Depends(db.get_async_session),
) -> list[schemas.LookupItem]:
    query = sa.select(models.Tournament.id, models.Tournament.name).order_by(models.Tournament.id.desc()).limit(500)
    if workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == workspace_id)
    if is_league is not None:
        query = query.where(models.Tournament.is_league.is_(is_league))
    result = await session.execute(query)
    return [schemas.LookupItem(id=row.id, name=row.name) for row in result.all()]


@router.get(
    path="/{id}",
    response_model=schemas.TournamentRead,
    description="Retrieve details of a specific tournament by its ID. "
    "Supports fetching additional related entities. "
    "Available entities: **stages**."
    f"**Cache TTL: {config.settings.tournaments_cache_ttl / 60} minutes.**",
    summary="Get tournament by ID",
)
async def get_one(
    request: Request,
    id: int,
    entities: list[str] = Query([]),
    session=Depends(db.get_async_session),
):
    return await tournament_flows.get_read(session, id, entities)


@router.get(
    path="/{id}/stages",
    response_model=list[schemas.StageRead],
    description="Retrieve stages for a tournament with items and inputs.",
    summary="Get tournament stages",
)
async def get_stages(
    id: int,
    session: AsyncSession = Depends(db.get_async_session),
):
    result = await session.execute(
        sa.select(models.Stage)
        .where(models.Stage.tournament_id == id)
        .options(
            selectinload(models.Stage.items)
            .selectinload(models.StageItem.inputs)
        )
        .order_by(models.Stage.order)
    )
    stages = result.scalars().all()
    return [schemas.StageRead.model_validate(s, from_attributes=True) for s in stages]


@router.get(
    path="/{id}/standings",
    response_model=list[schemas.StandingRead],
    description="Retrieve standings for a specific tournament by its ID. "
    "Supports fetching additional related entities. "
    "Available entities: **tournament**, **group**, **team**."
    f"**Cache TTL: {config.settings.tournaments_cache_ttl / 60} minutes.**",
    summary="Get tournament standings by ID",
)
async def get_standings(
    request: Request,
    id: int,
    entities: list[str] = Query([]),
    session: AsyncSession = Depends(db.get_async_session),
):
    tournament = await tournament_flows.get(session, id, [])
    return await standings_flows.get_by_tournament(session, tournament, entities)


@router.get(
    path="",
    response_model=pagination.Paginated[schemas.TournamentRead],
    description="Retrieve a paginated list of tournaments. Supports search and filtering. Available entities: **stages**.",
    summary="Get all tournaments",
)
async def get_all_tournaments(
    params: schemas.TournamentPaginationSortSearchQueryParams = Depends(),
    session: AsyncSession = Depends(db.get_async_session),
):
    return await tournament_flows.get_all(
        session, schemas.TournamentPaginationSortSearchParams.from_query_params(params)
    )


@router.get(
    path="/statistics/history",
    response_model=list[schemas.TournamentStatistics],
    description=f"Retrieve historical statistics for tournaments. \n **Cache TTL: {config.settings.tournaments_cache_ttl / 60} minutes.**",
    summary="Get tournament statistics (players, closeness, team price) history",
)
async def get_statistics(
    workspace_id: WorkspaceQuery = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    return await tournament_flows.get_history_tournaments(session, workspace_id=workspace_id)


@router.get(
    path="/statistics/division",
    response_model=list[schemas.DivisionStatistics],
    description=f"Retrieve division-based statistics for tournaments. **Cache TTL: {config.settings.tournaments_cache_ttl / 60} minutes.**",
    summary="Get division statistics",
)
async def get_avg_div(
    workspace_id: WorkspaceQuery = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    fallback_grid = await get_division_grid(session, workspace_id)
    normalizer = None
    if workspace_id is not None:
        try:
            normalizer = await build_workspace_division_grid_normalizer(
                session,
                workspace_id,
                require_complete=False,
            )
        except DivisionGridNormalizationError:
            pass  # Fall back to global grid for all tournaments
    return await tournament_flows.get_avg_divisions_tournaments(
        session,
        workspace_id=workspace_id,
        normalizer=normalizer,
        fallback_grid=fallback_grid,
    )


@router.get(
    path="/statistics/overall",
    response_model=schemas.OverallStatistics,
    description=f"Retrieve overall tournament statistics. Cache TTL: {config.settings.tournaments_cache_ttl / 60} minutes.",
    summary="Get overall tournament statistics",
)
async def get_most_players(
    workspace_id: WorkspaceQuery = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    return await tournament_flows.get_tournaments_overall(session, workspace_id=workspace_id)


@router.get(
    path="/league/seasons",
    response_model=list[str],
    description=f"Retrieve available OWAL seasons. Cache TTL: {config.settings.tournaments_cache_ttl / 60} minutes.",
    summary="Get OWAL seasons",
)
async def get_owal_seasons(
    workspace_id: WorkspaceQuery = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    return await tournament_flows.get_owal_seasons(session, workspace_id=workspace_id)


@router.get(
    path="/league/results",
    response_model=schemas.OwalStandings,
    description="Retrieve OWAL tournament standings.",
    summary="Get OWAL standings",
)
async def get_owal_standings(
    season: str | None = Query(default=None),
    workspace_id: WorkspaceQuery = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    grid = await get_division_grid(session, workspace_id)
    if season:
        return await tournament_flows.get_owal_standings_by_season(
            session, season, workspace_id=workspace_id, grid=grid,
        )
    return await tournament_flows.get_owal_standings(session, workspace_id=workspace_id, grid=grid)


@router.get(
    path="/league/stacks",
    response_model=list[schemas.LeaguePlayerStack],
    description="Retrieve OWAL tournament player stacks.",
    summary="Get OWAL player stacks",
)
async def get_owal_player_stacks(
    season: str | None = Query(default=None),
    workspace_id: WorkspaceQuery = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    if not season:
        seasons = await tournament_flows.get_owal_seasons(session, workspace_id=workspace_id)
        season = seasons[0] if seasons else None

    if not season:
        return []

    return await tournament_flows.get_league_player_stacks(session, season, workspace_id=workspace_id)
