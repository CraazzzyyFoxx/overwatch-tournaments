from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = (
    "CustomGame",
    "CustomGameCoHost",
    "CustomGamePlayer",
    "CustomGamePlayerRole",
    "CustomGameTeamName",
)


class CustomGame(db.TimeStampIntegerMixin):
    """Workspace pickup mix and its scalar settings.

    Repeating facts live in child tables. The remaining JSON column is a versioned
    solver document, not a bag of application state. Nothing the *host* configures
    is here at all -- the solver knobs, the roster shape and the points-per-win
    all live in one row of ``balancer.user_config``, so the same person's mixes
    all run the same way -- and the Discord target is the workspace's
    (``balancer.workspace_config.config_json.mix_discord_channel_id``), not this
    lobby's.
    """

    __tablename__ = "custom_game"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'balanced', 'completed', 'cancelled')",
            name="ck_custom_game_status",
        ),
        # (no per-mix points_per_win check: the knob is the host's, see above)
        {"schema": "balancer"},
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    host_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    # The map the next recorded match is played on -- rolled or picked ahead of
    # the lobby, consumed and cleared by ``record_outcome``. A deleted catalogue
    # map nulls this rather than blocking the delete.
    next_map_id: Mapped[int | None] = mapped_column(ForeignKey("overwatch.map.id", ondelete="SET NULL"), nullable=True)
    # Which stored balance option the mix is showing. Host-driven: the pager is
    # the host's, and everyone else -- a co-host in another tab, a player
    # reading the public board -- renders whatever this points at, so a lobby
    # never studies a different matchup than the one being called out. Clamped
    # into range by readers; ``balance`` resets it, a fresh search renumbers
    # every option.
    selected_variant_index: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    balance_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    balance_result_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default="1")


class CustomGameCoHost(db.Base):
    """One extra account with the host's write access on one mix.

    Keyed by ``auth.user.id``, exactly like :attr:`CustomGame.host_user_id`: a
    grant addresses a login, not a roster row. Workspace membership is an RBAC
    fact (a role scoped to the workspace -- see ``AuthUser.is_workspace_member``),
    and an admin can hold it without ever appearing on this workspace's player
    roster, so ``workspace_member`` is the wrong anchor and cannot be an FK here.
    """

    __tablename__ = "custom_game_co_host"
    __table_args__ = ({"schema": "balancer"},)

    custom_game_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.custom_game.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("auth.user.id", ondelete="CASCADE"), primary_key=True)


class CustomGamePlayer(db.TimeStampIntegerMixin):
    """One workspace member's current lineup state in a mix."""

    __tablename__ = "custom_game_player"
    __table_args__ = (
        UniqueConstraint("custom_game_id", "workspace_member_id", name="uq_custom_game_player_member"),
        CheckConstraint(
            "participation IN ('must_play', 'pool', 'benched')",
            name="ck_custom_game_player_participation",
        ),
        CheckConstraint(
            "role_selection_mode IN ('all_ranked', 'explicit')",
            name="ck_custom_game_player_role_selection_mode",
        ),
        {"schema": "balancer"},
    )

    custom_game_id: Mapped[int] = mapped_column(ForeignKey("balancer.custom_game.id", ondelete="CASCADE"), index=True)
    workspace_member_id: Mapped[int] = mapped_column(ForeignKey("workspace_member.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    participation: Mapped[str] = mapped_column(String(16), nullable=False, default="pool", server_default="pool")
    role_selection_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="all_ranked", server_default="all_ranked"
    )
    is_flex: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")


class CustomGamePlayerRole(db.Base):
    __tablename__ = "custom_game_player_role"
    __table_args__ = (
        UniqueConstraint(
            "custom_game_player_id",
            "priority",
            name="uq_custom_game_player_role_priority",
        ),
        CheckConstraint("priority > 0", name="ck_custom_game_player_role_priority"),
        {"schema": "balancer"},
    )

    custom_game_player_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.custom_game_player.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    priority: Mapped[int] = mapped_column(Integer(), nullable=False)


class CustomGameTeamName(db.Base):
    __tablename__ = "custom_game_team_name"
    __table_args__ = (
        CheckConstraint("team_index BETWEEN 0 AND 7", name="ck_custom_game_team_name_index"),
        {"schema": "balancer"},
    )

    custom_game_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.custom_game.id", ondelete="CASCADE"), primary_key=True
    )
    team_index: Mapped[int] = mapped_column(Integer(), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)

