"""tournament_winrate — per-tournament team winrate threshold.

Grain: user_tournament.

Ports the legacy ``count_by="win", group_by="tournament"`` branch of
``calculate_wins_achievement``: the player's team winrate within a single
tournament must meet a threshold. Typically combined (AND) with
``standing_position`` to express "won the tournament with a high winrate".
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS


@register("tournament_winrate")
async def execute_tournament_winrate(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Team winrate within a tournament meets a threshold. Grain: user_tournament.

    params:
        op: comparison operator
        value: winrate threshold (0.0–1.0)
    """
    op = params["op"]
    value = params["value"]
    op_fn = OPERATORS[op]

    home_score = sa.case(
        (models.Encounter.home_team_id == models.Team.id, models.Encounter.home_score),
        else_=models.Encounter.away_score,
    )
    away_score = sa.case(
        (models.Encounter.home_team_id == models.Team.id, models.Encounter.away_score),
        else_=models.Encounter.home_score,
    )
    sum_home = sa.func.sum(home_score)
    sum_away = sa.func.sum(away_score)
    winrate = sum_home / sa.func.nullif(sum_home + sum_away, 0)

    query = (
        sa.select(models.Player.user_id, models.Player.tournament_id)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Player.is_substitution.is_(False),
            models.Tournament.workspace_id == context.workspace_id,
        )
        .group_by(models.Player.user_id, models.Player.tournament_id)
        .having(op_fn(winrate, value))
    )

    if context.tournament:
        query = query.where(models.Player.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
