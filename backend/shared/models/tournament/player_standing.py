from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db
from shared.models.tournament.stage import Stage
from shared.models.tournament.tournament import Tournament

__all__ = ("PlayerStanding", "PlayerStandingPin")


class PlayerStanding(db.TimeStampIntegerMixin):
    """One player's row in an ``individual_swiss`` stage's personal table.

    The pool is frozen when the stage starts: one row per player per stage, rebuilt
    by the standings job. ``position`` is 1-based and counted inside the player's
    ``role``; ``rank`` is the player's rank at that moment (higher = stronger).
    """

    __tablename__ = "player_standing"
    __table_args__ = (
        UniqueConstraint("stage_id", "workspace_member_id", name="uq_player_standing_stage_member"),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey(Stage.id, ondelete="CASCADE"))
    registration_id: Mapped[int | None] = mapped_column(
        ForeignKey("registration.registration.id", ondelete="SET NULL"), nullable=True
    )
    workspace_member_id: Mapped[int] = mapped_column(ForeignKey("workspace_member.id", ondelete="CASCADE"))
    display_name: Mapped[str] = mapped_column(String(255))
    #: Role code, e.g. ``tank``.
    role: Mapped[str] = mapped_column(String(32))
    rank: Mapped[int] = mapped_column(Integer())
    points: Mapped[float] = mapped_column(Float(), default=0, server_default="0")
    wins: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    draws: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    losses: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    matches_played: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    maps_won: Mapped[float] = mapped_column(Float(), default=0, server_default="0")
    maps_lost: Mapped[float] = mapped_column(Float(), default=0, server_default="0")
    buchholz: Mapped[float] = mapped_column(Float(), default=0, server_default="0")
    position: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    is_qualified: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false")
    is_captain: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false")
    is_pinned: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false")


class PlayerStandingPin(db.TimeStampIntegerMixin):
    """An organizer's fixed place for one player inside their role's table.

    Lives apart from ``PlayerStanding`` because those rows are rebuilt on every
    recalculation. Uniqueness of a position per role is checked by the service.
    """

    __tablename__ = "player_standing_pin"
    __table_args__ = (
        CheckConstraint("position >= 1", name="ck_player_standing_pin_position"),
        UniqueConstraint("stage_id", "workspace_member_id", name="uq_player_standing_pin_stage_member"),
        {"schema": "tournament"},
    )

    stage_id: Mapped[int] = mapped_column(ForeignKey(Stage.id, ondelete="CASCADE"))
    workspace_member_id: Mapped[int] = mapped_column(ForeignKey("workspace_member.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer())
