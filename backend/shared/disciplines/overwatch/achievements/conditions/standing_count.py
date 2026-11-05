"""standing_count — count tournaments/roles where a final standing matches.

Grain: user (global).

Counts how many
tournaments (or distinct roles across tournaments) a user finished a given
position in, from the member's ``participant_result`` row.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain

from . import ResultSet, register
from .stat_threshold import OPERATORS


@register(
    "standing_count",
    grain=AchievementGrain.user,
    description="How many times a standing position was reached",
    required=("op", "value"),
    optional=("count_by", "is_league", "position_op", "position_value"),
    depends_on=("tournament.participant_result", "tournament.player"),
)
async def execute_standing_count(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Count tournaments (or distinct roles) at a standing position. Grain: user.

    params:
        position_op: operator for the member's final ``placement`` (default "==")
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

    result_row = models.ParticipantResult
    if count_by == "role":
        count_expr = sa.func.count(models.Player.role.distinct())
    else:
        count_expr = sa.func.count(result_row.tournament_id.distinct())

    where_clauses = [
        pos_fn(result_row.placement, position_value),
        sa.and_(
            models.Tournament.workspace_id == context.workspace_id, models.Tournament.discipline == context.discipline
        ),
    ]
    if is_league is not None:
        where_clauses.append(models.Tournament.is_league.is_(is_league))

    query = (
        sa.select(models.WorkspaceMember.player_id)
        .select_from(result_row)
        .join(models.Tournament, models.Tournament.id == result_row.tournament_id)
        .join(
            models.Player,
            sa.and_(
                models.Player.tournament_id == result_row.tournament_id,
                models.Player.workspace_member_id == result_row.workspace_member_id,
                models.Player.team_id == result_row.final_team_id,
            ),
        )
        .join(models.WorkspaceMember, models.WorkspaceMember.id == result_row.workspace_member_id)
        .where(*where_clauses)
        .group_by(models.WorkspaceMember.player_id)
        .having(op_fn(count_expr, value))
    )

    result = await session.execute(query)
    return {(row[0],) for row in result}
