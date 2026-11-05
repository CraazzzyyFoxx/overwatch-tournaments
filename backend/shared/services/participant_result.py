"""``tournament.participant_result``: one row per member of a finished tournament (spec §4.7).

Rule 2: per member, the last-formed team the member played for (substitutes never count; the team of the formation
node completed last, a tournament-wide team after them, then the latest row), the placement being that team's positive
``Standing.overall_position`` in its last stage by ``Stage.order`` (NULL when it never had one), and ``field_size`` the
team count of that team's formation node (the tournament's tournament-wide teams for a tournament-wide team). The migration ``flowP1_participant_result`` carries a frozen copy of the
same SQL for the backfill; keep the two in step. The storage and the member's tournament-row helpers live in
``shared.repository.participant_result``.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.participant_result import ParticipantResultRepository

__all__ = ("write_participant_results",)


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
        sa.select(sa.func.count(models.Team.id))
        .where(
            models.Team.tournament_id == tournament_id,
            models.Team.formation_node_id.is_not_distinct_from(player.formation_node_id),
        )
        .scalar_subquery()
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
        .outerjoin(models.FlowNode, models.FlowNode.id == player.formation_node_id)
        .where(
            player.tournament_id == tournament_id,
            models.Tournament.is_finished.is_(True),
            player.is_substitution.is_(False),
        )
        .distinct(player.workspace_member_id)
        .order_by(player.workspace_member_id, models.FlowNode.completed_at.desc().nulls_last(), player.id.desc())
    )


async def write_participant_results(session: AsyncSession, tournament_id: int) -> int:
    """Replace the tournament's rows with the rule-2 rows; none unless the tournament is finished. Never commits."""
    return await ParticipantResultRepository().replace(session, tournament_id, _team_rule_rows(tournament_id))
