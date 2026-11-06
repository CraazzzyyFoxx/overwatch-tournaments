"""Directed edge describing advancement between encounters.

Bracket structure is explicit: slots fill automatically on
a result change, and the wiring survives a bracket-engine regeneration.

Both ends are POSITIONS, not sides: ``source_position`` is the place in the
source encounter's standing (1 = winner, 2 = loser) and
``target_slot`` is the seat it feeds in the target. The bracket generator checks
``target_slot <= encounter.slot_count``.
"""

from __future__ import annotations

import typing

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if typing.TYPE_CHECKING:
    from shared.models.encounter.encounter import Encounter

__all__ = ("EncounterLink",)


class EncounterLink(db.TimeStampIntegerMixin):
    __tablename__ = "encounter_link"
    __table_args__ = (
        UniqueConstraint("source_encounter_id", "source_position", name="uq_link_source_position"),
        UniqueConstraint("target_encounter_id", "target_slot", name="uq_link_target_slot"),
        ForeignKeyConstraint(
            ["source_encounter_id", "tournament_id"],
            ["encounter.encounter.id", "encounter.encounter.tournament_id"],
            ondelete="CASCADE",
            name="fk_link_source",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        ForeignKeyConstraint(
            ["target_encounter_id", "tournament_id"],
            ["encounter.encounter.id", "encounter.encounter.tournament_id"],
            ondelete="CASCADE",
            name="fk_link_target",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        CheckConstraint("source_encounter_id <> target_encounter_id", name="ck_link_not_self"),
        CheckConstraint("source_position >= 1 AND target_slot >= 1", name="ck_link_positions"),
        {"schema": "tournament"},
    )

    #: Copy of both ends' owner, so the composite FKs can check it.
    tournament_id: Mapped[int] = mapped_column(BigInteger())
    source_encounter_id: Mapped[int] = mapped_column(BigInteger())
    #: Place in the source encounter's final standing.
    source_position: Mapped[int] = mapped_column(Integer())
    target_encounter_id: Mapped[int] = mapped_column(BigInteger())
    #: Seat of the target encounter this edge fills.
    target_slot: Mapped[int] = mapped_column(Integer())

    # Joined on the encounter id alone, although the constraints behind them are
    # the two-column owner keys: a many-to-one on a non-primary key cannot use
    # the identity map and would emit a SELECT on every touch.
    source_encounter: Mapped[Encounter] = relationship(
        primaryjoin="EncounterLink.source_encounter_id == Encounter.id",
        foreign_keys=[source_encounter_id],
    )
    target_encounter: Mapped[Encounter] = relationship(
        primaryjoin="EncounterLink.target_encounter_id == Encounter.id",
        foreign_keys=[target_encounter_id],
    )
