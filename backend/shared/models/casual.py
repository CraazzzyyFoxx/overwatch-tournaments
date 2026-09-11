from __future__ import annotations

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums

__all__ = ("CasualMatch", "CasualTeam", "CasualPlayer")


class CasualMatch(db.TimeStampIntegerMixin):
    """Aggregate root for one immutable casual-match snapshot."""

    __tablename__ = "match"
    __table_args__ = ({"schema": "casual"},)

    custom_game_id: Mapped[int] = mapped_column(ForeignKey("balancer.custom_game.id", ondelete="CASCADE"), index=True)
    map_id: Mapped[int | None] = mapped_column(
        ForeignKey("overwatch.map.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    # How far this match actually moved both teams' ranks when it was recorded.
    # Undo rolls back this stored amount, never the mix's current
    # ``points_per_win``: the knob may have changed since. NULL for a draw or a
    # match recorded with points off.
    points_per_win_applied: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    teams: Mapped[list[CasualTeam]] = relationship(
        back_populates="match",
        passive_deletes=True,
        order_by="CasualTeam.id",
    )


class CasualTeam(db.TimeStampIntegerMixin):
    """One scored side owned by exactly one casual match."""

    __tablename__ = "team"
    __table_args__ = (
        UniqueConstraint("match_id", "side", name="uq_casual_team_match_side"),
        CheckConstraint("side IN ('home', 'away')", name="ck_casual_team_side"),
        CheckConstraint("score >= 0", name="ck_casual_team_score"),
        {"schema": "casual"},
    )

    match_id: Mapped[int] = mapped_column(ForeignKey("casual.match.id", ondelete="CASCADE"), index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[int] = mapped_column(Integer(), nullable=False)

    match: Mapped[CasualMatch] = relationship(back_populates="teams")
    players: Mapped[list[CasualPlayer]] = relationship(back_populates="team", passive_deletes=True)


class CasualPlayer(db.TimeStampIntegerMixin):
    """One immutable seat snapshot.

    The member FK may disappear after the match; the recorded display name,
    role and rank remain.
    """

    __tablename__ = "player"
    __table_args__ = ({"schema": "casual"},)

    team_id: Mapped[int] = mapped_column(ForeignKey("casual.team.id", ondelete="CASCADE"), index=True)
    workspace_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace_member.id", ondelete="SET NULL"), nullable=True, index=True
    )
    display_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[enums.HeroClass | None] = mapped_column(Enum(enums.HeroClass), nullable=True)
    rank: Mapped[int] = mapped_column(Integer(), nullable=False)

    team: Mapped[CasualTeam] = relationship(back_populates="players")
