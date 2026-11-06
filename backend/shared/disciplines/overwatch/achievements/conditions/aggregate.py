"""Global aggregate conditions: global_stat_sum, global_winrate, distinct_count.

Grain: user (global).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import EncounterStatus
from shared.disciplines.overwatch.achievements.duel import series_total
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain
from shared.repository.stats_queries import player_facts

from . import ResultSet, register, stat_param
from .stat_threshold import OPERATORS


@register(
    "global_stat_sum",
    grain=AchievementGrain.user,
    description="Career total of a log stat",
    required=("stat", "op", "value"),
    validate_params=stat_param,
    depends_on=("stats.fact",),
)
async def execute_global_stat_sum(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Lifetime stat sum meets threshold. Grain: user."""
    from . import resolve_stat_name

    stat = resolve_stat_name(params["stat"])
    op = params["op"]
    value = params["value"]
    op_fn = OPERATORS[op]

    facts = player_facts(discipline="overwatch")
    query = (
        sa.select(facts.c.player_id)
        .where(
            facts.c.stat_code == stat,
            facts.c.segment == 0,
            facts.c.entity_id.is_(None),
            facts.c.workspace_id == context.workspace_id,
            # Mix stats live only inside the mix (mix encounters have no tournament).
            facts.c.tournament_id.is_not(None),
        )
        .group_by(facts.c.player_id)
        .having(op_fn(sa.func.sum(facts.c.value), value))
    )

    result = await session.execute(query)
    return {(row[0],) for row in result}


@register(
    "global_winrate",
    grain=AchievementGrain.user,
    description="Career winrate ranking",
    optional=("limit", "metric", "op", "order", "value"),
    depends_on=("tournament.encounter", "tournament.player"),
)
async def execute_global_winrate(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Top/bottom N by winrate (or won maps). Grain: user.

    params:
        metric: "winrate" (default) | "won_maps" — ranking key. "won_maps" ranks
            by the total number of won maps (sum of the player's map scores).
        op/value: optional HAVING filter on winrate.
        order: "desc" (default) | "asc".
        limit: optional top/bottom N.
    """
    op = params.get("op")
    value = params.get("value")
    order = params.get("order", "desc")
    limit = params.get("limit")
    metric = params.get("metric", "winrate")

    # The team's own score over the score of everyone seated in the encounter.
    seat = sa.orm.aliased(models.EncounterTeam, name="seat")
    won = sa.func.sum(seat.score)
    winrate = won / sa.func.nullif(sa.func.sum(series_total()), 0)
    rank_expr = won if metric == "won_maps" else winrate

    query = (
        sa.select(models.WorkspaceMember.player_id)
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(seat, sa.and_(seat.team_id == models.Team.id, seat.active.is_(True)))
        .join(models.Encounter, models.Encounter.id == seat.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Player.is_substitution.is_(False),
            sa.and_(
                models.Tournament.workspace_id == context.workspace_id,
                models.Tournament.discipline == context.discipline,
            ),
            models.Tournament.discipline == "overwatch",
            models.Encounter.workspace_id == context.workspace_id,
            models.Encounter.discipline == "overwatch",
            models.WorkspaceMember.workspace_id == context.workspace_id,
            models.Encounter.status == EncounterStatus.COMPLETED,
        )
        .group_by(models.WorkspaceMember.player_id)
    )

    if op and value is not None:
        op_fn = OPERATORS[op]
        query = query.having(op_fn(winrate, value))

    order_expr = rank_expr.desc() if order == "desc" else rank_expr.asc()
    query = query.order_by(order_expr)

    if limit:
        query = query.limit(limit)

    result = await session.execute(query)
    return {(row[0],) for row in result}


@register(
    "distinct_count",
    grain=AchievementGrain.user,
    description="Distinct heroes, matches or roles",
    required=("field", "op", "value"),
    optional=("min_playtime", "scope"),
    depends_on=("stats.fact", "tournament.player"),
    grain_for=lambda params: (
        AchievementGrain.user_tournament if params.get("scope") == "tournament" else AchievementGrain.user
    ),
)
async def execute_distinct_count(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Count distinct values (roles, heroes, matches, teammates). Grain: user or user_tournament."""
    field = params["field"]
    op = params["op"]
    value = params["value"]
    scope = params.get("scope", "global")
    min_playtime = params.get("min_playtime")
    op_fn = OPERATORS[op]

    if field == "role":
        group_cols = [models.WorkspaceMember.player_id]
        if scope == "tournament":
            group_cols.append(models.Player.tournament_id)

        query = (
            sa.select(*group_cols)
            .select_from(models.Player)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(
                models.Player.is_substitution.is_(False),
                sa.and_(
                    models.Tournament.workspace_id == context.workspace_id,
                    models.Tournament.discipline == context.discipline,
                ),
                models.Tournament.discipline == "overwatch",
                models.WorkspaceMember.workspace_id == context.workspace_id,
                models.Player.role.isnot(None),
            )
            .group_by(*group_cols)
            .having(op_fn(sa.func.count(models.Player.role.distinct()), value))
        )

        if context.tournament and scope == "tournament":
            query = query.where(models.Player.tournament_id == context.tournament.id)

        result = await session.execute(query)
        return {tuple(row) for row in result}

    facts = player_facts(discipline="overwatch")
    group_cols = [facts.c.player_id]
    if scope == "tournament":
        group_cols.append(facts.c.tournament_id)
    query = sa.select(*group_cols).where(
        facts.c.workspace_id == context.workspace_id,
        facts.c.segment == 0,
        # Mix stats live only inside the mix (mix encounters have no tournament).
        facts.c.tournament_id.is_not(None),
    )
    if field == "hero":
        query = query.where(
            facts.c.entity_id.is_not(None),
            facts.c.stat_code == "hero_time_played",
        )
        if min_playtime:
            query = query.where(facts.c.value >= min_playtime)
        counted = facts.c.entity_id
    elif field == "match":
        query = query.where(facts.c.entity_id.is_(None))
        counted = facts.c.match_id
    else:
        raise ValueError(f"Unsupported distinct_count field: {field!r}")
    query = query.group_by(*group_cols).having(op_fn(sa.func.count(counted.distinct()), value))
    if context.tournament and scope == "tournament":
        query = query.where(facts.c.tournament_id == context.tournament.id)
    return {tuple(row) for row in await session.execute(query)}
