from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.balancer import BalancerBalance
    from shared.models.tournament import Tournament
    from shared.models.user import User
    from shared.models.workspace import Workspace

__all__ = (
    "DraftPick",
    "DraftPlayer",
    "DraftSession",
    "DraftTeam",
)

# Enum-like columns are stored as plain String, matching the balancer-schema
# convention (see BalancerRegistration.status). The values are the StrEnum
# members in shared.core.enums (DraftStatus / DraftFormat / DraftPoolSource /
# DraftAutopickStrategy / DraftRole / DraftPlayerStatus / DraftPickStatus);
# StrEnum equality keeps comparisons type-safe on read.


class DraftSession(db.TimeStampIntegerMixin):
    __tablename__ = "draft_session"
    __table_args__ = (
        # One active draft per tournament — a CANCELLED/COMPLETED draft may
        # coexist with a new one, but only one in-flight session is allowed.
        Index(
            "uq_draft_session_active_tournament",
            "tournament_id",
            unique=True,
            postgresql_where=text("status IN ('setup','ready','live','paused')"),
        ),
        Index("ix_draft_session_tournament_status", "tournament_id", "status"),
        Index("ix_draft_session_status_created", "status", "created_at"),
        {"schema": "balancer"},
    )

    # tournament_id index is provided by ix_draft_session_tournament_status +
    # the partial-unique active index, so no standalone index here.
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"))
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="setup", default="setup")
    format: Mapped[str] = mapped_column(String(16), nullable=False, server_default="snake", default="snake")
    rounds: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="4", default=4)
    pick_time_seconds: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="45", default=45)
    team_size: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="5", default=5)
    # Circular FK with draft_pick — created with use_alter so DDL ordering works.
    current_pick_id: Mapped[int | None] = mapped_column(
        ForeignKey("balancer.draft_pick.id", ondelete="SET NULL", use_alter=True, name="fk_draft_session_current_pick"),
        nullable=True,
    )
    pool_source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="balancer_balance", default="balancer_balance"
    )
    source_balance_id: Mapped[int | None] = mapped_column(
        ForeignKey("balancer.balance.id", ondelete="SET NULL"), nullable=True, index=True
    )
    autopick_strategy: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="best_fit", default="best_fit"
    )
    allow_admin_override: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true", default=True)
    exported_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    export_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}", default=dict)

    tournament: Mapped["Tournament"] = relationship()
    workspace: Mapped["Workspace"] = relationship()
    source_balance: Mapped["BalancerBalance | None"] = relationship()
    teams: Mapped[list["DraftTeam"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    players: Mapped[list["DraftPlayer"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    picks: Mapped[list["DraftPick"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        foreign_keys="DraftPick.session_id",
    )
    current_pick: Mapped["DraftPick | None"] = relationship(foreign_keys=[current_pick_id], post_update=True)


class DraftTeam(db.TimeStampIntegerMixin):
    __tablename__ = "draft_team"
    __table_args__ = (
        UniqueConstraint("session_id", "draft_position", name="uq_draft_team_session_position"),
        {"schema": "balancer"},
    )

    session_id: Mapped[int] = mapped_column(ForeignKey("balancer.draft_session.id", ondelete="CASCADE"), index=True)
    captain_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The auth account that registered as captain — the reliable "is this me"
    # signal for captain gating (independent of public-player linking).
    captain_auth_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    draft_position: Mapped[int] = mapped_column(Integer(), nullable=False)
    exported_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.team.id", ondelete="SET NULL"), nullable=True, index=True
    )

    session: Mapped["DraftSession"] = relationship(back_populates="teams")
    captain: Mapped["User | None"] = relationship()
    picks: Mapped[list["DraftPick"]] = relationship(back_populates="draft_team", foreign_keys="DraftPick.draft_team_id")
    roster: Mapped[list["DraftPlayer"]] = relationship(
        primaryjoin="DraftPlayer.drafted_by_team_id == DraftTeam.id",
        viewonly=True,
    )


class DraftPlayer(db.TimeStampIntegerMixin):
    __tablename__ = "draft_player"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_draft_player_session_user"),
        Index("ix_draft_player_session_status", "session_id", "status"),
        {"schema": "balancer"},
    )

    # session_id index is provided by ix_draft_player_session_status (leftmost prefix).
    session_id: Mapped[int] = mapped_column(ForeignKey("balancer.draft_session.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    battle_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primary_role: Mapped[str] = mapped_column(String(16), nullable=False)
    sub_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_flex: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    division_number: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    rank_value: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="available", default="available")
    is_captain: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    drafted_by_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("balancer.draft_team.id", ondelete="SET NULL"), nullable=True, index=True
    )
    secondary_roles_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Per-role rank catalogue: ``role.value -> SR``. The single source of truth
    # for "what rank does this player have on role X" — ``rank_value`` is the
    # primary-role default/fallback (see ``services.draft.ranks.role_rank``).
    role_ranks: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, server_default="{}", default=dict)
    # Per-role top heroes: ``role.value -> [{"slug", "image_path"}]`` (display only).
    role_top_heroes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}", default=dict)
    # Misc/extensible per-player data (e.g. ``notes``). Replaces the misnamed
    # ``anomaly_flags`` bag — known concepts live in their own columns above.
    additional_info: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}", default=dict)

    session: Mapped["DraftSession"] = relationship(back_populates="players")
    user: Mapped["User | None"] = relationship()
    drafted_by_team: Mapped["DraftTeam | None"] = relationship(foreign_keys=[drafted_by_team_id], overlaps="roster")


class DraftPick(db.TimeStampIntegerMixin):
    __tablename__ = "draft_pick"
    __table_args__ = (
        # (session_id, overall_no) unique constraint also serves as the
        # session+order lookup index — no separate ix needed.
        UniqueConstraint("session_id", "overall_no", name="uq_draft_pick_session_overall"),
        Index("ix_draft_pick_session_status", "session_id", "status"),
        {"schema": "balancer"},
    )

    session_id: Mapped[int] = mapped_column(ForeignKey("balancer.draft_session.id", ondelete="CASCADE"))
    overall_no: Mapped[int] = mapped_column(Integer(), nullable=False)
    round_no: Mapped[int] = mapped_column(Integer(), nullable=False)
    pick_in_round: Mapped[int] = mapped_column(Integer(), nullable=False)
    draft_team_id: Mapped[int] = mapped_column(ForeignKey("balancer.draft_team.id", ondelete="CASCADE"), index=True)
    target_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Frozen rank of the drafted role at finalize time, so a pick is a complete
    # ``(player, role, rank)`` record (resolved via ``ranks.role_rank``).
    target_rank_value: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="upcoming", default="upcoming")
    picked_player_id: Mapped[int | None] = mapped_column(
        ForeignKey("balancer.draft_player.id", ondelete="SET NULL"), nullable=True, index=True
    )
    picked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.user.id", ondelete="SET NULL"), nullable=True
    )
    is_autopick: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    is_admin_override: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    clock_started_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clock_expires_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clock_remaining_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # Optimistic-concurrency token: the atomic select-vs-autopick finalize
    # bumps this under a WHERE version = :expected guard.
    version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)

    session: Mapped["DraftSession"] = relationship(back_populates="picks", foreign_keys=[session_id])
    draft_team: Mapped["DraftTeam"] = relationship(back_populates="picks", foreign_keys=[draft_team_id])
    picked_player: Mapped["DraftPlayer | None"] = relationship(foreign_keys=[picked_player_id])
