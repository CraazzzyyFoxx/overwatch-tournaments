from __future__ import annotations

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums

__all__ = ("CasualMatch", "CasualMatchBusyPlayer", "CasualTeam", "CasualPlayer")


class CasualMatch(db.TimeStampIntegerMixin):
    """Aggregate root for one immutable casual-match snapshot."""

    __tablename__ = "match"
    __table_args__ = (
        CheckConstraint("lobby_index BETWEEN 0 AND 1", name="ck_casual_match_lobby_index"),
        {"schema": "casual"},
    )

    custom_game_id: Mapped[int] = mapped_column(ForeignKey("balancer.custom_game.id", ondelete="CASCADE"), index=True)
    # Which lobby of the mix played it. Every pre-two-lobby match is lobby 0,
    # which is also what a one-lobby mix keeps writing.
    lobby_index: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    map_id: Mapped[int | None] = mapped_column(
        ForeignKey("overwatch.map.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    # How far this match actually moved both teams' ranks when it was recorded.
    # Undo rolls back this stored amount, never the mix's current
    # ``points_per_win``: the knob may have changed since. NULL for a draw or a
    # match recorded with points off.
    points_per_win_applied: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    # ``cascade`` *and* ``passive_deletes``: the children's FKs are NOT NULL with
    # ``ON DELETE CASCADE``, so the database is what should clean them up, and
    # ``passive_deletes`` keeps an unloaded collection from being read just to be
    # rewritten. But ``passive_deletes`` alone only covers the *unloaded* case --
    # undo loads both sides (``CasualMatchRepository.get_for_game`` eager-loads
    # them to roll the ranks back), and the default cascade de-associates the
    # loaded ones: ``UPDATE casual.team SET match_id = NULL`` against NOT NULL.
    # ``delete-orphan`` says the sides are owned by the match and go with it.
    teams: Mapped[list[CasualTeam]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CasualTeam.id",
    )
    busy_players: Mapped[list[CasualMatchBusyPlayer]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        passive_deletes=True,
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
    players: Mapped[list[CasualPlayer]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


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
    # How far a ranker-mode recording moved this seat's rank in the host's
    # book, so undo gives back exactly that. NULL whenever the match was
    # recorded in points mode -- ``CasualMatch.points_per_win_applied`` covers it.
    rank_delta_applied: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    team: Mapped[CasualTeam] = relationship(back_populates="players")


class CasualMatchBusyPlayer(db.Base):
    """Who was playing the mix's OTHER lobby while this match was recorded.

    Rotation fairness only: a member listed here neither played this match nor
    sat it out -- they were in the other lobby -- so counting it either way
    would either fake a rest or fake a game. Empty for every one-lobby mix,
    which is exactly why nothing needs backfilling.
    """

    __tablename__ = "match_busy_player"
    __table_args__ = ({"schema": "casual"},)

    match_id: Mapped[int] = mapped_column(ForeignKey("casual.match.id", ondelete="CASCADE"), primary_key=True)
    workspace_member_id: Mapped[int] = mapped_column(
        ForeignKey("workspace_member.id", ondelete="CASCADE"), primary_key=True
    )

    match: Mapped[CasualMatch] = relationship(back_populates="busy_players")
