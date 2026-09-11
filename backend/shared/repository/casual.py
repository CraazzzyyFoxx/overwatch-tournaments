from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from shared import models
from shared.core import enums
from shared.repository.base import BaseRepository

__all__ = ("CasualMatchRepository", "CasualTeamRepository", "CasualPlayerRepository")


class CasualMatchRepository(BaseRepository[models.CasualMatch]):
    def __init__(self) -> None:
        super().__init__(models.CasualMatch)

    async def list_for_custom_game(self, session: AsyncSession, custom_game_id: int) -> Sequence[models.CasualMatch]:
        """Newest-first, with both scored sides and their frozen seats loaded.

        Eager, not lazy: an async session raises on an unawaited lazy load, and
        both readers of this need the whole snapshot -- the history view for
        names and scores, the rotation recommender for who actually played.
        """
        result = await session.scalars(
            self.select()
            .where(self.model.custom_game_id == custom_game_id)
            .options(selectinload(self.model.teams).selectinload(models.CasualTeam.players))
            .order_by(self.model.id.desc())
        )
        return result.all()

    async def get_for_game(
        self, session: AsyncSession, custom_game_id: int, match_id: int
    ) -> models.CasualMatch | None:
        """One match of this mix, or ``None`` when it belongs to another mix.

        Ownership is part of the lookup rather than a check afterwards, so a
        match id guessed from another workspace reads as "not found" instead of
        being loaded and then rejected. Same eager loads as the list read: undo
        walks both sides' frozen seats.
        """
        return await session.scalar(
            self.select()
            .where(self.model.custom_game_id == custom_game_id, self.model.id == match_id)
            .options(selectinload(self.model.teams).selectinload(models.CasualTeam.players))
        )

    async def newest_id_for_game(self, session: AsyncSession, custom_game_id: int) -> int | None:
        """Id of the most recently recorded match, or ``None`` for a mix with none."""
        return await session.scalar(
            sa.select(sa.func.max(self.model.id)).where(self.model.custom_game_id == custom_game_id)
        )

    async def activity_for_games(
        self, session: AsyncSession, custom_game_ids: Sequence[int]
    ) -> dict[int, tuple[int, datetime]]:
        """``custom_game_id -> (matches recorded, when the newest one was)``.

        One grouped query for a whole list of mixes: the mix list shows this per
        row, and per-row counting would be a query per mix. A mix with no
        matches is simply absent from the result.
        """
        if not custom_game_ids:
            return {}
        rows = await session.execute(
            sa.select(
                self.model.custom_game_id,
                sa.func.count().label("matches"),
                sa.func.max(self.model.created_at).label("last_at"),
            )
            .where(self.model.custom_game_id.in_(custom_game_ids))
            .group_by(self.model.custom_game_id)
        )
        return {row.custom_game_id: (row.matches, row.last_at) for row in rows}

    async def seats_for_workspace(
        self, session: AsyncSession, workspace_id: int, since: datetime | None = None
    ) -> Sequence[sa.Row[tuple[int, enums.HeroClass | None, int, datetime, int, int]]]:
        """One row per recorded seat in this workspace's mixes, oldest match first.

        Self-joins ``casual.team`` because a seat's result is relative: the
        match stores two scored sides and no winner flag, so the only way to
        say "this seat won" in SQL is to carry the *other* side's score on the
        same row. The pair is unique -- a match has exactly two sides
        (``uq_casual_team_match_side``) -- so this never fans a seat out.

        Seats whose member FK was nulled by a departure are dropped: the
        scoreboard is keyed by workspace member, and a seat with no member has
        nobody to credit. ``since`` filters on the match, not the seat, so a
        window always cuts whole matches.
        """
        other = aliased(models.CasualTeam)
        stmt = (
            sa.select(
                models.CasualPlayer.workspace_member_id,
                models.CasualPlayer.role,
                models.CasualMatch.id.label("match_id"),
                models.CasualMatch.created_at,
                models.CasualTeam.score.label("own_score"),
                other.score.label("other_score"),
            )
            .select_from(models.CasualPlayer)
            .join(models.CasualTeam, models.CasualPlayer.team_id == models.CasualTeam.id)
            .join(models.CasualMatch, models.CasualTeam.match_id == models.CasualMatch.id)
            .join(models.CustomGame, models.CasualMatch.custom_game_id == models.CustomGame.id)
            .join(other, sa.and_(other.match_id == models.CasualMatch.id, other.id != models.CasualTeam.id))
            .where(
                models.CustomGame.workspace_id == workspace_id,
                models.CasualPlayer.workspace_member_id.is_not(None),
            )
            .order_by(models.CasualMatch.id, models.CasualPlayer.id)
        )
        if since is not None:
            stmt = stmt.where(models.CasualMatch.created_at >= since)
        result = await session.execute(stmt)
        return result.all()


class CasualTeamRepository(BaseRepository[models.CasualTeam]):
    def __init__(self) -> None:
        super().__init__(models.CasualTeam)


class CasualPlayerRepository(BaseRepository[models.CasualPlayer]):
    def __init__(self) -> None:
        super().__init__(models.CasualPlayer)
