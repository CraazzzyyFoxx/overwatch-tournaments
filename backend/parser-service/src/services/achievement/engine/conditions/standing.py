"""standing_position / standing_record â€” tournament standings conditions."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from ._stage_filters import standing_is_elimination, standing_is_groups
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


@register("standing_position")
async def execute_position(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    op = params["op"]
    value = params["value"]
    op_fn = OPERATORS[op]
    include_groups = params.get("include_groups", False)

    where_clauses = [
        op_fn(models.Standing.overall_position, value),
        models.Tournament.workspace_id == context.workspace_id,
        models.Player.is_substitution.is_(False),
    ]
    if not include_groups:
        where_clauses.append(
            standing_is_elimination(
                standing=models.Standing,
                stage=models.Stage,
            )
        )

    query = _standing_base_query().where(*where_clauses)

    if context.tournament:
        query = query.where(models.Standing.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}


@register("standing_record")
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
        models.Tournament.workspace_id == context.workspace_id,
        models.Player.is_substitution.is_(False),
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

    query = _standing_base_query().where(*where_clauses)

    if context.tournament:
        query = query.where(models.Standing.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
