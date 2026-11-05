"""standing_position / standing_record â€” tournament standings conditions."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.disciplines.overwatch.achievements.stage_filters import (
    stage_is_completed,
    standing_is_elimination,
    standing_is_groups,
)
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain
from shared.services.participant_result import is_member_tournament_row

from . import ResultSet, one_of, register
from .stat_threshold import OPERATORS


def _standing_base_query() -> sa.Select:
    return (
        sa.select(
            models.WorkspaceMember.player_id,
            models.Standing.tournament_id,
        )
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
    )


@register(
    "standing_position",
    grain=AchievementGrain.user_tournament,
    description="Final standing position in the tournament",
    required=("op", "value"),
    depends_on=("tournament.participant_result",),
)
async def execute_position(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    result_row = models.ParticipantResult
    query = (
        sa.select(models.WorkspaceMember.player_id, result_row.tournament_id)
        .select_from(result_row)
        .join(models.WorkspaceMember, models.WorkspaceMember.id == result_row.workspace_member_id)
        .join(models.Tournament, models.Tournament.id == result_row.tournament_id)
        .where(
            OPERATORS[params["op"]](result_row.placement, params["value"]),
            sa.and_(
                models.Tournament.workspace_id == context.workspace_id,
                models.Tournament.discipline == context.discipline,
            ),
        )
    )
    if context.tournament:
        query = query.where(result_row.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}


@register(
    "standing_record",
    grain=AchievementGrain.user_tournament,
    description="Win/loss/draw record on a standings row",
    required=("field", "op", "value"),
    optional=("groups_only", "include_groups"),
    validate_params=one_of(field=("wins", "losses", "draws", "points", "buchholz", "matches")),
    depends_on=("tournament.stage", "tournament.standing", "tournament.player", "tournament.participant_result"),
)
async def execute_record(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Check standing record fields: wins, losses, draws, points, buchholz.

    Stage targeting:
        groups_only=True → only group-stage standings (round-robin/swiss/legacy groups).
        include_groups=True → both group and elimination standings.
        default → elimination/bracket standings only.
    """
    field = params["field"]
    op = params["op"]
    value = params["value"]
    include_groups = params.get("include_groups", False)
    groups_only = params.get("groups_only", False)

    column_map = {
        "wins": models.Standing.win,
        "losses": models.Standing.lose,
        "draws": models.Standing.draw,
        "points": models.Standing.points,
        "buchholz": models.Standing.buchholz,
        "matches": models.Standing.matches,
    }
    column = column_map[field]
    op_fn = OPERATORS[op]

    where_clauses = [
        op_fn(column, value),
        sa.and_(
            models.Tournament.workspace_id == context.workspace_id, models.Tournament.discipline == context.discipline
        ),
        models.Player.is_substitution.is_(False),
        stage_is_completed(stage=models.Stage),
    ]
    if groups_only:
        where_clauses.append(
            standing_is_groups(
                standing=models.Standing,
                stage=models.Stage,
            )
        )
    elif not include_groups:
        where_clauses.append(
            standing_is_elimination(
                standing=models.Standing,
                stage=models.Stage,
            )
        )

    query = _standing_base_query().where(is_member_tournament_row(), *where_clauses)

    if context.tournament:
        query = query.where(models.Standing.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
