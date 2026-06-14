"""log_stat_rank — top-N players per tournament by an aggregate log stat.

Grain: user_tournament.

Ports the legacy ``calculate_best_in_logs`` helper: ranks users within each
tournament by ``sum(stat) / sum(HeroTimePlayed)`` (overall rows, ``hero_id IS NULL``)
and keeps the top ``limit`` per tournament.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register


@register("log_stat_rank")
async def execute_log_stat_rank(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Top-N players per tournament by an aggregate stat. Grain: user_tournament.

    params:
        stat: LogStatsName to rank by
        order: "desc" (default) | "asc"
        limit: int (default 1) — how many top players per tournament
        normalize_by_time: bool (default True) — divide the stat sum by total
            HeroTimePlayed before ranking (matches legacy per-minute ranking)
    """
    from . import resolve_stat_name

    stat = resolve_stat_name(params["stat"])
    order = params.get("order", "desc")
    limit = params.get("limit", 1)
    normalize_by_time = params.get("normalize_by_time", True)

    log_value = sa.func.sum(
        sa.case((models.MatchStatistics.name == stat, models.MatchStatistics.value), else_=0)
    )
    time_value = sa.func.sum(
        sa.case(
            (models.MatchStatistics.name == "HeroTimePlayed", models.MatchStatistics.value),
            else_=0,
        )
    )

    if normalize_by_time:
        metric = log_value / sa.func.nullif(time_value, 0)
        stat_names = [stat, "HeroTimePlayed"]
    else:
        metric = log_value
        stat_names = [stat]

    per_user = (
        sa.select(
            models.MatchStatistics.user_id.label("user_id"),
            models.Encounter.tournament_id.label("tournament_id"),
            metric.label("metric"),
        )
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(
            models.MatchStatistics.name.in_(stat_names),
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.is_(None),
            models.Tournament.workspace_id == context.workspace_id,
        )
        .group_by(models.MatchStatistics.user_id, models.Encounter.tournament_id)
    )

    if context.tournament:
        per_user = per_user.where(models.Encounter.tournament_id == context.tournament.id)

    per_user_sq = per_user.subquery("per_user")

    order_expr = (
        sa.desc(per_user_sq.c.metric) if order == "desc" else sa.asc(per_user_sq.c.metric)
    )
    ranked = (
        sa.select(
            per_user_sq.c.user_id,
            per_user_sq.c.tournament_id,
            sa.func.row_number()
            .over(partition_by=per_user_sq.c.tournament_id, order_by=order_expr)
            .label("rn"),
        ).where(per_user_sq.c.metric.isnot(None))
    ).subquery("ranked")

    query = sa.select(ranked.c.user_id, ranked.c.tournament_id).where(ranked.c.rn <= limit)
    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
