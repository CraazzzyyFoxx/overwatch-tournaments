"""stat_threshold — per-match stat meets a threshold.

Grain: user_match (user_id, tournament_id, match_id).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import LogStatsName
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain
from shared.repository.stats_queries import player_facts

from . import ResultSet, register, stat_param

OPERATORS = {
    "==": lambda col, val: col == val,
    "!=": lambda col, val: col != val,
    ">=": lambda col, val: col >= val,
    ">": lambda col, val: col > val,
    "<=": lambda col, val: col <= val,
    "<": lambda col, val: col < val,
}


@register(
    "stat_threshold",
    grain=AchievementGrain.user_match,
    description="Per-map log stat compared against a threshold",
    required=("stat", "op", "value"),
    validate_params=stat_param,
    depends_on=("stats.match", "stats.fact"),
)
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
    facts = player_facts(discipline="overwatch")
    sum_expr = sa.func.sum(facts.c.value)

    query = (
        sa.select(
            facts.c.player_id,
            facts.c.tournament_id,
            facts.c.match_id,
            sum_expr.label("measured"),
        )
        .select_from(facts)
        .where(
            facts.c.stat_code == stat_name,
            facts.c.segment == 0,
            facts.c.entity_id.is_(None),
            facts.c.workspace_id == context.workspace_id,
            # Mix stats live only inside the mix (mix encounters have no tournament).
            facts.c.tournament_id.is_not(None),
        )
        .group_by(
            facts.c.player_id,
            facts.c.tournament_id,
            facts.c.match_id,
        )
        .having(op_fn(sum_expr, value))
    )

    if context.tournament:
        query = query.where(facts.c.tournament_id == context.tournament.id)

    result = await session.execute(query)
    keys: ResultSet = set()
    for row in result:
        key = (row[0], row[1], row[2])
        keys.add(key)
        context.record_evidence(key, stat=LogStatsName(stat_name).name, measured=row[3], op=op, threshold=value)
    return keys
