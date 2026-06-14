import typing
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.requests import Request

from src import schemas, models
from src.core import config, db, enums, pagination, auth
from src.core.workspace import WorkspaceQuery

from src.services.analytics_read import flows as analytics_flows

router = APIRouter(prefix="/analytics", tags=[enums.RouteTag.ANALYTICS])


@router.get(
    path="/algorithms/{id}",
    response_model=schemas.AnalyticsAlgorithmRead,
    description="Retrieve details of a specific analytics algorithm by its ID.",
    summary="Get analytics algorithm by ID",
)
async def get_one(
    id: int,
    session=Depends(db.get_async_session),
):
    return await analytics_flows.get_algorithm(session, id)


@router.get(
    path="/algorithms",
    response_model=pagination.Paginated[schemas.AnalyticsAlgorithmRead],
    description="Retrieve a paginated list of algorithms.",
    summary="Get all algorithms",
)
async def get_all_tournaments(
    params: pagination.PaginationQueryParams = Depends(),
    tournament_id: int | None = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    return await analytics_flows.get_algorithms(
        session,
        pagination.PaginationParams.from_query_params(params),
        tournament_id=tournament_id,
    )


@router.get(
    path="",
    response_model=schemas.TournamentAnalytics,
    description=f"Retrieve analytics for tournaments. **Cache TTL: {config.settings.tournaments_cache_ttl / 60} minutes.**",
    summary="Get tournament analytics",
)
async def get_analytics(
    request: Request,
    tournament_id: int,
    algorithm: int,
    start_tournament_id: int | None = None,
    end_tournament_id: int | None = None,
    workspace_id: WorkspaceQuery = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    return await analytics_flows.get_analytics(
        session,
        tournament_id,
        algorithm,
        workspace_id=workspace_id,
    )


@router.post(
    path="/shift",
    response_model=schemas.PlayerAnalytics,
    description="Changes shift for a player in a tournament.",
    summary="Change player shift",
)
async def change_shift(
    data: schemas.PlayerShiftUpdate,
    current_user: models.AuthUser = Depends(auth.require_permission("analytics", "update")),
    session: AsyncSession = Depends(db.get_async_session),
):
    return await analytics_flows.change_shift(session, data.player_id, data.shift)


@router.get(
    path="/streaks",
    response_model=typing.Sequence[schemas.PlayerStreak],
    description="Retrieve player streaks for a tournament.",
    summary="Get player streaks",
)
async def get_streaks(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
):
    return await analytics_flows.get_streaks(session, tournament_id)


# ---------------------------------------------------------------------------
# Balance quality snapshot endpoint
# ---------------------------------------------------------------------------


class BalancePlayerSnapshotRead(BaseModel):
    user_id: int | None = None
    team_id: int | None = None
    assigned_role: str
    preferred_role: str | None = None
    assigned_rank: int
    discomfort: int = 0
    division_number: int | None = None
    is_captain: bool = False
    was_off_role: bool = False


class BalanceQualityRead(BaseModel):
    tournament_id: int
    algorithm: str
    division_scope: str | None = None
    team_count: int
    player_count: int
    avg_sr_overall: float
    sr_std_dev: float
    sr_range: float
    total_discomfort: int
    off_role_count: int
    objective_score: float | None = None
    players: list[BalancePlayerSnapshotRead]


@router.get(
    path="/balance-quality",
    response_model=BalanceQualityRead | None,
    description="Retrieve balance quality snapshot for a tournament.",
    summary="Get balance quality metrics",
)
async def get_balance_quality(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
):
    result = await session.execute(
        sa.select(models.AnalyticsBalanceSnapshot)
        .where(models.AnalyticsBalanceSnapshot.tournament_id == tournament_id)
        .options(selectinload(models.AnalyticsBalanceSnapshot.players))
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        return None

    return BalanceQualityRead(
        tournament_id=snapshot.tournament_id,
        algorithm=snapshot.algorithm,
        division_scope=snapshot.division_scope,
        team_count=snapshot.team_count,
        player_count=snapshot.player_count,
        avg_sr_overall=snapshot.avg_sr_overall,
        sr_std_dev=snapshot.sr_std_dev,
        sr_range=snapshot.sr_range,
        total_discomfort=snapshot.total_discomfort,
        off_role_count=snapshot.off_role_count,
        objective_score=snapshot.objective_score,
        players=[
            BalancePlayerSnapshotRead(
                user_id=p.user_id,
                team_id=p.team_id,
                assigned_role=p.assigned_role,
                preferred_role=p.preferred_role,
                assigned_rank=p.assigned_rank,
                discomfort=p.discomfort,
                division_number=p.division_number,
                is_captain=p.is_captain,
                was_off_role=p.was_off_role,
            )
            for p in snapshot.players
        ],
    )
