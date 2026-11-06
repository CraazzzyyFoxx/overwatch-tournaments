"""Where an encounter sits in a bracket.

The match layer is game-neutral and owns no tournament structure, so the bracket position lives
with the tournament instead: a mix or a scrim is an encounter with no row here.
``round`` is negative in a double elimination's lower bracket.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKeyConstraint, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = ("BracketEncounter",)


class BracketEncounter(db.Base):
    __tablename__ = "bracket_encounter"
    __table_args__ = (
        Index("ix_bracket_encounter_stage_id", "stage_id"),
        Index("ix_bracket_encounter_stage_item_id", "stage_item_id"),
        ForeignKeyConstraint(
            ["encounter_id", "tournament_id"],
            ["encounter.encounter.id", "encounter.encounter.tournament_id"],
            ondelete="CASCADE",
            name="fk_bracket_encounter",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        # A deleted stage leaves the encounter in place with no position, the
        # way a deleted stage item does.
        ForeignKeyConstraint(
            ["stage_id", "tournament_id"],
            ["tournament.stage.id", "tournament.stage.tournament_id"],
            ondelete="SET NULL (stage_id)",
            name="fk_bracket_stage",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        ForeignKeyConstraint(
            ["stage_item_id", "stage_id"],
            ["tournament.stage_item.id", "tournament.stage_item.stage_id"],
            ondelete="SET NULL (stage_item_id)",
            name="fk_bracket_stage_item",
        ),
        {"schema": "tournament"},
    )

    encounter_id: Mapped[int] = mapped_column(BigInteger(), primary_key=True)
    tournament_id: Mapped[int] = mapped_column(BigInteger())
    stage_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    stage_item_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    round: Mapped[int] = mapped_column(Integer())
