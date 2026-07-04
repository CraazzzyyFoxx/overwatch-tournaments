from sqlalchemy import Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.models.tournament.stage import Stage, StageItem
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament, TournamentGroup

__all__ = ("Standing",)


class Standing(db.TimeStampIntegerMixin):
    __tablename__ = "standing"

    __table_args__ = (
        # Canonical identity for a standing row is (tournament, stage, stage_item, team).
        # Unique index is created in migration phasea0001 with COALESCE on stage_item_id
        # (SQLAlchemy does not support COALESCE inside UniqueConstraint, so we register
        # this at migration level and keep helper indexes here).
        Index("ix_standing_tournament_position", "tournament_id", "overall_position"),
        Index(
            "ix_standing_stage_stage_item_team",
            "stage_id",
            "stage_item_id",
            "team_id",
        ),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    # Deprecated: legacy FK to TournamentGroup. New rows may leave it NULL.
    # Kept for backwards compatibility until TournamentGroup is dropped.
    group_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(TournamentGroup.id, ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    team_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(Team.id, ondelete="CASCADE"), index=True
    )
    stage_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(Stage.id, ondelete="SET NULL"), nullable=True, index=True
    )
    stage_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(StageItem.id, ondelete="SET NULL"), nullable=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    overall_position: Mapped[int] = mapped_column(Integer, server_default="0")
    matches: Mapped[int] = mapped_column(Integer)
    win: Mapped[int] = mapped_column(Integer, default=0)
    draw: Mapped[int] = mapped_column(Integer, default=0)
    lose: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[float] = mapped_column(Float)
    buchholz: Mapped[float | None] = mapped_column(Float, nullable=True)
    tb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Map/score differential tie-breaker (sum of map-score margins across the
    # group stage). Persisted so the API can surface an accurate value instead
    # of approximating it. NULL for elimination-stage standings.
    score_differential: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tournament: Mapped[Tournament] = relationship(back_populates="standings")
    group: Mapped[TournamentGroup] = relationship()
    team: Mapped[Team] = relationship(back_populates="standings")
    stage: Mapped["Stage | None"] = relationship()
    stage_item: Mapped["StageItem | None"] = relationship()
