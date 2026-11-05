"""tournament_winrate — per-tournament team winrate threshold.

Grain: user_tournament.

The player's team winrate within a single
tournament must meet a threshold. Typically combined (AND) with
``standing_position`` to express "won the tournament with a high winrate".
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
from shared.services.participant_result import is_member_tournament_row

from . import ResultSet, register
from .stat_threshold import OPERATORS


@register(
    "tournament_winrate",
    grain=AchievementGrain.user_tournament,
    description="Series winrate inside one tournament",
    required=("op", "value"),
    depends_on=("tournament.encounter", "tournament.player", "tournament.participant_result"),
)
async def execute_tournament_winrate(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Team winrate within a tournament meets a threshold. Grain: user_tournament.

    params:
        op: comparison operator
        value: winrate threshold (0.0–1.0)
    """
    op = params["op"]
    value = params["value"]
    op_fn = OPERATORS[op]

    # The team's own score over the score of everyone seated in the encounter.
    seat = sa.orm.aliased(models.EncounterTeam, name="seat")
    winrate = sa.func.sum(seat.score) / sa.func.nullif(sa.func.sum(series_total()), 0)

    query = (
        sa.select(models.WorkspaceMember.player_id, models.Player.tournament_id)
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(seat, sa.and_(seat.team_id == models.Team.id, seat.active.is_(True)))
        .join(models.Encounter, models.Encounter.id == seat.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Player.is_substitution.is_(False),
            is_member_tournament_row(),
            sa.and_(
                models.Tournament.workspace_id == context.workspace_id,
                models.Tournament.discipline == context.discipline,
            ),
            models.Encounter.status == EncounterStatus.COMPLETED,
        )
        .group_by(models.WorkspaceMember.player_id, models.Player.tournament_id)
        .having(op_fn(winrate, value))
    )

    if context.tournament:
        query = query.where(models.Player.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
