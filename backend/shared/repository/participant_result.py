"""``tournament.participant_result`` access: the replace-all write and the member's tournament row (spec §4.7, §11.4).

The rows themselves are chosen by ``shared.services.participant_result``; this module only stores them.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.orm.util import AliasedClass

from shared import models

__all__ = ("COLUMNS", "ParticipantResultRepository", "is_member_tournament_row", "member_tournament_player_id")

#: The column order a ``replace`` select must yield.
COLUMNS = ("tournament_id", "workspace_member_id", "final_team_id", "placement", "field_size", "source_node_id")


class ParticipantResultRepository:
    async def replace(self, session: AsyncSession, tournament_id: int, rows: sa.Select) -> int:
        """Replace the tournament's rows with ``rows`` (selecting ``COLUMNS``); the inserted count. Flushes first."""
        await session.flush()
        await session.execute(
            sa.delete(models.ParticipantResult).where(models.ParticipantResult.tournament_id == tournament_id)
        )
        # RETURNING, not rowcount: psycopg reports -1 for a bare INSERT ... SELECT.
        result = await session.execute(
            sa.insert(models.ParticipantResult)
            .from_select(list(COLUMNS), rows)
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
