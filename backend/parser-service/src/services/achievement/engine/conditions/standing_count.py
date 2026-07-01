"""standing_count — count tournaments/roles where a final standing matches.

Grain: user (global).

Ports the legacy ``calculate_wins_achievement`` helper: counts how many
tournaments (or distinct roles across tournaments) a user reached a given
elimination-standing position in.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from ._stage_filters import standing_is_elimination
from .stat_threshold import OPERATORS


@register("standing_count")
async def execute_standing_count(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Count tournaments (or distinct roles) at a standing position. Grain: user.

    params:
        position_op: operator for ``overall_position`` (default "==")
        position_value: position threshold (default 1)
        count_by: "tournament" (default) | "role"
        op: operator for the resulting count
        value: count threshold
        is_league: bool | None (default False) — filter Tournament.is_league
    """
    position_op = params.get("position_op", "==")
    position_value = params.get("position_value", 1)
    count_by = params.get("count_by", "tournament")
    op = params["op"]
    value = params["value"]
    is_league = params.get("is_league", False)

    pos_fn = OPERATORS[position_op]
    op_fn = OPERATORS[op]

    if count_by == "role":
        count_expr = sa.func.count(models.Player.role.distinct())
    else:
        count_expr = sa.func.count(models.Standing.tournament_id.distinct())

    where_clauses = [
        pos_fn(models.Standing.overall_position, position_value),
        standing_is_elimination(standing=models.Standing, stage=models.Stage),
        models.Tournament.workspace_id == context.workspace_id,
        models.Player.is_substitution.is_(False),
    ]
    if is_league is not None:
        where_clauses.append(models.Tournament.is_league.is_(is_league))

    query = (
        sa.select(models.WorkspaceMember.player_id)
        .select_from(models.Standing)
        .join(models.Tournament, models.Tournament.id == models.Standing.tournament_id)
        .outerjoin(models.Stage, models.Stage.id == models.Standing.stage_id)
        .join(
            models.Player,
            sa.and_(
                models.Player.team_id == models.Standing.team_id,
                models.Player.tournament_id == models.Standing.tournament_id,
            ),
        )
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .where(*where_clauses)
        .group_by(models.WorkspaceMember.player_id)
        .having(op_fn(count_expr, value))
    )

    result = await session.execute(query)
    return {(row[0],) for row in result}
