"""``tournament.participant_result``: one row per member of a finished tournament (spec §4.7).

Rule 2: per member, the last-formed team the member played for (substitutes never count), the placement being that
team's positive ``Standing.overall_position`` in its last stage by ``Stage.order`` (NULL when it never had one), and
``field_size`` the tournament's team count. The migration ``flowP1_participant_result`` carries a frozen copy of the
same SQL for the backfill; keep the two in step.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.orm.util import AliasedClass

from shared import models

__all__ = ("is_member_tournament_row", "member_tournament_player_id", "write_participant_results")

_COLUMNS = ("tournament_id", "workspace_member_id", "final_team_id", "placement", "field_size", "source_node_id")


def _team_rule_rows(tournament_id: int) -> sa.Select:
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
    await session.flush()
    await session.execute(
        sa.delete(models.ParticipantResult).where(models.ParticipantResult.tournament_id == tournament_id)
    )
    # RETURNING, not rowcount: psycopg reports -1 for a bare INSERT ... SELECT.
    result = await session.execute(
        sa.insert(models.ParticipantResult)
        .from_select(list(_COLUMNS), _team_rule_rows(tournament_id))
        .returning(models.ParticipantResult.workspace_member_id)
    )
    return len(result.all())


def member_tournament_player_id(player: type[models.Player] | AliasedClass = models.Player) -> sa.ScalarSelect[int]:
    """The id of the member's tournament row: the final team's, else the latest non-substitute row (spec §11.4)."""
    other, result = aliased(models.Player), models.ParticipantResult
    return (
        sa.select(other.id)
        .outerjoin(
            result,
            sa.and_(
                result.tournament_id == other.tournament_id,
                result.workspace_member_id == other.workspace_member_id,
            ),
        )
        .where(
            other.workspace_member_id == player.workspace_member_id,
            other.tournament_id == player.tournament_id,
        )
        .order_by(
            sa.func.coalesce(other.team_id == result.final_team_id, False).desc(),
            other.is_substitution.asc(),
            other.id.desc(),
        )
        .limit(1)
        .correlate_except(other, result)
        .scalar_subquery()
    )


def is_member_tournament_row(player: type[models.Player] | AliasedClass = models.Player) -> sa.ColumnElement[bool]:
    return player.id == member_tournament_player_id(player)
