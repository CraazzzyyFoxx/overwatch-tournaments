"""``tournament.participant_result``: one row per member of a finished tournament (spec §4.7).

Rule 2: per member, the last-formed team the member played for (substitutes never count), the placement being that
team's positive ``Standing.overall_position`` in its last stage by ``Stage.order`` (NULL when it never had one), and
``field_size`` the tournament's team count. The migration ``flowP1_participant_result`` carries a frozen copy of the
same SQL for the backfill; keep the two in step. The storage and the member's tournament-row helpers live in
``shared.repository.participant_result`` (repositories cannot import services) and are re-exported here.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.participant_result import (
    ParticipantResultRepository,
    is_member_tournament_row,
    member_tournament_player_id,
)

__all__ = ("is_member_tournament_row", "member_tournament_player_id", "write_participant_results")


def _team_rule_rows(tournament_id: int) -> sa.Select:
    """One select in ``ParticipantResultRepository`` column order (``COLUMNS``)."""
    player, standing, stage = models.Player, models.Standing, models.Stage
    placement = (
        sa.select(standing.overall_position)
        .outerjoin(stage, stage.id == standing.stage_id)
        .where(standing.team_id == player.team_id, standing.overall_position > 0)
        .order_by(stage.order.desc().nulls_last(), standing.stage_id.desc().nulls_last(), standing.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    field_size = (
        sa.select(sa.func.count(models.Team.id)).where(models.Team.tournament_id == tournament_id).scalar_subquery()
    )
    return (
        sa.select(
            player.tournament_id,
            player.workspace_member_id,
            player.team_id,
            placement,
            field_size,
            sa.cast(sa.null(), sa.BigInteger),
        )
        .join(models.Tournament, models.Tournament.id == player.tournament_id)
        .where(
            player.tournament_id == tournament_id,
            models.Tournament.is_finished.is_(True),
            player.is_substitution.is_(False),
        )
        # shortcut: "last-formed" = latest Player.id while every team has a NULL formation; P3 orders by formation.
        .distinct(player.workspace_member_id)
        .order_by(player.workspace_member_id, player.id.desc())
    )


async def write_participant_results(session: AsyncSession, tournament_id: int) -> int:
    """Replace the tournament's rows with the rule-2 rows; none unless the tournament is finished. Never commits."""
    return await ParticipantResultRepository().replace(session, tournament_id, _team_rule_rows(tournament_id))
