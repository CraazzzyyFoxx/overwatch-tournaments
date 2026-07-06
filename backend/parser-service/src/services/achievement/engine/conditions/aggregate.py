"""Global aggregate conditions: global_stat_sum, global_winrate, distinct_count.

Grain: user (global).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS


@register("global_stat_sum")
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

    query = (
        sa.select(models.MatchStatistics.user_id)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(
            models.MatchStatistics.name == stat,
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.is_(None),
            models.Tournament.workspace_id == context.workspace_id,
        )
        .group_by(models.MatchStatistics.user_id)
        .having(op_fn(sa.func.sum(models.MatchStatistics.value), value))
    )

    result = await session.execute(query)
    return {(row[0],) for row in result}


@register("global_winrate")
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
        include_league: bool (default False).
    """
    op = params.get("op")
    value = params.get("value")
    order = params.get("order", "desc")
    limit = params.get("limit")
    include_league = params.get("include_league", False)
    metric = params.get("metric", "winrate")

    home_score = sa.case(
        (models.Encounter.home_team_id == models.Team.id, models.Encounter.home_score),
        else_=models.Encounter.away_score,
    )
    away_score = sa.case(
        (models.Encounter.home_team_id == models.Team.id, models.Encounter.away_score),
        else_=models.Encounter.home_score,
    )

    sum_home = sa.func.sum(home_score)
    sum_away = sa.func.sum(away_score)
    winrate = sum_home / sa.func.nullif(sum_home + sum_away, 0)
    rank_expr = sum_home if metric == "won_maps" else winrate

    query = (
        sa.select(models.WorkspaceMember.player_id)
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Player.is_substitution.is_(False),
            models.Tournament.workspace_id == context.workspace_id,
            *([] if include_league else [models.Tournament.is_league.is_(False)]),
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


@register("distinct_count")
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
                models.Tournament.workspace_id == context.workspace_id,
                models.Player.role.isnot(None),
            )
            .group_by(*group_cols)
            .having(op_fn(sa.func.count(models.Player.role.distinct()), value))
        )

        if context.tournament and scope == "tournament":
            query = query.where(models.Player.tournament_id == context.tournament.id)

        result = await session.execute(query)
        return {tuple(row) for row in result}

    if field == "hero":
        # Count distinct heroes played (with optional min playtime)
        group_cols = [models.MatchStatistics.user_id]
        if scope == "tournament":
            group_cols.append(models.Encounter.tournament_id)

        where_clauses = [
            models.MatchStatistics.hero_id.isnot(None),
            models.MatchStatistics.round == 0,
            models.MatchStatistics.name == "HeroTimePlayed",
            models.Tournament.workspace_id == context.workspace_id,
        ]

        if min_playtime:
            where_clauses.append(models.MatchStatistics.value >= min_playtime)

        query = (
            sa.select(*group_cols)
            .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
            .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(*where_clauses)
            .group_by(*group_cols)
            .having(op_fn(sa.func.count(models.MatchStatistics.hero_id.distinct()), value))
        )

        if context.tournament and scope == "tournament":
            query = query.where(models.Encounter.tournament_id == context.tournament.id)

        result = await session.execute(query)
        return {tuple(row) for row in result}

    if field == "match":
        # Count distinct matches (used with scope="tournament")
        group_cols = [models.MatchStatistics.user_id]
        if scope == "tournament":
            group_cols.append(models.Encounter.tournament_id)

        query = (
            sa.select(*group_cols)
            .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
            .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(
                models.MatchStatistics.round == 0,
                models.MatchStatistics.hero_id.is_(None),
                models.Tournament.workspace_id == context.workspace_id,
            )
            .group_by(*group_cols)
            .having(op_fn(sa.func.count(models.MatchStatistics.match_id.distinct()), value))
        )

        if context.tournament and scope == "tournament":
            query = query.where(models.Encounter.tournament_id == context.tournament.id)

        result = await session.execute(query)
        return {tuple(row) for row in result}

    raise ValueError(f"Unsupported distinct_count field: {field!r}")
