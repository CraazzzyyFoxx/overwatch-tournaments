import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from src import schemas
from src.core.db import async_session_maker

from . import service


async def get_dashboard_stats(
    session: AsyncSession,
    workspace_id: int | None = None,
) -> schemas.DashboardStats:
    counts, issues, active_stats = await _gather(workspace_id)

    active_tournament_stats = None
    if active_stats is not None:
        active_tournament_stats = schemas.DashboardActiveTournamentStats(**active_stats)

    return schemas.DashboardStats(
        **counts,
        active_tournament_stats=active_tournament_stats,
        issues=schemas.DashboardIssues(**issues),
    )


async def _gather(workspace_id: int | None) -> tuple[dict, dict, dict | None]:
    # AsyncSession isn't concurrency-safe for parallel .execute() — spawn
    # independent sessions so the three independent dashboard queries
    # actually run in parallel.
    async def _run_counts() -> dict:
        async with async_session_maker() as s:
            return await service.get_counts(s, workspace_id)

    async def _run_issues() -> dict:
        async with async_session_maker() as s:
            return await service.get_issues(s, workspace_id)

    async def _run_active_stats() -> dict | None:
        async with async_session_maker() as s:
            return await service.get_active_tournament_stats(s, workspace_id)

    return await asyncio.gather(_run_counts(), _run_issues(), _run_active_stats())
