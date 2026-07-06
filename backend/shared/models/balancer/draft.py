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
    from shared.models.balancer.balance import BalancerBalance
    from shared.models.catalog.hero import Hero
    from shared.models.tenancy.workspace import Workspace, WorkspaceMember
    from shared.models.tournament.tournament import Tournament

__all__ = (
    "DraftPick",
    "DraftPlayer",
    "DraftPlayerRole",
    "DraftPlayerRoleHero",
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

    tournament: Mapped[Tournament] = relationship()
    workspace: Mapped[Workspace] = relationship()
    source_balance: Mapped[BalancerBalance | None] = relationship()
    teams: Mapped[list[DraftTeam]] = relationship(back_populates="session", cascade="all, delete-orphan")
    players: Mapped[list[DraftPlayer]] = relationship(back_populates="session", cascade="all, delete-orphan")
    picks: Mapped[list[DraftPick]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        foreign_keys="DraftPick.session_id",
    )
    current_pick: Mapped[DraftPick | None] = relationship(foreign_keys=[current_pick_id], post_update=True)


class DraftTeam(db.TimeStampIntegerMixin):
    __tablename__ = "draft_team"
    __table_args__ = (
        UniqueConstraint("session_id", "draft_position", name="uq_draft_team_session_position"),
        {"schema": "balancer"},
    )

    session_id: Mapped[int] = mapped_column(ForeignKey("balancer.draft_session.id", ondelete="CASCADE"), index=True)
    # Captain's domain identity, anchored on workspace_member (dbarch03 dropped
    # the legacy captain_user_id -> players.user.id column). The player id is
    # reached via captain_member.player_id; readers must eager-load
    # ``captain_member`` (see the captain_user_id property below).
    captain_workspace_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace_member.id", ondelete="SET NULL"), nullable=True, index=True
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

    session: Mapped[DraftSession] = relationship(back_populates="teams")
    captain_member: Mapped[WorkspaceMember | None] = relationship()
    picks: Mapped[list[DraftPick]] = relationship(back_populates="draft_team", foreign_keys="DraftPick.draft_team_id")
    roster: Mapped[list[DraftPlayer]] = relationship(
        primaryjoin="DraftPlayer.drafted_by_team_id == DraftTeam.id",
        viewonly=True,
    )

    @property
    def captain_user_id(self) -> int | None:
        """The captain's domain player id (players.user.id) via its member.

        Preserves the pre-dbarch03 read shape. ``captain_member`` must be
        eager-loaded by the caller — never rely on a lazy load in async code.
        """
        member = self.captain_member
        return member.player_id if member is not None else None


class DraftPlayer(db.TimeStampIntegerMixin):
    __tablename__ = "draft_player"
    __table_args__ = (
        UniqueConstraint("session_id", "workspace_member_id", name="uq_draft_player_session_member"),
        Index("ix_draft_player_session_status", "session_id", "status"),
        {"schema": "balancer"},
    )

    # session_id index is provided by ix_draft_player_session_status (leftmost prefix).
    session_id: Mapped[int] = mapped_column(ForeignKey("balancer.draft_session.id", ondelete="CASCADE"))
    # Sole identity anchor (dbarch03 dropped the legacy user_id column): the
    # domain player is reached via workspace_member.player_id. Nullable — most
    # pool players are unlinked (battle_tag only) and have no member.
    workspace_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace_member.id", ondelete="SET NULL"), nullable=True, index=True
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
    # Misc/extensible per-player data (e.g. ``notes``). Known concepts (per-role
    # rank/heroes, secondary roles) live in the normalized ``roles`` child table
    # (dbarch03 dropped the ``role_ranks``/``role_top_heroes``/
    # ``secondary_roles_json`` JSON bags); this catch-all is intentionally kept.
    additional_info: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}", default=dict)

    session: Mapped[DraftSession] = relationship(back_populates="players")
    member: Mapped[WorkspaceMember | None] = relationship()
    drafted_by_team: Mapped[DraftTeam | None] = relationship(foreign_keys=[drafted_by_team_id], overlaps="roster")
    roles: Mapped[list[DraftPlayerRole]] = relationship(
        back_populates="player",
        cascade="all, delete-orphan",
        order_by="DraftPlayerRole.priority",
    )

    @property
    def user_id(self) -> int | None:
        """The player's domain id (players.user.id) via its member.

        Preserves the pre-dbarch03 read shape. ``member`` must be eager-loaded.
        """
        member = self.member
        return member.player_id if member is not None else None

    @property
    def secondary_roles_json(self) -> list[str] | None:
        """Off-role codes (``is_secondary``), ordered by priority.

        Reconstructs the pre-dbarch03 ``secondary_roles_json`` shape from the
        normalized ``roles`` child rows (empty -> None, matching the old writer).
        ``roles`` must be eager-loaded.
        """
        secondary = [role.role for role in self.roles if role.is_secondary]
        return secondary or None

    @property
    def role_ranks(self) -> dict[str, int]:
        """Per-role rank catalogue (``role.value -> SR``), rebuilt from child rows.

        Only roles carrying a rank appear (matches the old JSON bag). ``roles``
        must be eager-loaded.
        """
        return {role.role: role.rank_value for role in self.roles if role.rank_value is not None}

    @property
    def role_top_heroes(self) -> dict[str, list[dict[str, Any]]]:
        """Per-role top heroes (``role.value -> [{slug, image_path}]``).

        Rebuilt from the child role/hero rows. Only roles with heroes appear
        (matches the old JSON bag). ``roles.hero_entries.hero`` must be
        eager-loaded.
        """
        out: dict[str, list[dict[str, Any]]] = {}
        for role in self.roles:
            heroes = [
                {"slug": he.hero.slug, "image_path": he.hero.image_path}
                for he in role.hero_entries
                if he.hero is not None
            ]
            if heroes:
                out[role.role] = heroes
        return out


