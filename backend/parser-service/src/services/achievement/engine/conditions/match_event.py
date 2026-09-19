"""match_event_count — how often a parsed log event fired for one player on one map.

Grain: user_match (user_id, tournament_id, match_id).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import MatchEvent as MatchEventName
from shared.models.achievements.achievement import AchievementGrain
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


@register(
    "match_event_count",
    grain=AchievementGrain.user_match,
    description="How many times an in-match event happened for this player on one map",
    required=("event", "op", "value"),
    optional=("hero_slug",),
    depends_on=("matches.event", "matches.match", "tournament.encounter"),
)
async def execute_match_event_count(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    # ``Enum(enums.MatchEvent)`` persists the member NAME ("HeroSwap"), not its
    # value ("hero_swap") — so the param is a member name and the bind is the
    # member itself, which the column type renders back to that name. An
    # unknown name raises KeyError here; the runner records it as a rule failure.
    event = MatchEventName[params["event"]]
    op = params["op"]
    value = params["value"]
    hero_slug = params.get("hero_slug")

    op_fn = OPERATORS[op]
    count_expr = sa.func.count()

    query = (
        sa.select(
            models.MatchEvent.user_id,
            models.Encounter.tournament_id,
            models.MatchEvent.match_id,
            count_expr.label("measured"),
        )
        .join(models.Match, models.Match.id == models.MatchEvent.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(
            models.MatchEvent.name == event,
            models.Tournament.workspace_id == context.workspace_id,
        )
        .group_by(
            models.MatchEvent.user_id,
            models.Encounter.tournament_id,
            models.MatchEvent.match_id,
        )
        .having(op_fn(count_expr, value))
    )

    if hero_slug:
        query = query.join(models.Hero, models.Hero.id == models.MatchEvent.hero_id).where(
            models.Hero.slug == hero_slug
        )

    if context.tournament:
        query = query.where(models.Encounter.tournament_id == context.tournament.id)

    result = await session.execute(query)
    keys: ResultSet = set()
    for row in result:
        key = (row[0], row[1], row[2])
        keys.add(key)
        context.record_evidence(key, event=event.name, count=int(row[3]))
    return keys
