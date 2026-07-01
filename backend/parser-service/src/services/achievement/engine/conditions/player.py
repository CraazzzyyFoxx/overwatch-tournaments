"""Player-level conditions: is_captain, is_newcomer, tournament_type, tournament_count.

Grain varies by condition.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS


@register("is_captain")
async def execute_is_captain(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Grain: user_tournament."""
    query = (
        sa.select(models.WorkspaceMember.player_id, models.Player.tournament_id)
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Team.captain_id == models.WorkspaceMember.player_id,
            models.Tournament.workspace_id == context.workspace_id,
        )
    )
    if context.tournament:
        query = query.where(models.Player.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}


@register("is_newcomer")
async def execute_is_newcomer(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Check newcomer status. Grain: user_tournament.

    Without params or with empty params: simple boolean check (is_newcomer=True).
    With op/value: count tournaments where user was newcomer, compare with threshold.
      e.g. {"op": ">=", "value": 2} — was newcomer in 2+ tournaments.
    """
    op = params.get("op")
    value = params.get("value")

    if op and value is not None:
        # Count-based: how many tournaments user was a newcomer in
        op_fn = OPERATORS[op]
        query = (
            sa.select(models.WorkspaceMember.player_id)
            .select_from(models.Player)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(
                models.Player.is_newcomer.is_(True),
                models.Player.is_substitution.is_(False),
                models.Tournament.workspace_id == context.workspace_id,
            )
            .group_by(models.WorkspaceMember.player_id)
            .having(op_fn(sa.func.count(models.Player.tournament_id.distinct()), value))
        )
        if context.tournament:
            query = query.where(models.Player.tournament_id == context.tournament.id)

        result = await session.execute(query)
        return {(row[0],) for row in result}

    # Simple boolean: user is newcomer in tournament
    query = (
        sa.select(models.WorkspaceMember.player_id, models.Player.tournament_id)
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Player.is_newcomer.is_(True),
            models.Player.is_substitution.is_(False),
            models.Tournament.workspace_id == context.workspace_id,
        )
    )
    if context.tournament:
        query = query.where(models.Player.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}


@register("tournament_type")
async def execute_tournament_type(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Filter by tournament type. Grain: user_tournament.

    is_league: true/false/null. null = any tournament (no filter).
    """
    is_league = params.get("is_league")

    query = (
        sa.select(models.WorkspaceMember.player_id, models.Player.tournament_id)
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
        )
    )

    if is_league is not None:
        query = query.where(models.Tournament.is_league.is_(is_league))

    if context.tournament:
        query = query.where(models.Player.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}


@register("tournament_count")
async def execute_tournament_count(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Number of tournaments played. Grain: user (global).

    Optional filters narrow which tournaments are counted:
        is_league: bool | None — filter Tournament.is_league
        number_min / number_max: int — filter Tournament.number range
            (e.g. number_max=18 for OW1, number_min=19 for OW2)
    """
    op = params["op"]
    value = params["value"]
    op_fn = OPERATORS[op]

    is_league = params.get("is_league")
    number_min = params.get("number_min")
    number_max = params.get("number_max")

    where_clauses = [
        models.Tournament.workspace_id == context.workspace_id,
        models.Player.is_substitution.is_(False),
    ]
    if is_league is not None:
        where_clauses.append(models.Tournament.is_league.is_(is_league))
    if number_min is not None:
        where_clauses.append(models.Tournament.number >= number_min)
    if number_max is not None:
        where_clauses.append(models.Tournament.number <= number_max)

    query = (
        sa.select(models.WorkspaceMember.player_id)
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(*where_clauses)
        .group_by(models.WorkspaceMember.player_id)
        .having(op_fn(sa.func.count(models.Player.tournament_id.distinct()), value))
    )

    result = await session.execute(query)
    return {(row[0],) for row in result}
