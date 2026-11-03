"""Tournament voice channels: the organizer's settings and the bot's record of what it made in Discord.

``voice_settings`` is written by tournament-service (admin). ``voice_channel`` is written by
discord-service alone: it is the bot's view of what exists, diffed against tournament-service's
``rpc.tournament.voice_plan`` on every sync. See ``docs/tournament-voice-channels.md``.
"""

from __future__ import annotations

import typing
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if typing.TYPE_CHECKING:
    from shared.models.tournament.tournament import Tournament

__all__ = ("TournamentVoiceChannel", "TournamentVoiceSettings")


class TournamentVoiceSettings(db.TimeStampIntegerMixin):
    __tablename__ = "voice_settings"
    __table_args__ = ({"schema": "tournament"},)

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false")
    #: Team voices hidden from ``@everyone``; the roster, ``staff_role_ids`` and the bot get access.
    private: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false")
    #: Team voices before any stage was activated (the admin's "create now", e.g. for check-in).
    early_teams: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false")
    #: An existing Discord category to put the voices in; NULL = the bot creates its own.
    category_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    staff_role_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger()), nullable=False, server_default=text("'{}'::bigint[]")
    )
    # Written by discord-service after each sync.
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ``[{"code": str, "detail": str | None}]`` -- what the last sync could not do (missing permission, ...).
    sync_issues: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    tournament: Mapped[Tournament] = relationship()


class TournamentVoiceChannel(db.TimeStampIntegerMixin):
    __tablename__ = "voice_channel"
    __table_args__ = (
        UniqueConstraint("tournament_id", "slot_key", name="uq_voice_channel_slot"),
        CheckConstraint("kind IN ('category', 'hub', 'team', 'swiss_slot')", name="ck_voice_channel_kind"),
        CheckConstraint("status IN ('pending', 'active', 'deleting')", name="ck_voice_channel_status"),
        {"schema": "tournament"},
    )

    # ``uq_voice_channel_slot`` leads with tournament_id: no separate index.
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"), nullable=False
    )
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("tournament.stage.id", ondelete="SET NULL"), nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("tournament.team.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The plan's stable key: ``hub``, ``team:<team_id>``, ``slot:<stage_id>:<index>``, ``category:<n>``.
    slot_key: Mapped[str] = mapped_column(String(64), nullable=False)
    #: NULL while ``pending`` (not created in Discord yet).
    discord_channel_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True, unique=True)
    #: False for the organizer's existing category: the bot never deletes what it did not create.
    owned: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    #: When the plan dropped this channel; it is deleted once empty or 10 minutes after.
    delete_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tournament: Mapped[Tournament] = relationship()

    def __repr__(self) -> str:
        return f"<TournamentVoiceChannel {self.slot_key} channel={self.discord_channel_id} status={self.status}>"
