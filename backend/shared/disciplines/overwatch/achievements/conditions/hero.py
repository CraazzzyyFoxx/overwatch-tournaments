"""hero_stat / hero_kd_best — hero-specific conditions.

Grain: user_tournament for hero_kd_best, user_match for hero_stat.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain
from shared.repository.stats_queries import player_facts

from . import ResultSet, register, stat_param
from .stat_threshold import OPERATORS


@register(
    "hero_stat",
    grain=AchievementGrain.user_match,
    description="Per-map stat while playing one specific hero",
    required=("hero_slug", "stat", "op", "value"),
    validate_params=stat_param,
    depends_on=("stats.fact",),
)
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
    facts = player_facts(discipline="overwatch")
    sum_expr = sa.func.sum(facts.c.value)

    query = (
        sa.select(
            facts.c.player_id,
            facts.c.tournament_id,
            facts.c.match_id,
        )
        .select_from(facts)
        .join(models.CatalogEntity, models.CatalogEntity.id == facts.c.entity_id)
        .where(
            models.CatalogEntity.kind == "character",
            models.CatalogEntity.discipline == "overwatch",
            facts.c.stat_code == stat,
            facts.c.segment == 0,
            models.CatalogEntity.slug == hero_slug,
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
    return {(row[0], row[1], row[2]) for row in result}


@register(
    "hero_kd_best",
    grain=AchievementGrain.user_tournament,
    description="Best K/D on a hero across the tournament",
    optional=("hero_slug", "min_match_time", "min_matches", "min_time"),
    depends_on=("stats.fact",),
)
async def execute_hero_kd_best(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Best K/D for a hero in tournament. Grain: user_tournament.

    One query answers every hero: the catalog seeds a rule per hero, and running
    this per rule would be an N+1 of identical scans.
    The per-hero winners are memoized on the run's ``leaf_cache`` and the rule's
    ``hero_slug`` is applied afterwards. Equivalent to filtering in SQL: the
    window already partitions by hero, so other heroes never change a rank.
    """
    hero_slug = params.get("hero_slug")
    min_time = params.get("min_time", 600)
    min_matches = params.get("min_matches", 3)
    min_match_time = params.get("min_match_time", 60)  # per-match minimum playtime

    cache_key = (
        "hero_kd_best",
        context.discipline,
        context.workspace_id,
        context.tournament.id if context.tournament else None,
        min_time,
        min_matches,
        min_match_time,
    )
    by_hero = context.leaf_cache.get(cache_key)
    if by_hero is None:
        by_hero = await _hero_kd_best_by_slug(session, context, min_time, min_matches, min_match_time)
        context.leaf_cache[cache_key] = by_hero

    if hero_slug:
        return set(by_hero.get(hero_slug, ()))
    return set().union(*by_hero.values())


async def _hero_kd_best_by_slug(
    session: AsyncSession,
    context: EvalContext,
    min_time: float,
    min_matches: int,
    min_match_time: float,
) -> dict[str, set[tuple[int, int]]]:
    """``{hero_slug: {(user_id, tournament_id)}}`` — each hero's best K/D per tournament."""
    facts = player_facts(discipline="overwatch")
    base = (
        sa.select(
            facts.c.player_id,
            facts.c.tournament_id,
            facts.c.match_id,
            facts.c.entity_id,
            facts.c.stat_code,
            sa.func.sum(facts.c.value).label("val"),
        )
        .where(
            facts.c.segment == 0,
            facts.c.entity_id.is_not(None),
            facts.c.stat_code.in_(("eliminations", "deaths", "hero_time_played")),
            facts.c.workspace_id == context.workspace_id,
            # Mix stats live only inside the mix (mix encounters have no tournament).
            facts.c.tournament_id.is_not(None),
        )
        .group_by(
            facts.c.player_id,
            facts.c.tournament_id,
            facts.c.match_id,
            facts.c.entity_id,
            facts.c.stat_code,
        )
    )

    if context.tournament:
        base = base.where(facts.c.tournament_id == context.tournament.id)

    base_sq = base.subquery("base")

    # Pivot: per-user-per-match → eliminations, deaths, time_played
    user_match = (
        sa.select(
            base_sq.c.player_id,
            base_sq.c.tournament_id,
            base_sq.c.entity_id,
            base_sq.c.match_id,
            sa.func.sum(
                sa.case(
                    (base_sq.c.stat_code == "eliminations", base_sq.c.val),
                    else_=0,
                )
            ).label("eliminations"),
            sa.func.sum(
                sa.case(
                    (base_sq.c.stat_code == "deaths", base_sq.c.val),
                    else_=0,
                )
            ).label("deaths"),
            sa.func.sum(
                sa.case(
                    (base_sq.c.stat_code == "hero_time_played", base_sq.c.val),
                    else_=0,
                )
            ).label("time_played"),
        ).group_by(
            base_sq.c.player_id,
            base_sq.c.tournament_id,
            base_sq.c.entity_id,
            base_sq.c.match_id,
        )
    ).subquery("user_match")

    # Filter out matches where hero playtime is below per-match minimum
    qualified_matches = (sa.select(user_match).where(user_match.c.time_played >= min_match_time)).subquery(
        "qualified_matches"
    )

    # Aggregate across matches: per-user-per-hero-per-tournament
    agg = (
        sa.select(
            qualified_matches.c.player_id,
            qualified_matches.c.tournament_id,
            qualified_matches.c.entity_id,
            (
                sa.func.sum(qualified_matches.c.eliminations)
                / sa.func.nullif(sa.func.sum(qualified_matches.c.deaths), 0)
            ).label("kd"),
            sa.func.sum(qualified_matches.c.time_played).label("total_time"),
            sa.func.count().label("match_count"),
        )
        .group_by(
            qualified_matches.c.player_id,
            qualified_matches.c.tournament_id,
            qualified_matches.c.entity_id,
        )
        .having(
            sa.func.sum(qualified_matches.c.time_played) >= min_time,
            sa.func.count() >= min_matches,
        )
    ).subquery("agg")

    # Best K/D per hero per tournament
    best = (
        sa.select(
            agg.c.player_id,
            agg.c.tournament_id,
            agg.c.entity_id,
            sa.func.row_number()
            .over(
                partition_by=[agg.c.tournament_id, agg.c.entity_id],
                order_by=agg.c.kd.desc(),
            )
            .label("rn"),
        )
    ).subquery("best")

    final = (
        sa.select(best.c.player_id, best.c.tournament_id, models.CatalogEntity.slug)
        .join(models.CatalogEntity, models.CatalogEntity.id == best.c.entity_id)
        .where(
            best.c.rn == 1,
            models.CatalogEntity.kind == "character",
            models.CatalogEntity.discipline == "overwatch",
        )
    )

    by_hero: dict[str, set[tuple[int, int]]] = {}
    for user_id, tournament_id, slug in await session.execute(final):
        by_hero.setdefault(slug, set()).add((user_id, tournament_id))
    return by_hero
