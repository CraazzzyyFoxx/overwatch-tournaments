import typing
from datetime import datetime

from sqlalchemy import Enum, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.tournament.stage import Stage, StageItem
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament

if typing.TYPE_CHECKING:
    from shared.models.matches.match import Match
    from shared.models.tournament.encounter_game import EncounterGame
    from shared.models.tournament.encounter_report import EncounterCaptainReport
    from shared.models.tournament.encounter_result_audit import EncounterResultAudit

__all__ = ("Encounter",)


ENCOUNTER_RESULT_STATUS_ENUM = Enum(
    enums.EncounterResultStatus,
    values_callable=lambda e: [x.value for x in e],
    name="encounterresultstatus",
    schema="tournament",
    create_type=False,
)

# NB: deliberately NO values_callable — this type has always persisted the
# member NAMEs (COMPLETED/PENDING/OPEN), not the lowercase .value (see the
# status column comment below). Lives in the tournament schema since dbarch01
# moved it out of public (where a7634c02717d originally created it).
ENCOUNTER_STATUS_ENUM = Enum(
    enums.EncounterStatus,
    name="encounterstatus",
    schema="tournament",
    create_type=False,
)


class Encounter(db.TimeStampIntegerMixin):
    __tablename__ = "encounter"

    __table_args__ = (
        # Created CONCURRENTLY by perfidx04: status is filtered on 10+ read
        # paths (live/upcoming feeds, standings, Challonge export).
        Index("ix_encounter_tournament_status", "tournament_id", "status"),
        Index(
            "ix_encounter_status_live_upcoming",
            "tournament_id",
            "status",
            # NB: predicate uses uppercase enum NAMEs; the type lives in the
            # tournament schema since dbarch01 (see the status column comment
            # below). The DB index created by perfidx04 with a
            # public.encounterstatus cast keeps working after the move — pg
            # stores type OIDs, not names, in index predicates.
            postgresql_where=text(
                "status IN ('PENDING'::tournament.encounterstatus, 'OPEN'::tournament.encounterstatus)"
            ),
        ),
        {"schema": "tournament"},
    )

    name: Mapped[str] = mapped_column(String())
    home_team_id: Mapped[int | None] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), nullable=True, index=True)
    away_team_id: Mapped[int | None] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), nullable=True, index=True)
    home_score: Mapped[int] = mapped_column(Integer())
    away_score: Mapped[int] = mapped_column(Integer())

    round: Mapped[int] = mapped_column(Integer(), index=True)
    closeness: Mapped[float | None] = mapped_column(Float(), nullable=True)
    best_of: Mapped[int] = mapped_column(Integer(), default=3, server_default="3")
    scheduled_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    current_map_index: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey(Stage.id, ondelete="SET NULL"), nullable=True, index=True)
    stage_item_id: Mapped[int | None] = mapped_column(
        ForeignKey(StageItem.id, ondelete="SET NULL"), nullable=True, index=True
    )
    # ENCOUNTER_STATUS_ENUM persists the member NAME (COMPLETED/PENDING/OPEN), not
    # its .value (completed/pending/open) — there is no values_callable, so any
    # raw SQL/partial-index predicate against `status` must use the uppercase NAME
    # labels (see migrations/versions/perfidx04_encounter_status_indexes.py). The
    # underlying `encounterstatus` type was created in public by a7634c02717d and
    # stranded there when b8e2f4a1c903 moved `encounter` to `tournament` (ALTER
    # TABLE ... SET SCHEMA does not move dependent types); dbarch01 finally moved
    # it into the tournament schema.
    status: Mapped[enums.EncounterStatus] = mapped_column(ENCOUNTER_STATUS_ENUM, default=enums.EncounterStatus.OPEN)

    if typing.TYPE_CHECKING:
        # Derived from ``Match`` existence via ``column_property`` after
        # ``Match`` is defined (see ``shared/models/matches/match.py``).
        has_logs: Mapped[bool]

    # Captain result submission
    result_status: Mapped[enums.EncounterResultStatus] = mapped_column(
        ENCOUNTER_RESULT_STATUS_ENUM,
        default=enums.EncounterResultStatus.NONE,
        server_default=enums.EncounterResultStatus.NONE.value,
    )
    # ``confirmed_at`` is the only provenance kept on the row: it is the sole
    # timestamp an admin confirmation with zero captain reports leaves behind,
    # and lists sort/filter on it without joining the audit. Who did it — and
    # every earlier decision — lives in ``result_audit``; the old
    # submitted_by_id/submitted_at/confirmed_by_id slots had no readers and
    # forgot everything but the last writer.
    confirmed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)

    tournament: Mapped[Tournament] = relationship()
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])
    stage: Mapped[Stage | None] = relationship()
    stage_item: Mapped[StageItem | None] = relationship()
    result_audit: Mapped[list[EncounterResultAudit]] = relationship(
        back_populates="encounter",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EncounterResultAudit.created_at.desc()",
    )
    # Same shape as the two collections around it, and for the same reason:
    # ``Match.encounter_id`` is NOT NULL, so the default cascade -- which nulls a
    # child's foreign key when the parent goes -- made ``delete_encounter`` emit
    # ``UPDATE matches.match SET encounter_id = NULL`` and die on the constraint.
    # ``passive_deletes`` hands the job to the ``ON DELETE CASCADE`` the column
    # already carries (and every ``match_id`` child carries in turn), so deleting
    # an encounter never loads its series just to rewrite it.
    matches: Mapped[list[Match]] = relationship(
        back_populates="encounter",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    captain_reports: Mapped[list[EncounterCaptainReport]] = relationship(
        back_populates="encounter",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    games: Mapped[list[EncounterGame]] = relationship(
        back_populates="encounter",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EncounterGame.position",
    )
