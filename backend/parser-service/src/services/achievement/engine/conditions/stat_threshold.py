"""stat_threshold — per-match stat meets a threshold.

Grain: user_match (user_id, tournament_id, match_id).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register

OPERATORS = {
    "==": lambda col, val: col == val,
    "!=": lambda col, val: col != val,
    ">=": lambda col, val: col >= val,
    ">": lambda col, val: col > val,
    "<=": lambda col, val: col <= val,
    "<": lambda col, val: col < val,
}


@register("stat_threshold")
async def execute(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    from . import resolve_stat_name
    stat_name = resolve_stat_name(params["stat"])
    op = params["op"]
    value = params["value"]

    op_fn = OPERATORS[op]
    sum_expr = sa.func.sum(models.MatchStatistics.value)

    query = (
        sa.select(
            models.MatchStatistics.user_id,
            models.Encounter.tournament_id,
            models.MatchStatistics.match_id,
        )
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(
            models.MatchStatistics.name == stat_name,
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.is_(None),
            models.Tournament.workspace_id == context.workspace_id,
        )
        .group_by(
            models.MatchStatistics.user_id,
            models.Encounter.tournament_id,
            models.MatchStatistics.match_id,
        )
        .having(op_fn(sum_expr, value))
    )

    if context.tournament:
        query = query.where(models.Encounter.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1], row[2]) for row in result}
