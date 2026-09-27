"""One participant's result in one FFA lobby game.

``stats`` is what the organizer's columns collected for this team in this game
(``{"kills": 12, "deaths": 3}``); the points it pays are never stored -- the
stage's formula computes them on every read (plan §2). ``placement`` is always
stored: when the formula pays nothing for placement it is derived from the
game's points (ties share a place), so "games won" and "best placement" mean
the same for a score-only lobby and a battle royale. The composite FK to the
participant makes a result for a team outside the lobby impossible.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db
from shared.models.tournament.encounter_game import EncounterGame

__all__ = ("EncounterGameResult",)


class EncounterGameResult(db.TimeStampIntegerMixin):
    __tablename__ = "encounter_game_result"
    __table_args__ = (
        UniqueConstraint("game_id", "team_id", name="uq_encounter_game_result_game_team"),
        CheckConstraint("placement >= 1", name="ck_encounter_game_result_placement"),
        CheckConstraint("jsonb_typeof(stats) = 'object'", name="ck_encounter_game_result_stats"),
        ForeignKeyConstraint(
            ["encounter_id", "team_id"],
            ["tournament.encounter_participant.encounter_id", "tournament.encounter_participant.team_id"],
            ondelete="CASCADE",
            name="fk_encounter_game_result_participant",
        ),
        Index("ix_encounter_game_result_encounter_team", "encounter_id", "team_id"),
        {"schema": "tournament"},
    )

    game_id: Mapped[int] = mapped_column(ForeignKey(EncounterGame.id, ondelete="CASCADE"))
    encounter_id: Mapped[int] = mapped_column(BigInteger())
    team_id: Mapped[int] = mapped_column(BigInteger())
    placement: Mapped[int] = mapped_column(Integer())
    #: The organizer's columns for this team in this game; a key the stage does
    #: not have is simply absent, and an absent key reads as 0 (plan §3.2).
    stats: Mapped[dict[str, float]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
