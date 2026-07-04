from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.stage import Stage, StageItem
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament, TournamentGroup

__all__ = (
    "ChallongeSource",
    "ChallongeParticipantMapping",
    "ChallongeMatchMapping",
    "ChallongeSyncLog",
    "ChallongeTeam",
)


class ChallongeSource(db.TimeStampIntegerMixin):
    __tablename__ = "challonge_source"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "challonge_tournament_id",
            name="uq_challonge_source_tournament_challonge",
        ),
        Index("ix_challonge_source_tournament", "tournament_id"),
        Index("ix_challonge_source_stage", "stage_id"),
        Index("ix_challonge_source_stage_item", "stage_item_id"),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE")
    )
    stage_id: Mapped[int | None] = mapped_column(
        ForeignKey(Stage.id, ondelete="SET NULL"), nullable=True
    )
    stage_item_id: Mapped[int | None] = mapped_column(
        ForeignKey(StageItem.id, ondelete="SET NULL"), nullable=True
    )
    challonge_tournament_id: Mapped[int] = mapped_column(Integer())
    slug: Mapped[str | None] = mapped_column(String(), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="tournament")

    tournament: Mapped[Tournament] = relationship()
    stage: Mapped[Stage | None] = relationship()
    stage_item: Mapped[StageItem | None] = relationship()


class ChallongeParticipantMapping(db.TimeStampIntegerMixin):
    __tablename__ = "challonge_participant_mapping"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "challonge_participant_id",
            name="uq_challonge_participant_mapping_source_participant",
        ),
        Index("ix_challonge_participant_mapping_source", "source_id"),
        Index("ix_challonge_participant_mapping_team", "team_id"),
        {"schema": "tournament"},
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.challonge_source.id", ondelete="CASCADE")
    )
    challonge_participant_id: Mapped[int] = mapped_column(Integer())
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"))

    source: Mapped[ChallongeSource] = relationship()
    team: Mapped[Team] = relationship()


class ChallongeMatchMapping(db.TimeStampIntegerMixin):
    __tablename__ = "challonge_match_mapping"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "challonge_match_id",
            name="uq_challonge_match_mapping_source_match",
        ),
        UniqueConstraint(
            "source_id",
            "encounter_id",
            name="uq_challonge_match_mapping_source_encounter",
        ),
        Index("ix_challonge_match_mapping_source", "source_id"),
        Index("ix_challonge_match_mapping_encounter", "encounter_id"),
        {"schema": "tournament"},
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.challonge_source.id", ondelete="CASCADE")
    )
    challonge_match_id: Mapped[int] = mapped_column(Integer())
    encounter_id: Mapped[int] = mapped_column(
        ForeignKey(Encounter.id, ondelete="CASCADE")
    )

    source: Mapped[ChallongeSource] = relationship()
    encounter: Mapped[Encounter] = relationship()


class ChallongeSyncLog(db.TimeStampIntegerMixin):
    __tablename__ = "challonge_sync_log"
    __table_args__ = (
        # Created CONCURRENTLY by dbarch01: serves the sync-log feed
        # (WHERE tournament_id = ? ORDER BY created_at DESC LIMIT 50) directly.
        Index(
            "ix_challonge_sync_log_tournament_created",
            "tournament_id",
            text("created_at DESC"),
        ),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.challonge_source.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    direction: Mapped[str] = mapped_column(String(10))  # "import" or "export"
    operation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(32))  # tournament, participant, match
    entity_id: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    challonge_id: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # success, failed, conflict
    conflict_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)

    tournament: Mapped[Tournament] = relationship()
    source: Mapped[ChallongeSource | None] = relationship()


class ChallongeTeam(db.TimeStampIntegerMixin):
    """DEPRECATED (Challonge consolidation): superseded by ChallongeParticipantMapping
    (source_id -> challonge_participant_id -> team_id). Still dual-written and read as a
    resolver fallback by both tournament-service and parser-service. Kept until the gated
    migration dbarch04b_challonge_drop_legacy is applied on prod (see its docstring)."""

    __tablename__ = "challonge_team"
    __table_args__ = (
        # FK indexes created CONCURRENTLY by perfidx03 (team_id is hit by the
        # Challonge export's selectinload(Team.challonge) WHERE team_id IN (...)).
        Index("ix_tournament_challonge_team_team_id", "team_id"),
        Index("ix_tournament_challonge_team_tournament_id", "tournament_id"),
        Index("ix_tournament_challonge_team_group_id", "group_id"),
        {"schema": "tournament"},
    )

    challonge_id: Mapped[int] = mapped_column(Integer())
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"))
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey(TournamentGroup.id, ondelete="CASCADE"), nullable=True
    )
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE")
    )

    team: Mapped[Team] = relationship(back_populates="challonge")
    group: Mapped[TournamentGroup] = relationship()
    tournament: Mapped[Tournament] = relationship()
