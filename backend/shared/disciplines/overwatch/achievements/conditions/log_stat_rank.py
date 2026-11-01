"""log_stat_rank — top-N players per tournament by an aggregate log stat.

Grain: user_tournament.

Count stats (eliminations, damage, time) may be ranked per minute of
``HeroTimePlayed``. Rate stats (accuracy, K/D) must not: dividing a stored
percentage by time awards the shortest sample, not the best rate.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.impact import CONTRIBUTION_STATS
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain
from shared.repository.stats_queries import player_facts

from . import ResultSet, register, stat_param

# Stored as a 0–100 (or 0–1) rate, not a count. Never rank these as value/time.
_RATE_STATS = frozenset(
    {
        "critical_hit_accuracy",
        "scoped_critical_hit_accuracy",
        "scoped_accuracy",
        "weapon_accuracy",
        "kd",
        "kda",
    }
)

# Additive per map, but already normalized when the parser computed them
# (``impact.py`` multiplies by the player's time share). Dividing them by
# HeroTimePlayed a second time would rank the shortest appearance highest.
_NO_TIME_NORMALIZE = frozenset(
    {
        "impact_points",
        "impact_rank",
        "overperformance_score",
        "overperformance_badge",
        *(stat.value for stat in CONTRIBUTION_STATS.values()),
    }
)

# Prefer the original hits/shots fraction when both sides are logged.
_RATE_FRACTIONS: dict[str, tuple[str, str]] = {
    "critical_hit_accuracy": ("critical_hits", "shots_fired"),
    "weapon_accuracy": ("shots_hit", "shots_fired"),
    "scoped_accuracy": ("scoped_shots_hit", "scoped_shots_fired"),
}


@register(
    "log_stat_rank",
    grain=AchievementGrain.user_tournament,
    description="Ranked by a log stat across the tournament",
    required=("stat",),
    validate_params=stat_param,
    optional=("limit", "normalize_by_time", "order"),
    depends_on=("stats.fact",),
)
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
        normalize_by_time: bool — divide a *count* by HeroTimePlayed. Ignored
            for rate stats. Default True for counts, False for rates.
    """
    from . import resolve_stat_name

    stat = resolve_stat_name(params["stat"])
    order = params.get("order", "desc")
    limit = params.get("limit", 1)
    is_rate = stat in _RATE_STATS
    if "normalize_by_time" in params:
        normalize_by_time = bool(params["normalize_by_time"]) and not is_rate
    else:
        normalize_by_time = not is_rate and stat not in _NO_TIME_NORMALIZE

    if stat in _RATE_FRACTIONS:
        per_user = _fraction_query(stat, context)
    elif is_rate:
        per_user = _time_weighted_rate_query(stat, context)
    else:
        per_user = _count_query(stat, context, normalize_by_time=normalize_by_time)

    per_user_sq = per_user.subquery("per_user")

    order_expr = sa.desc(per_user_sq.c.metric) if order == "desc" else sa.asc(per_user_sq.c.metric)
    ranked = (
        sa.select(
            per_user_sq.c.user_id,
            per_user_sq.c.tournament_id,
            sa.func.row_number().over(partition_by=per_user_sq.c.tournament_id, order_by=order_expr).label("rn"),
        ).where(per_user_sq.c.metric.isnot(None))
    ).subquery("ranked")

    query = sa.select(ranked.c.user_id, ranked.c.tournament_id).where(ranked.c.rn <= limit)
    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}


def _count_query(stat: str, context: EvalContext, *, normalize_by_time: bool) -> sa.Select:
    facts = player_facts(discipline="overwatch")
    log_value = sa.func.sum(sa.case((facts.c.stat_code == stat, facts.c.value), else_=0))
    time_value = sa.func.sum(sa.case((facts.c.stat_code == "hero_time_played", facts.c.value), else_=0))
    metric = log_value / sa.func.nullif(time_value, 0) if normalize_by_time else log_value
    stat_codes = [stat, "hero_time_played"] if normalize_by_time else [stat]
    query = (
        sa.select(facts.c.player_id.label("user_id"), facts.c.tournament_id, metric.label("metric"))
        .where(
            facts.c.stat_code.in_(stat_codes),
            facts.c.segment == 0,
            facts.c.entity_id.is_(None),
            facts.c.workspace_id == context.workspace_id,
            # Mix stats live only inside the mix (mix encounters have no tournament).
            facts.c.tournament_id.is_not(None),
        )
        .group_by(facts.c.player_id, facts.c.tournament_id)
    )
    if context.tournament:
        query = query.where(facts.c.tournament_id == context.tournament.id)
    return query


def _fraction_query(stat: str, context: EvalContext) -> sa.Select:
    numerator, denominator = _RATE_FRACTIONS[stat]
    facts = player_facts(discipline="overwatch")
    num_value = sa.func.sum(sa.case((facts.c.stat_code == numerator, facts.c.value), else_=0))
    den_value = sa.func.sum(sa.case((facts.c.stat_code == denominator, facts.c.value), else_=0))
    query = (
        sa.select(
            facts.c.player_id.label("user_id"),
            facts.c.tournament_id,
            (num_value / sa.func.nullif(den_value, 0)).label("metric"),
        )
        .where(
            facts.c.stat_code.in_((numerator, denominator)),
            facts.c.segment == 0,
            facts.c.entity_id.is_(None),
            facts.c.workspace_id == context.workspace_id,
            # Mix stats live only inside the mix (mix encounters have no tournament).
            facts.c.tournament_id.is_not(None),
        )
        .group_by(facts.c.player_id, facts.c.tournament_id)
    )
    if context.tournament:
        query = query.where(facts.c.tournament_id == context.tournament.id)
    return query


def _time_weighted_rate_query(stat: str, context: EvalContext) -> sa.Select:
    """Mean of the stored rate, weighted by playtime — not rate/time."""
    rate_row = player_facts(discipline="overwatch")
    time_row = rate_row.alias("playtime")
    # Both scopes reduce the same observations in the same native order, even
    # when PostgreSQL chooses a different join or grouping plan.
    reduction_order = (rate_row.c.match_id, rate_row.c.workspace_member_id)
    query = (
        sa.select(
            rate_row.c.player_id.label("user_id"),
            rate_row.c.tournament_id,
            (
                sa.func.sum(aggregate_order_by(rate_row.c.value * time_row.c.value, *reduction_order))
                / sa.func.nullif(sa.func.sum(aggregate_order_by(time_row.c.value, *reduction_order)), 0)
            ).label("metric"),
        )
        .select_from(rate_row)
        .join(
            time_row,
            sa.and_(
                time_row.c.match_id == rate_row.c.match_id,
                time_row.c.workspace_member_id == rate_row.c.workspace_member_id,
                time_row.c.encounter_team_id == rate_row.c.encounter_team_id,
                time_row.c.segment == 0,
                time_row.c.entity_id.is_(None),
                time_row.c.stat_code == "hero_time_played",
            ),
        )
        .where(
            rate_row.c.stat_code == stat,
            rate_row.c.segment == 0,
            rate_row.c.entity_id.is_(None),
            rate_row.c.workspace_id == context.workspace_id,
            # Mix stats live only inside the mix (mix encounters have no tournament).
            rate_row.c.tournament_id.is_not(None),
        )
        .group_by(rate_row.c.player_id, rate_row.c.tournament_id)
    )
    if context.tournament:
        query = query.where(rate_row.c.tournament_id == context.tournament.id)
    return query
