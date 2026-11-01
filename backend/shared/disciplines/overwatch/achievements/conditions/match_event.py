"""match_event_count — how often a parsed log event fired for one player on one map.

Grain: user_match (user_id, tournament_id, match_id).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import MatchEvent as MatchEventName
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain
from shared.repository.stats_queries import match_context

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
    depends_on=("stats.event", "stats.match", "tournament.encounter"),
)
async def execute_match_event_count(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    # Keep the DSL/evidence member name; compare the native event code.
    event = MatchEventName[params["event"]]
    op = params["op"]
    value = params["value"]
    hero_slug = params.get("hero_slug")

    op_fn = OPERATORS[op]
    count_expr = sa.func.count()

    match = match_context(discipline="overwatch")
    query = (
        sa.select(
            models.WorkspaceMember.player_id,
            match.c.tournament_id,
            models.StatsEvent.match_id,
            count_expr.label("measured"),
        )
        .select_from(models.StatsEvent)
        .join(match, match.c.id == models.StatsEvent.match_id)
        .join(
            models.EventType,
            sa.and_(
                models.EventType.id == models.StatsEvent.type_id,
                models.EventType.discipline == match.c.discipline,
            ),
        )
        .join(
            models.WorkspaceMember,
            sa.and_(
                models.WorkspaceMember.id == models.StatsEvent.actor_member_id,
                models.WorkspaceMember.workspace_id == match.c.workspace_id,
            ),
        )
        .where(
            models.EventType.code == event.value,
            match.c.workspace_id == context.workspace_id,
            # Mix stats live only inside the mix (mix encounters have no tournament).
            match.c.tournament_id.is_not(None),
        )
        .group_by(
            models.WorkspaceMember.player_id,
            match.c.tournament_id,
            models.StatsEvent.match_id,
        )
        .having(op_fn(count_expr, value))
    )

    if hero_slug:
        query = query.join(models.CatalogEntity, models.CatalogEntity.id == models.StatsEvent.entity_id).where(
            models.CatalogEntity.slug == hero_slug,
            models.CatalogEntity.kind == "character",
            models.CatalogEntity.discipline == "overwatch",
        )

    if context.tournament:
        query = query.where(match.c.tournament_id == context.tournament.id)

    result = await session.execute(query)
    keys: ResultSet = set()
    for row in result:
        key = (row[0], row[1], row[2])
        keys.add(key)
        context.record_evidence(key, event=event.name, count=int(row[3]))
    return keys
