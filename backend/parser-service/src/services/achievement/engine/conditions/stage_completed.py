"""stage_completed — the tournament's stages numbered ``op value`` are all finished.

Stage number = 1-based position in the tournament's stage order (``Stage.order``,
then ``id``), so gaps or duplicates in ``order`` do not shift what "stage 2" means.
``{"op": "<=", "value": 1}`` → the first stage is done (e.g. AND it with
``reached_playoffs`` to award only once the group stage has finished).

Grain: user_tournament.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.achievements.achievement import AchievementGrain
from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS


@register(
    "stage_completed",
    grain=AchievementGrain.user_tournament,
    description="Every stage whose number matches is completed",
    required=("value",),
    optional=("op",),
    depends_on=("tournament.stage", "tournament.player"),
)
async def execute_stage_completed(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    op_fn = OPERATORS[params.get("op", "==")]
    value = params["value"]

    numbered = (
        sa.select(
            models.Stage.tournament_id,
            models.Stage.is_completed,
            sa.func.row_number()
            .over(partition_by=models.Stage.tournament_id, order_by=(models.Stage.order, models.Stage.id))
            .label("number"),
        )
        .join(models.Tournament, models.Tournament.id == models.Stage.tournament_id)
        .where(models.Tournament.workspace_id == context.workspace_id)
    )
    if context.tournament:
        numbered = numbered.where(models.Stage.tournament_id == context.tournament.id)
    numbered_sq = numbered.subquery("numbered_stage")

    # At least one stage must match: no "stage 3" in a two-stage tournament is
    # not a finished stage 3.
    completed_tournaments = (
        sa.select(numbered_sq.c.tournament_id)
        .where(op_fn(numbered_sq.c.number, value))
        .group_by(numbered_sq.c.tournament_id)
        .having(sa.func.min(sa.case((numbered_sq.c.is_completed.is_(True), 1), else_=0)) == 1)
    )
    # Legacy tournaments predate stages; for them "finished" is all there is.
    stageless_finished = sa.and_(
        models.Tournament.is_finished.is_(True),
        ~sa.exists().where(models.Stage.tournament_id == models.Tournament.id),
    )

    query = (
        sa.select(models.WorkspaceMember.player_id, models.Player.tournament_id)
        .select_from(models.Player)
        .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
            sa.or_(models.Tournament.id.in_(completed_tournaments), stageless_finished),
        )
    )
    if context.tournament:
        query = query.where(models.Player.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
