from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.models.tournament.stage import Stage, StageItem
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament

__all__ = ("Standing", "StandingPin")


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

    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey(Team.id, ondelete="CASCADE"), index=True)
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
    # The TRIMMED (median) Buchholz -- and, load-bearing beyond its value, the
    # group-vs-playoff discriminator: `buchholz IS NULL` means "playoff row" in
    # app-service user/compare/overview queries and in parser-service achievement
    # filters. Renaming it would touch all of those, so the untrimmed sum lives
    # in its own column instead.
    buchholz: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Sum of every opponent's points, nothing trimmed. Separate tiebreaker from
    #: ``buchholz`` (it sits later in the default Swiss order) and not derivable
    #: from what else is stored, since opponents' points are not.
    full_buchholz: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Position of the head of this row's tie cluster; equal values across rows
    #: mean no configured tiebreaker could separate them and their order was
    #: assigned. NULL when the row stands alone. Read-only: recomputed on every
    #: recalculation, so editing it on a row is pointless.
    tie_group: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Map/score differential tie-breaker (sum of map-score margins across the
    # group stage). Persisted so the API can surface an accurate value instead
    # of approximating it. NULL for elimination-stage standings.
    score_differential: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The organizer pinned this row's ``position`` (``StandingPin``); written by
    #: the engine on every recalculation, like everything else on the row.
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    tournament: Mapped[Tournament] = relationship(back_populates="standings")
    team: Mapped[Team] = relationship(back_populates="standings")
    stage: Mapped[Stage | None] = relationship()
    stage_item: Mapped[StageItem | None] = relationship()


class StandingPin(db.TimeStampIntegerMixin):
    """An organizer's fixed place for one team in one standings table.

    A table is a (stage, stage item) pair -- the scope ``Standing.position`` is
    counted in. The engine ranks the table as usual, then seats every pinned team
    at its place and lets the others fill the free places in computed order, so a
    pin holds whatever results arrive later. Standing rows are rebuilt from
    scratch on each recalculation, which is why the pin lives here and not on
    them. ``stage_item_id`` is NULL for an elimination stage, whose table spans
    the whole stage; NULLs compare equal in both unique indexes.
    """

    __tablename__ = "standing_pin"
    __table_args__ = (
        CheckConstraint("position >= 1", name="ck_standing_pin_position"),
        Index(
            "uq_standing_pin_team",
            "stage_id",
            "stage_item_id",
            "team_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "uq_standing_pin_position",
            "stage_id",
            "stage_item_id",
            "position",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey(Stage.id, ondelete="CASCADE"))
    stage_item_id: Mapped[int | None] = mapped_column(ForeignKey(StageItem.id, ondelete="CASCADE"), nullable=True)
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
