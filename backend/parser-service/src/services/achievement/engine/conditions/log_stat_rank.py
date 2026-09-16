"""log_stat_rank — top-N players per tournament by an aggregate log stat.

Grain: user_tournament.

Count stats (eliminations, damage, time) may be ranked per minute of
``HeroTimePlayed``. Rate stats (accuracy, K/D) must not: dividing a stored
percentage by time awards the shortest sample, not the best rate.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src import models

from ..context import EvalContext
from . import ResultSet, register

# Stored as a 0–100 (or 0–1) rate, not a count. Never rank these as value/time.
_RATE_STATS = frozenset(
    {
        "CriticalHitAccuracy",
        "ScopedCriticalHitAccuracy",
        "ScopedAccuracy",
        "WeaponAccuracy",
        "KD",
        "KDA",
    }
)

# Prefer the original hits/shots fraction when both sides are logged.
_RATE_FRACTIONS: dict[str, tuple[str, str]] = {
    "CriticalHitAccuracy": ("CriticalHits", "ShotsFired"),
    "WeaponAccuracy": ("ShotsHit", "ShotsFired"),
    "ScopedAccuracy": ("ScopedShotsHit", "ScopedShotsFired"),
}


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
        normalize_by_time = not is_rate

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
    log_value = sa.func.sum(sa.case((models.MatchStatistics.name == stat, models.MatchStatistics.value), else_=0))
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
    return per_user


def _fraction_query(stat: str, context: EvalContext) -> sa.Select:
    numerator, denominator = _RATE_FRACTIONS[stat]
    num_value = sa.func.sum(sa.case((models.MatchStatistics.name == numerator, models.MatchStatistics.value), else_=0))
    den_value = sa.func.sum(
        sa.case((models.MatchStatistics.name == denominator, models.MatchStatistics.value), else_=0)
    )
    per_user = (
        sa.select(
            models.MatchStatistics.user_id.label("user_id"),
            models.Encounter.tournament_id.label("tournament_id"),
            (num_value / sa.func.nullif(den_value, 0)).label("metric"),
        )
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(
            models.MatchStatistics.name.in_([numerator, denominator]),
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.is_(None),
            models.Tournament.workspace_id == context.workspace_id,
        )
        .group_by(models.MatchStatistics.user_id, models.Encounter.tournament_id)
    )
    if context.tournament:
        per_user = per_user.where(models.Encounter.tournament_id == context.tournament.id)
    return per_user


def _time_weighted_rate_query(stat: str, context: EvalContext) -> sa.Select:
    """Mean of the stored rate, weighted by HeroTimePlayed — not rate/time."""
    rate_row = aliased(models.MatchStatistics)
    time_row = aliased(models.MatchStatistics)
    per_user = (
        sa.select(
            rate_row.user_id.label("user_id"),
            models.Encounter.tournament_id.label("tournament_id"),
            (sa.func.sum(rate_row.value * time_row.value) / sa.func.nullif(sa.func.sum(time_row.value), 0)).label(
                "metric"
            ),
        )
        .select_from(rate_row)
        .join(
            time_row,
            sa.and_(
                time_row.match_id == rate_row.match_id,
                time_row.user_id == rate_row.user_id,
                time_row.round == 0,
                time_row.hero_id.is_(None),
                time_row.name == "HeroTimePlayed",
            ),
        )
        .join(models.Match, models.Match.id == rate_row.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(
            rate_row.name == stat,
            rate_row.round == 0,
            rate_row.hero_id.is_(None),
            models.Tournament.workspace_id == context.workspace_id,
        )
        .group_by(rate_row.user_id, models.Encounter.tournament_id)
    )
    if context.tournament:
        per_user = per_user.where(models.Encounter.tournament_id == context.tournament.id)
    return per_user
