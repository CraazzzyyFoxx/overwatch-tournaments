"""hero_pickrate — played a low-pickrate hero during a tournament.

Grain: user_tournament.

Ports the legacy ``freak`` achievement: a hero counts as rare when its total
playtime in the tournament is below ``value`` (fraction) of the tournament's
total hero playtime. Pickrate is computed per tournament (cleaner than the
legacy code, which mixed global hero sums with a per-tournament total).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS

MIN_PLAYTIME_SEC = 60


@register("hero_pickrate")
async def execute_hero_pickrate(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Played a hero whose tournament pickrate is below threshold. Grain: user_tournament.

    params:
        op: comparison operator (default "<")
        value: pickrate fraction (default 0.001 == 0.1%)
    """
    op = params.get("op", "<")
    value = params.get("value", 0.001)
    op_fn = OPERATORS[op]

    base_where = [
        models.MatchStatistics.name == "HeroTimePlayed",
        models.MatchStatistics.value > MIN_PLAYTIME_SEC,
        models.MatchStatistics.hero_id.isnot(None),
        models.MatchStatistics.round == 0,
        models.Tournament.workspace_id == context.workspace_id,
    ]
    if context.tournament:
        base_where.append(models.Encounter.tournament_id == context.tournament.id)

    def _playtime_base(*columns: Any) -> sa.Select[Any]:
        return (
            sa.select(*columns)
            .select_from(models.MatchStatistics)
            .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
            .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(*base_where)
        )

    total_sq = (
        _playtime_base(
            models.Encounter.tournament_id.label("tournament_id"),
            sa.func.sum(models.MatchStatistics.value).label("total_time"),
        ).group_by(models.Encounter.tournament_id)
    ).subquery("pickrate_total")

    hero_sq = (
        _playtime_base(
            models.Encounter.tournament_id.label("tournament_id"),
            models.MatchStatistics.hero_id.label("hero_id"),
            sa.func.sum(models.MatchStatistics.value).label("hero_time"),
        ).group_by(models.Encounter.tournament_id, models.MatchStatistics.hero_id)
    ).subquery("pickrate_hero")

    rare_heroes = (
        sa.select(hero_sq.c.tournament_id, hero_sq.c.hero_id)
        .join(total_sq, total_sq.c.tournament_id == hero_sq.c.tournament_id)
        .where(op_fn(hero_sq.c.hero_time, value * total_sq.c.total_time))
    ).subquery("rare_heroes")

    query = (
        _playtime_base(models.MatchStatistics.user_id, models.Encounter.tournament_id)
        .join(
            rare_heroes,
            sa.and_(
                rare_heroes.c.tournament_id == models.Encounter.tournament_id,
                rare_heroes.c.hero_id == models.MatchStatistics.hero_id,
            ),
        )
        .group_by(models.MatchStatistics.user_id, models.Encounter.tournament_id)
    )

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
