"""One participant's result in one FFA lobby game.

``placement`` is always stored: when the stage's formula pays nothing for
placement it is derived from ``score`` (ties share a place), so "games won" and
"best placement" mean the same for a score-only lobby and a battle royale.
The composite FK to the participant makes a result for a team outside the
lobby impossible.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db
from shared.models.tournament.encounter_game import EncounterGame

__all__ = ("EncounterGameResult",)


class EncounterGameResult(db.TimeStampIntegerMixin):
    __tablename__ = "encounter_game_result"
    __table_args__ = (
        UniqueConstraint("game_id", "team_id", name="uq_encounter_game_result_game_team"),
        CheckConstraint("placement >= 1", name="ck_encounter_game_result_placement"),
        CheckConstraint("score >= 0", name="ck_encounter_game_result_score"),
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
    score: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