class DraftPlayerRole(db.TimeStampIntegerMixin):
    """Normalized per-role entry for a draft player (primary + secondaries).

    Mirrors ``BalancerRegistrationRole``: one row per role the player has,
    carrying that role's rank. ``is_secondary`` marks an off-role; the player's
    primary role also gets a row (``is_secondary=False``).
    """

    __tablename__ = "draft_player_role"
    __table_args__ = (
        UniqueConstraint("draft_player_id", "role", name="uq_draft_player_role"),
        {"schema": "balancer"},
    )

    draft_player_id: Mapped[int] = mapped_column(ForeignKey("balancer.draft_player.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    rank_value: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    is_secondary: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    priority: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)

    player: Mapped[DraftPlayer] = relationship(back_populates="roles")
    hero_entries: Mapped[list[DraftPlayerRoleHero]] = relationship(
        back_populates="role_entry",
        cascade="all, delete-orphan",
        order_by="DraftPlayerRoleHero.priority",
    )


class DraftPlayerRoleHero(db.TimeStampIntegerMixin):
    """Ordered top-hero preference for a draft player's role entry.

    Mirrors ``BalancerRegistrationRoleHero`` (real FK to ``overwatch.hero``
    instead of a JSON blob of slugs).
    """

    __tablename__ = "draft_player_role_hero"
    __table_args__ = (
        UniqueConstraint("draft_player_role_id", "priority", name="uq_draft_player_role_hero_priority"),
        UniqueConstraint("draft_player_role_id", "hero_id", name="uq_draft_player_role_hero_hero"),
        {"schema": "balancer"},
    )

    draft_player_role_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.draft_player_role.id", ondelete="CASCADE"), index=True
    )
    hero_id: Mapped[int] = mapped_column(ForeignKey("overwatch.hero.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(Integer(), nullable=False)

    role_entry: Mapped[DraftPlayerRole] = relationship(back_populates="hero_entries")
    hero: Mapped[Hero] = relationship()


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
    # The acting captain's domain identity, anchored on workspace_member
    # (dbarch03 dropped the legacy picked_by_user_id column). Nullable —
    # system/auto picks have no actor. Player id via picked_by_member.player_id.
    picked_by_workspace_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace_member.id", ondelete="SET NULL"), nullable=True
    )
    is_autopick: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    is_admin_override: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    clock_started_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clock_expires_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clock_remaining_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # Optimistic-concurrency token: the atomic select-vs-autopick finalize
    # bumps this under a WHERE version = :expected guard.
    version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)

    session: Mapped[DraftSession] = relationship(back_populates="picks", foreign_keys=[session_id])
    draft_team: Mapped[DraftTeam] = relationship(back_populates="picks", foreign_keys=[draft_team_id])
    picked_player: Mapped[DraftPlayer | None] = relationship(foreign_keys=[picked_player_id])
    picked_by_member: Mapped[WorkspaceMember | None] = relationship(foreign_keys=[picked_by_workspace_member_id])

    @property
    def picked_by_user_id(self) -> int | None:
        """The acting captain's domain id (players.user.id) via its member.

        Preserves the pre-dbarch03 read shape. ``picked_by_member`` must be
        eager-loaded.
        """
        member = self.picked_by_member
        return member.player_id if member is not None else None
