from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db
from shared.domain.mix_lobby import MAX_LOBBIES

__all__ = (
    "CustomGame",
    "CustomGameCoHost",
    "CustomGameLobby",
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
    lobby's; only the voices a mix moves people into are its own.
    """

    __tablename__ = "custom_game"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'balanced', 'completed', 'cancelled')",
            name="ck_custom_game_status",
        ),
        CheckConstraint(
            "self_signup IN ('closed', 'pool', 'benched')",
            name="ck_custom_game_self_signup",
        ),
        CheckConstraint(f"lobby_count BETWEEN 1 AND {MAX_LOBBIES}", name="ck_custom_game_lobby_count"),
        # (no per-mix points_per_win check: the knob is the host's, see above)
        {"schema": "balancer"},
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    host_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    # How many lobbies this mix runs at once (1..``MAX_LOBBIES``). There are
    # exactly this many ``custom_game_lobby`` rows: everything about one played
    # match -- the matchup, the pager, the rolled map -- is a fact about a
    # lobby, not about the mix, so two lobbies never fight over one column.
    lobby_count: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default="1")
    # Whether players may seat THEMSELVES here, and where that lands them:
    # closed | pool | benched. Every existing mix ships closed, so the feature
    # is opt-in per session rather than a platform-wide change of who writes a
    # roster.
    self_signup: Mapped[str] = mapped_column(String(16), nullable=False, default="closed", server_default="closed")
    # Whether a seated player may re-order their OWN roles and flip flex. The
    # host's book of ranks stays the host's either way.
    self_role_edit: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")
    # The mix's general voice: where "return" sends everyone. One of the
    # workspace's general voices (``workspace_config.mix_general_voice_channel_ids``).
    general_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)


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


class CustomGameLobby(db.Base):
    """One of a mix's lobbies: its own matchup, pager, map and clock.

    A mix with one lobby is simply row ``lobby_index = 0``, so there is one code
    path for one lobby and for six. Membership is NOT stored: who is in a lobby
    right now is derived from the seats of its selected variant, which keeps the
    matchup the single source of truth instead of a column to re-sync after
    every balance and every swap.

    ``balanced_at`` says when this lobby last got a matchup, and is the half of
    "the lineup on screen was never recorded" the mix cannot answer from the
    match history alone.
    """

    __tablename__ = "custom_game_lobby"
    __table_args__ = (
        CheckConstraint(f"lobby_index BETWEEN 0 AND {MAX_LOBBIES - 1}", name="ck_custom_game_lobby_index"),
        {"schema": "balancer"},
    )

    custom_game_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.custom_game.id", ondelete="CASCADE"), primary_key=True
    )
    lobby_index: Mapped[int] = mapped_column(Integer(), primary_key=True)
    # Which stored balance option this lobby is showing. Host-driven: the pager
    # is the host's, and every other viewer renders whatever it points at.
    selected_variant_index: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    balance_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    balance_result_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default="1")
    # The map this lobby's next match is played on -- rolled ahead of the lobby
    # loading in, consumed and cleared by ``record_outcome``.
    next_map_id: Mapped[int | None] = mapped_column(ForeignKey("overwatch.map.id", ondelete="SET NULL"), nullable=True)
    balanced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The two team voices this lobby's teams are moved into (team 1, team 2):
    # voices of the workspace's voice category that are not general voices.
    team1_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    team2_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)


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
        CheckConstraint(f"lobby_pin BETWEEN 0 AND {MAX_LOBBIES - 1}", name="ck_custom_game_player_lobby_pin"),
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
    # The host's "this one plays in A": honoured by the next balance, not a
    # live seat. ``None`` means the solver places them wherever they fit.
    lobby_pin: Mapped[int | None] = mapped_column(Integer(), nullable=True)


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
