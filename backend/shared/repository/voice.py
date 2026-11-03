"""Tournament voice channels: the organizer's settings and the bot's channel rows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.tournament.voice import TournamentVoiceChannel, TournamentVoiceSettings
from shared.repository.base import BaseRepository

__all__ = ("TournamentVoiceChannelRepository", "TournamentVoiceSettingsRepository")


class TournamentVoiceSettingsRepository(BaseRepository[TournamentVoiceSettings]):
    def __init__(self) -> None:
        super().__init__(TournamentVoiceSettings)

    async def for_tournament(self, session: AsyncSession, tournament_id: int) -> TournamentVoiceSettings | None:
        return await self.get_by(session, tournament_id=tournament_id)

    async def upsert(
        self, session: AsyncSession, tournament_id: int, values: dict[str, Any]
    ) -> TournamentVoiceSettings:
        row = await self.for_tournament(session, tournament_id)
        if row is None:
            return await self.create(session, TournamentVoiceSettings(tournament_id=tournament_id, **values))
        return await self.update_fields(session, row, values)


class TournamentVoiceChannelRepository(BaseRepository[TournamentVoiceChannel]):
    def __init__(self) -> None:
        super().__init__(TournamentVoiceChannel)

    async def for_tournament(self, session: AsyncSession, tournament_id: int) -> Sequence[TournamentVoiceChannel]:
        query = self.select().where(TournamentVoiceChannel.tournament_id == tournament_id)
        return (await session.scalars(query.order_by(TournamentVoiceChannel.id))).all()

    def stage(self, session: AsyncSession, tournament_id: int, slot_key: str) -> TournamentVoiceChannel:
        """A new row joined to the session, written by the caller's next flush (the bot fills it field by field)."""
        row = TournamentVoiceChannel(tournament_id=tournament_id, slot_key=slot_key)
        session.add(row)
        return row

    async def detach(self, session: AsyncSession, discord_channel_id: int) -> None:
        """The channel is gone from Discord: its row goes back to ``pending`` so the next sync recreates it."""
        await session.execute(
            sa.update(TournamentVoiceChannel)
            .where(TournamentVoiceChannel.discord_channel_id == discord_channel_id)
            .values(discord_channel_id=None, status="pending")
        )
