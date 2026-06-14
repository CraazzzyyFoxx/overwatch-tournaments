"""div_change / div_level — division-related conditions.

Grain: user_tournament (user_id, tournament_id).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS


@register("div_level")
async def execute_div_level(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Player's division (computed from rank via grid) meets threshold."""
    op = params["op"]
    value = params["value"]

    if context.grid is None and context.normalizer is None:
        return set()

    op_fn = OPERATORS[op]

    query = (
        sa.select(
            models.Player.user_id,
            models.Player.tournament_id,
            models.Player.rank,
            models.Tournament.division_grid_version_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
        )
    )

    if context.tournament:
        query = query.where(models.Player.tournament_id == context.tournament.id)

    result = await session.execute(query)
    results: ResultSet = set()
    for user_id, tournament_id, rank, source_version_id in result:
        division = context.resolve_division(rank, source_version_id=source_version_id)
        if division and op_fn(division.number, value):
            results.add((user_id, tournament_id))
    return results


@register("div_change")
async def execute_div_change(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Division shift after tournament — requires analytics data."""
    direction = params["direction"]  # "up" or "down"
    min_shift = params["min_shift"]

    if context.grid is None and context.normalizer is None:
        return set()

    # Use window function LAG to compare adjacent tournament divisions
    player_with_lag = (
        sa.select(
            models.Player.user_id,
            models.Player.tournament_id,
            models.Player.rank,
            models.Player.role,
            models.Tournament.division_grid_version_id.label("source_version_id"),
            sa.func.lag(models.Player.rank).over(
                partition_by=[models.Player.user_id, models.Player.role],
                order_by=models.Tournament.number,
            ).label("prev_rank"),
            sa.func.lag(models.Tournament.division_grid_version_id).over(
                partition_by=[models.Player.user_id, models.Player.role],
                order_by=models.Tournament.number,
            ).label("prev_source_version_id"),
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
        )
    ).subquery("player_lag")

    query = sa.select(
        player_with_lag.c.user_id,
        player_with_lag.c.tournament_id,
        player_with_lag.c.rank,
        player_with_lag.c.source_version_id,
        player_with_lag.c.prev_rank,
        player_with_lag.c.prev_source_version_id,
    ).where(player_with_lag.c.prev_rank.isnot(None))

    if context.tournament:
        query = query.where(player_with_lag.c.tournament_id == context.tournament.id)

    result = await session.execute(query)
    results: ResultSet = set()
    for user_id, tournament_id, rank, source_version_id, prev_rank, prev_source_version_id in result:
        current_div = context.resolve_division(rank, source_version_id=source_version_id)
        prev_div = context.resolve_division(prev_rank, source_version_id=prev_source_version_id)
        if not current_div or not prev_div:
            continue

        # Division numbers: lower = better (div 1 = top, div 20 = bottom).
        # "up" = improvement: prev_div.number > current_div.number
        # "down" = degradation: current_div.number > prev_div.number
        if direction == "up":
            shift = prev_div.number - current_div.number
        else:
            shift = current_div.number - prev_div.number
        if shift >= min_shift:
            results.add((user_id, tournament_id))

    return results
