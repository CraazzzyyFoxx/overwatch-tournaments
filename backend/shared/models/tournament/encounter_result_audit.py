"""Append-only trail of every change to an encounter's result.

Replaces the ``submitted_by_id``/``confirmed_by_id`` slots that used to sit on
``tournament.encounter``: those recorded only the last writer, had no readers,
and silently forgot that an encounter had been reopened and re-confirmed. Since
an admin can now reopen a confirmed result, "who decided this" is a history, not
a single value.

Rows are written by every finalization path and never updated or deleted; the
encounter's ``ON DELETE CASCADE`` is the only thing that removes them. A NULL
``actor_user_id`` means a machine actor (Challonge import, bracket cascade).
"""

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.identity.user import User
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.team import Team

__all__ = ("EncounterResultAudit",)


ENCOUNTER_RESULT_AUDIT_ACTION_ENUM = Enum(
    enums.EncounterResultAuditAction,
    values_callable=lambda e: [x.value for x in e],
    name="encounterresultauditaction",
    schema="tournament",
    create_type=False,
)

# Mirrors the ``result_status`` column's type — reused, not redeclared, so the
# audit can never drift from the states it records.
ENCOUNTER_RESULT_STATUS_ENUM = Enum(
    enums.EncounterResultStatus,
    values_callable=lambda e: [x.value for x in e],
    name="encounterresultstatus",
    schema="tournament",
    create_type=False,
)


class EncounterResultAudit(db.TimeStampIntegerMixin):
    """One transition of an encounter's result."""

    __tablename__ = "encounter_result_audit"
    __table_args__ = (
        # Every read is "the history of this encounter", newest first.
        Index("ix_encounter_result_audit_encounter_created", "encounter_id", "created_at"),
        # An FFA row carries no series score: the lobby's truth is the snapshot.
        CheckConstraint(
            "(home_score_after IS NOT NULL AND away_score_after IS NOT NULL) OR ffa_results_json IS NOT NULL",
            name="ck_encounter_result_audit_after_shape",
        ),
        {"schema": "tournament"},
    )

    # No standalone index: the composite (encounter_id, created_at) below already
    # serves every lookup, and this table only grows.
    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"))
    # NULL = machine actor. SET NULL so a deleted account leaves the trail intact.
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey(User.id, ondelete="SET NULL"), nullable=True)
    action: Mapped[enums.EncounterResultAuditAction] = mapped_column(ENCOUNTER_RESULT_AUDIT_ACTION_ENUM)

    from_result_status: Mapped[enums.EncounterResultStatus | None] = mapped_column(
        ENCOUNTER_RESULT_STATUS_ENUM, nullable=True
    )
    to_result_status: Mapped[enums.EncounterResultStatus] = mapped_column(ENCOUNTER_RESULT_STATUS_ENUM)

    home_score_before: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    away_score_before: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    home_score_after: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    away_score_after: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    #: Snapshot of the lobby's results before/after the decision; stands in for
    #: the score on FFA rows, NULL on duel rows.
    ffa_results_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Which side's report was taken as truth, when the admin adopted one.
    adopted_team_id: Mapped[int | None] = mapped_column(ForeignKey(Team.id, ondelete="SET NULL"), nullable=True)
    # Per-game decisions (actions game_confirm/game_correct/game_cancel): which
    # game, and its result_version AFTER the write. For those rows
    # home/away_score_before/after carry the GAME's accepted score, not the
    # series score. NULL for series-level rows.
    game_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.encounter_game.id", ondelete="CASCADE"), nullable=True, index=True
    )
    game_result_version: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # Admin's stated reason for a correction/cancel; NULL for automatic rows.
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # Mirrors shared.services.encounter.finalize.FinalizeSource.
    source: Mapped[str] = mapped_column(String(16))

    encounter: Mapped[Encounter] = relationship(back_populates="result_audit")
    actor: Mapped[User | None] = relationship()
    adopted_team: Mapped[Team | None] = relationship()
