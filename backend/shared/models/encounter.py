import typing
from datetime import datetime

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.stage import Stage, StageItem
from shared.models.team import Team
from shared.models.tournament import Tournament, TournamentGroup
from shared.models.user import User

if typing.TYPE_CHECKING:
    from shared.models.match import Match

__all__ = ("Encounter",)


ENCOUNTER_RESULT_STATUS_ENUM = Enum(
    enums.EncounterResultStatus,
    values_callable=lambda e: [x.value for x in e],
    name="encounterresultstatus",
    schema="tournament",
    create_type=False,
)


class Encounter(db.TimeStampIntegerMixin):
    __tablename__ = "encounter"

    __table_args__ = (
        Index("ix_encounter_tournament_group", "tournament_id", "tournament_group_id"),
        {"schema": "tournament"},
    )

    name: Mapped[str] = mapped_column(String())
    home_team_id: Mapped[int | None] = mapped_column(
        ForeignKey(Team.id, ondelete="CASCADE"), nullable=True, index=True
    )
    away_team_id: Mapped[int | None] = mapped_column(
        ForeignKey(Team.id, ondelete="CASCADE"), nullable=True, index=True
    )
    home_score: Mapped[int] = mapped_column(Integer())
    away_score: Mapped[int] = mapped_column(Integer())

    round: Mapped[int] = mapped_column(Integer(), index=True)
    closeness: Mapped[float | None] = mapped_column(Float(), nullable=True)
    best_of: Mapped[int] = mapped_column(Integer(), default=3, server_default="3")
    scheduled_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    current_map_index: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    tournament_group_id: Mapped[int | None] = mapped_column(
        ForeignKey(TournamentGroup.id, ondelete="CASCADE"), nullable=True, index=True
    )
    stage_id: Mapped[int | None] = mapped_column(
        ForeignKey(Stage.id, ondelete="SET NULL"), nullable=True, index=True
    )
    stage_item_id: Mapped[int | None] = mapped_column(
        ForeignKey(StageItem.id, ondelete="SET NULL"), nullable=True, index=True
    )

    challonge_id: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    status: Mapped[enums.EncounterStatus] = mapped_column(
        Enum(enums.EncounterStatus), default=enums.EncounterStatus.OPEN
    )
    has_logs: Mapped[bool] = mapped_column(Boolean(), default=False)

    # Captain result submission
    result_status: Mapped[enums.EncounterResultStatus] = mapped_column(
        ENCOUNTER_RESULT_STATUS_ENUM,
        default=enums.EncounterResultStatus.NONE,
        server_default=enums.EncounterResultStatus.NONE.value,
    )
    submitted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey(User.id, ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True), nullable=True
    )
    confirmed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey(User.id, ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True), nullable=True
    )

    tournament_group: Mapped[TournamentGroup] = relationship()
    tournament: Mapped[Tournament] = relationship()
    home_team: Mapped["Team"] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(foreign_keys=[away_team_id])
    stage: Mapped["Stage | None"] = relationship()
    stage_item: Mapped["StageItem | None"] = relationship()
    submitted_by: Mapped["User | None"] = relationship(foreign_keys=[submitted_by_id])
    confirmed_by: Mapped["User | None"] = relationship(foreign_keys=[confirmed_by_id])
    matches: Mapped[list["Match"]] = relationship()
