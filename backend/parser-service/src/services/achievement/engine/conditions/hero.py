"""hero_stat / hero_kd_best — hero-specific conditions.

Grain: user_tournament for hero_kd_best, user_match for hero_stat.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS


@register("hero_stat")
async def execute_hero_stat(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Per-hero stat in a match. Grain: user_match."""
    hero_slug = params["hero_slug"]
    from . import resolve_stat_name
    stat = resolve_stat_name(params["stat"])
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
        .join(models.Hero, models.Hero.id == models.MatchStatistics.hero_id)
        .where(
            models.MatchStatistics.name == stat,
            models.MatchStatistics.round == 0,
            models.Hero.slug == hero_slug,
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


@register("hero_kd_best")
async def execute_hero_kd_best(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Best K/D for a hero in tournament. Grain: user_tournament."""
    hero_slug = params.get("hero_slug")
    min_time = params.get("min_time", 600)
    min_matches = params.get("min_matches", 3)
    min_match_time = params.get("min_match_time", 60)  # per-match minimum playtime

    # Base: per-user-per-match stats for hero
    hero_filter = []
    if hero_slug:
        hero_filter.append(models.Hero.slug == hero_slug)

    base = (
        sa.select(
            models.MatchStatistics.user_id,
            models.Encounter.tournament_id,
            models.MatchStatistics.match_id,
            models.MatchStatistics.hero_id,
            models.MatchStatistics.name,
            sa.func.sum(models.MatchStatistics.value).label("val"),
        )
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .join(models.Hero, models.Hero.id == models.MatchStatistics.hero_id)
        .where(
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.isnot(None),
            models.MatchStatistics.name.in_([
                "Eliminations",
                "Deaths",
                "HeroTimePlayed",
            ]),
            models.Tournament.workspace_id == context.workspace_id,
            *hero_filter,
        )
        .group_by(
            models.MatchStatistics.user_id,
            models.Encounter.tournament_id,
            models.MatchStatistics.match_id,
            models.MatchStatistics.hero_id,
            models.MatchStatistics.name,
        )
    )

    if context.tournament:
        base = base.where(models.Encounter.tournament_id == context.tournament.id)

    base_sq = base.subquery("base")

    # Pivot: per-user-per-match → eliminations, deaths, time_played
    user_match = (
        sa.select(
            base_sq.c.user_id,
            base_sq.c.tournament_id,
            base_sq.c.hero_id,
            base_sq.c.match_id,
            sa.func.sum(sa.case(
                (base_sq.c.name == "Eliminations", base_sq.c.val),
                else_=0,
            )).label("eliminations"),
            sa.func.sum(sa.case(
                (base_sq.c.name == "Deaths", base_sq.c.val),
                else_=0,
            )).label("deaths"),
            sa.func.sum(sa.case(
                (base_sq.c.name == "HeroTimePlayed", base_sq.c.val),
                else_=0,
            )).label("time_played"),
        )
        .group_by(
            base_sq.c.user_id,
            base_sq.c.tournament_id,
            base_sq.c.hero_id,
            base_sq.c.match_id,
        )
    ).subquery("user_match")

    # Filter out matches where hero playtime is below per-match minimum
    qualified_matches = (
        sa.select(user_match)
        .where(user_match.c.time_played >= min_match_time)
    ).subquery("qualified_matches")

    # Aggregate across matches: per-user-per-hero-per-tournament
    agg = (
        sa.select(
            qualified_matches.c.user_id,
            qualified_matches.c.tournament_id,
            qualified_matches.c.hero_id,
            (
                sa.func.sum(qualified_matches.c.eliminations)
                / sa.func.nullif(sa.func.sum(qualified_matches.c.deaths), 0)
            ).label("kd"),
            sa.func.sum(qualified_matches.c.time_played).label("total_time"),
            sa.func.count().label("match_count"),
        )
        .group_by(
            qualified_matches.c.user_id,
            qualified_matches.c.tournament_id,
            qualified_matches.c.hero_id,
        )
        .having(
            sa.func.sum(qualified_matches.c.time_played) >= min_time,
            sa.func.count() >= min_matches,
        )
    ).subquery("agg")

    # Best K/D per hero per tournament
    best = (
        sa.select(
            agg.c.user_id,
            agg.c.tournament_id,
            agg.c.hero_id,
            sa.func.row_number().over(
                partition_by=[agg.c.tournament_id, agg.c.hero_id],
                order_by=agg.c.kd.desc(),
            ).label("rn"),
        )
    ).subquery("best")

    final = sa.select(best.c.user_id, best.c.tournament_id).where(best.c.rn == 1)

    result = await session.execute(final)
    return {(row[0], row[1]) for row in result}
