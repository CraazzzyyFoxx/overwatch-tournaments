from __future__ import annotations

import typing
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.domain.mix_lobby import MAX_LOBBIES

if typing.TYPE_CHECKING:
    from shared.models.catalog.role import CatalogRole
    from shared.models.encounter.encounter import Encounter

__all__ = (
    "CustomGame",
    "CustomGameCoHost",
    "CustomGameLobby",
    "CustomGamePlayer",
    "CustomGamePlayerRole",
    "CustomGameTeamName",
    "CustomGameRound",
    "CustomGameRoundMember",
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
        CheckConstraint("team_formation IN ('balance', 'draft')", name="ck_custom_game_team_formation"),
        CheckConstraint("draft_pick_seconds BETWEEN 10 AND 600", name="ck_custom_game_draft_pick_seconds"),
        CheckConstraint("hero_ban_seconds BETWEEN 10 AND 600", name="ck_custom_game_hero_ban_seconds"),
        CheckConstraint("hero_pick_seconds BETWEEN 10 AND 600", name="ck_custom_game_hero_pick_seconds"),
        # Target of ``fk_encounter_custom_game``: owner, workspace and discipline in one key.
        UniqueConstraint("id", "workspace_id", "discipline", name="uq_custom_game_owner_key"),
        # Deferred like ``fk_encounter_scoring_rule``: a workspace delete removes rule and mix in one statement.
        ForeignKeyConstraint(
            ["scoring_rule_id", "workspace_id"],
            ["encounter.scoring_rule.id", "encounter.scoring_rule.workspace_id"],
            name="fk_custom_game_scoring_rule",
            deferrable=True,
            initially="DEFERRED",
        ),
        # (no per-mix points_per_win check: the knob is the host's, see above)
        {"schema": "mix"},
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    host_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    # How many lobbies this mix runs at once (1..``MAX_LOBBIES``). There are
    # exactly this many ``mix.lobby`` rows: everything about one played
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
    #: Which game this mix is played in (``catalog.discipline.code``); fixed at create, carried on every mix read.
    discipline: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("catalog.discipline.code", name="fk_custom_game_discipline"),
        default="overwatch",
        server_default="overwatch",
    )
    #: The mix's own ``wins`` rule: Bo1, draws allowed. Every round encounter points at it.
    scoring_rule_id: Mapped[int] = mapped_column(BigInteger())
    #: The hero ban preset Start opens a room on (``pick_ban_rules.mix_ban_preset`` of this game); NULL = no bans.
    hero_ban_preset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: How a lobby forms its teams by default (spec §4.3): ``balance`` (the solver) or ``draft`` (captains pick).
    team_formation: Mapped[str] = mapped_column(String(16), nullable=False, default="balance", server_default="balance")
    #: A mix draft's pick clock in seconds (10..600, the draft schema's range).
    draft_pick_seconds: Mapped[int] = mapped_column(Integer(), nullable=False, default=30, server_default="30")
    #: Fearless (spec §11.4): a player cannot pick a hero they were recorded on in an earlier round of this mix.
    hero_fearless: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")
    #: The hero room's clock per ban (and protect) / per pick, in seconds (10..600); NULL = the preset's own. Every such
    #: step of the next room runs on it -- an all-at-once pick is one step, so its clock is the whole pick's.
    hero_ban_seconds: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    hero_pick_seconds: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    #: Free pick order: a turn-by-turn pick (member ``next``) is for whichever teammate still without a hero the picker
    #: taps; one nobody takes falls to the first of them in lineup order.
    hero_free_order: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")
    #: Only a team's captain (or a host) picks its heroes, for any teammate; off, each player also picks their own.
    hero_captains_only: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")


class CustomGameCoHost(db.Base):
    """One extra account with the host's write access on one mix.

    Keyed by ``auth.user.id``, exactly like :attr:`CustomGame.host_user_id`: a
    grant addresses a login, not a roster row. Workspace membership is an RBAC
    fact (a role scoped to the workspace -- see ``AuthUser.is_workspace_member``),
    and an admin can hold it without ever appearing on this workspace's player
    roster, so ``workspace_member`` is the wrong anchor and cannot be an FK here.
    """

    __tablename__ = "co_host"
    __table_args__ = ({"schema": "mix"},)

    custom_game_id: Mapped[int] = mapped_column(ForeignKey("mix.custom_game.id", ondelete="CASCADE"), primary_key=True)
    # The PK leads with custom_game_id; "mixes this account co-hosts" needs its own index.
    user_id: Mapped[int] = mapped_column(ForeignKey("auth.user.id", ondelete="CASCADE"), primary_key=True, index=True)


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

    __tablename__ = "lobby"
    __table_args__ = (
        CheckConstraint(f"lobby_index BETWEEN 0 AND {MAX_LOBBIES - 1}", name="ck_custom_game_lobby_index"),
        CheckConstraint("next_map_kind = 'map'", name="ck_custom_game_lobby_next_map_kind"),
        ForeignKeyConstraint(
            ["next_map_id", "next_map_kind"],
            ["catalog.entity.id", "catalog.entity.kind"],
            ondelete="SET NULL (next_map_id)",
            name="fk_custom_game_lobby_next_map",
        ),
        UniqueConstraint("live_encounter_id", name="uq_custom_game_lobby_live_encounter"),
        {"schema": "mix"},
    )

    custom_game_id: Mapped[int] = mapped_column(ForeignKey("mix.custom_game.id", ondelete="CASCADE"), primary_key=True)
    lobby_index: Mapped[int] = mapped_column(Integer(), primary_key=True)
    # Which stored balance option this lobby is showing. Host-driven: the pager
    # is the host's, and every other viewer renders whatever it points at.
    selected_variant_index: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    balance_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    balance_result_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default="1")
    # The map this lobby's next match is played on -- rolled ahead of the lobby
    # loading in, fixed on the match by ``start_match`` and cleared by ``record_outcome``.
    next_map_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    next_map_kind: Mapped[str] = mapped_column(String(16), default="map", server_default="map")
    balanced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The two team voices this lobby's teams are moved into (team 1, team 2):
    # voices of the workspace's voice category that are not general voices.
    team1_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    team2_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    # The match this lobby has on the floor: started, not yet recorded or cancelled (spec §5.1). Its lineup is
    # frozen meanwhile; the lobby's state (idle / ready / pregame / live) is derived from this, the document,
    # ``live_ban_preset`` and the match's hero room, never stored.
    live_encounter_id: Mapped[int | None] = mapped_column(
        BigInteger(),
        ForeignKey("encounter.encounter.id", ondelete="SET NULL", name="fk_custom_game_lobby_live_encounter"),
        nullable=True,
    )
    # The hero ban preset Start froze for ``live_encounter_id`` (the mix's ``hero_ban_preset`` then; NULL = no bans):
    # the match's room opens -- and any reset reopens -- on it, whatever the header says meanwhile.
    live_ban_preset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The in-game lobby's join code, as the host pasted it (trimmed, 1..64 chars; NULL = none). Public like the
    # rest of the lobby, kept across matches until the host changes it, and editable while a match is live.
    lobby_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CustomGamePlayer(db.TimeStampIntegerMixin):
    """One workspace member's current lineup state in a mix."""

    __tablename__ = "player"
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
        {"schema": "mix"},
    )

    custom_game_id: Mapped[int] = mapped_column(ForeignKey("mix.custom_game.id", ondelete="CASCADE"), index=True)
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
    # Stepped away (spec §7.4): in no lobby's seated set until back. The must-play mark is kept for the return.
    away: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")


