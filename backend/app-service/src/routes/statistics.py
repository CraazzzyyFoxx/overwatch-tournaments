import typing

from fastapi import APIRouter, Depends

from src import schemas
from src.core import db, enums, pagination
from src.core.workspace import WorkspaceQuery

from src.services.dashboard import flows as dashboard_flows
from src.services.statistics import flows as statistics_flows

router = APIRouter(prefix="/statistics", tags=[enums.RouteTag.STATISTICS])


@router.get(
    path="/dashboard",
    response_model=schemas.DashboardStats,
    description="Retrieve aggregated dashboard statistics: entity counts, issue counts, "
    "and active tournament encounter stats. All computed server-side in a single request.",
    summary="Get admin dashboard stats",
)
async def get_dashboard_stats(
    workspace_id: WorkspaceQuery = None,
    session=Depends(db.get_async_session),
):
    return await dashboard_flows.get_dashboard_stats(session, workspace_id=workspace_id)


@router.get(
    path="/champion",
    response_model=pagination.Paginated[schemas.PlayerStatistics],
    description="Retrieve a paginated list of players based on champion statistics. Supports sorting. ",
    summary="Get champion statistics",
)
async def get_most_champions(
    params: pagination.PaginationSortQueryParams[
        typing.Literal["id", "name", "value"]
    ] = Depends(),
    workspace_id: WorkspaceQuery = None,
    session=Depends(db.get_async_session),
):
    return await statistics_flows.get_most_champions(
        session, pagination.PaginationSortParams.from_query_params(params),
        workspace_id=workspace_id,
    )


@router.get(
    path="/winrate",
    response_model=pagination.Paginated[schemas.PlayerStatistics],
    description="Retrieve a paginated list of players based on win rate statistics. Supports sorting. ",
    summary="Get win rate statistics",
)
async def get_player_winrate(
    params: pagination.PaginationSortQueryParams[
        typing.Literal["id", "name", "value"]
    ] = Depends(),
    workspace_id: WorkspaceQuery = None,
    session=Depends(db.get_async_session),
):
    return await statistics_flows.get_to_winrate_players(
        session, pagination.PaginationSortParams.from_query_params(params),
        workspace_id=workspace_id,
    )


@router.get(
    path="/won-maps",
    response_model=pagination.Paginated[schemas.PlayerStatistics],
    description="Retrieve a paginated list of players based on won maps statistics. Supports sorting. ",
    summary="Get won maps statistics",
)
async def get_top_won_maps_players(
    params: pagination.PaginationSortQueryParams[
        typing.Literal["id", "name", "value"]
    ] = Depends(),
    workspace_id: WorkspaceQuery = None,
    session=Depends(db.get_async_session),
):
    return await statistics_flows.get_to_won_players(
        session, pagination.PaginationSortParams.from_query_params(params),
        workspace_id=workspace_id,
    )
