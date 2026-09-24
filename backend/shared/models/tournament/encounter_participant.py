"""A team seated in an FFA lobby (``encounter.format == 'ffa'``).

Rows exist only for lobbies: a duel names its two sides in
``encounter.home_team_id``/``away_team_id`` and has none here (see
docs/plans/2026-09-24-ffa-encounters.md §3, decision 3). The single writer is
tournament-service ``FfaEncounterService``.
"""

from __future__ import annotations

import typing

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.models.tournament.team import Team

if typing.TYPE_CHECKING:
    from shared.models.tournament.encounter import Encounter

__all__ = ("EncounterParticipant",)


class EncounterParticipant(db.TimeStampIntegerMixin):
    __tablename__ = "encounter_participant"
    __table_args__ = (
        UniqueConstraint("encounter_id", "team_id", name="uq_encounter_participant_encounter_team"),
        UniqueConstraint("encounter_id", "slot", name="uq_encounter_participant_encounter_slot"),
        CheckConstraint("slot >= 1", name="ck_encounter_participant_slot"),
        # Named here rather than via ``index=True``: that would auto-name it
        # ``ix_tournament_encounter_participant_team_id`` and drift from the
        # migration, which follows the ``ix_<table>_<cols>`` convention.
        Index("ix_encounter_participant_team_id", "team_id"),
        {"schema": "tournament"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey("tournament.encounter.id", ondelete="CASCADE"))
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"))
    #: Seat in the lobby, in seed order. Display order before any game is played.
    slot: Mapped[int] = mapped_column(Integer())

    encounter: Mapped[Encounter] = relationship(back_populates="participants")
    team: Mapped[Team] = relationship()