class CustomGamePlayerRole(db.Base):
    """A mix player's ordered preferences: module roles of the mix's rated dimension."""

    __tablename__ = "player_role"
    __table_args__ = (
        UniqueConstraint(
            "custom_game_player_id",
            "priority",
            name="uq_custom_game_player_role_priority",
        ),
        CheckConstraint("priority > 0", name="ck_custom_game_player_role_priority"),
        ForeignKeyConstraint(
            ["role_id", "dimension_id"],
            ["catalog.role.id", "catalog.role.dimension_id"],
            name="fk_custom_game_player_role_role",
            deferrable=True,
            initially="DEFERRED",
        ),
        {"schema": "mix"},
    )

    custom_game_player_id: Mapped[int] = mapped_column(
        ForeignKey("mix.player.id", ondelete="CASCADE"), primary_key=True
    )
    dimension_id: Mapped[int] = mapped_column(BigInteger())
    role_id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, autoincrement=False, index=True)
    priority: Mapped[int] = mapped_column(Integer(), nullable=False)

    catalog_role: Mapped[CatalogRole] = relationship(
        primaryjoin="foreign(CustomGamePlayerRole.role_id) == CatalogRole.id", foreign_keys=[role_id], lazy="joined"
    )

    @property
    def role(self) -> str:
        return self.catalog_role.code


class CustomGameTeamName(db.Base):
    __tablename__ = "team_name"
    __table_args__ = (
        CheckConstraint(f"team_index BETWEEN 0 AND {2 * MAX_LOBBIES - 1}", name="ck_custom_game_team_name_index"),
        {"schema": "mix"},
    )

    custom_game_id: Mapped[int] = mapped_column(ForeignKey("mix.custom_game.id", ondelete="CASCADE"), primary_key=True)
    team_index: Mapped[int] = mapped_column(Integer(), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)


class CustomGameRound(db.Base):
    """Balancer-only facts of one recorded mix round. The round itself is ``encounter.encounter``."""

    __tablename__ = "round"
    __table_args__ = (
        CheckConstraint(f"lobby_index BETWEEN 0 AND {MAX_LOBBIES - 1}", name="ck_custom_game_round_lobby_index"),
        {"schema": "mix"},
    )

    encounter_id: Mapped[int] = mapped_column(
        ForeignKey("encounter.encounter.id", ondelete="CASCADE", name="fk_custom_game_round_encounter"),
        primary_key=True,
    )
    lobby_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    #: The points-per-win this round moved both teams by; undo gives back exactly this. NULL for a draw or points off.
    points_per_win_applied: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    encounter: Mapped[Encounter] = relationship()
    members: Mapped[list[CustomGameRoundMember]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="CustomGameRoundMember.workspace_member_id"
    )


class CustomGameRoundMember(db.Base):
    """One member's balancer facts in one round: seated (with its frozen rank delta) or busy next door.

    Who sat on which seat is ``encounter.team_member`` only. The writer never stores a member both busy and seated.
    """

    __tablename__ = "round_member"
    __table_args__ = (
        CheckConstraint("NOT busy OR rank_delta_applied IS NULL", name="ck_custom_game_round_member_busy"),
        Index("ix_custom_game_round_member_workspace_member_id", "workspace_member_id"),
        {"schema": "mix"},
    )

    encounter_id: Mapped[int] = mapped_column(
        ForeignKey("mix.round.encounter_id", ondelete="CASCADE", name="fk_custom_game_round_member_round"),
        primary_key=True,
    )
    # NO ACTION, deferred: the anchor rule of ``encounter.team_member``.
    workspace_member_id: Mapped[int] = mapped_column(
        ForeignKey(
            "workspace_member.id",
            name="fk_custom_game_round_member_workspace_member",
            deferrable=True,
            initially="DEFERRED",
        ),
        primary_key=True,
    )
    busy: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    rank_delta_applied: Mapped[int | None] = mapped_column(Integer(), nullable=True)
