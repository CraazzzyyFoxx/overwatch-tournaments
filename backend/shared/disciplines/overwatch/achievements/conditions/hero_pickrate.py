"""hero_pickrate — played a low-pickrate hero during a tournament.

Grain: user_tournament.

Backs ``freak``: a hero counts as rare when its total
playtime in the tournament is below ``value`` (fraction) of the tournament's
total hero playtime. Pickrate is computed per tournament, never against global
hero sums.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain
from shared.repository.stats_queries import player_facts

from . import ResultSet, register
from .stat_threshold import OPERATORS

MIN_PLAYTIME_SEC = 60


@register(
    "hero_pickrate",
    grain=AchievementGrain.user_tournament,
    description="Played a hero nobody else picked",
    optional=("op", "value"),
    depends_on=("stats.fact",),
)
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

    facts = player_facts(discipline="overwatch")
    base_where = [
        facts.c.stat_code == "hero_time_played",
        facts.c.value > MIN_PLAYTIME_SEC,
        facts.c.entity_id.is_not(None),
        facts.c.segment == 0,
        facts.c.workspace_id == context.workspace_id,
        # Custom-game encounters carry no tournament; without this they would pool into one NULL "tournament".
        facts.c.tournament_id.is_not(None),
    ]
    if context.tournament:
        base_where.append(facts.c.tournament_id == context.tournament.id)

    # One read of the facts: playtime per (tournament, hero, player), with the hero's and the tournament's
    # totals summed over those groups by window functions. Reading ``player_facts`` three times (total, per
    # hero, per player) and joining the reads back together fetched every fact of the tournament's matches
    # three times and ran past the 30 s statement timeout on a single production tournament.
    player_hero_time = sa.func.sum(facts.c.value)
    pickrate = (
        sa.select(
            facts.c.player_id,
            facts.c.tournament_id,
            sa.func.sum(player_hero_time)
            .over(partition_by=(facts.c.tournament_id, facts.c.entity_id))
            .label("hero_time"),
            sa.func.sum(player_hero_time).over(partition_by=facts.c.tournament_id).label("total_time"),
        )
        .select_from(facts)
        .where(*base_where)
        .group_by(facts.c.tournament_id, facts.c.entity_id, facts.c.player_id)
    ).subquery("pickrate")

    query = (
        sa.select(pickrate.c.player_id, pickrate.c.tournament_id)
        .where(op_fn(pickrate.c.hero_time, value * pickrate.c.total_time))
        .distinct()
    )

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
