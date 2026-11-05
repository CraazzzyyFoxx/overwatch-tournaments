from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.balancer.balance import BalancerBalance
    from shared.models.catalog import CatalogRole
    from shared.models.identity.auth_user import AuthUser
    from shared.models.registration.registration import Registration
    from shared.models.tenancy.workspace import Workspace, WorkspaceMember

__all__ = (
    "DraftAuditEvent",
    "DraftPick",
    "DraftPlayer",
    "DraftSession",
    "DraftTeam",
)

# Enum-like state columns store shared.core.enums values as plain strings.
# Draft captain and pick role columns reference catalog.role.


class DraftSession(db.TimeStampIntegerMixin):
    __tablename__ = "session"
    __table_args__ = (
        # One active draft per owner -- a CANCELLED/COMPLETED draft may coexist with a new one.
        Index(
            "uq_draft_session_active_formation_node",
            "formation_node_id",
            unique=True,
            postgresql_where=text("status IN ('setup','ready','live','paused')"),
        ),
        Index(
            "uq_draft_session_active_lobby",
            "custom_game_id",
            "lobby_index",
            unique=True,
            postgresql_where=text("status IN ('setup','ready','live','paused')"),
        ),
        Index("ix_draft_session_tournament_status", "tournament_id", "status"),
        Index("ix_draft_session_status_created", "status", "created_at"),
        # Exactly one owner (spec §4.1): a tournament, or one lobby of a mix. Each owner key carries the workspace and
        # the discipline, so a copied column can never disagree with the owner it was copied from.
        CheckConstraint("num_nonnulls(tournament_id, custom_game_id) = 1", name="ck_draft_session_owner"),
        CheckConstraint("(custom_game_id IS NULL) = (lobby_index IS NULL)", name="ck_draft_session_lobby"),
        # A tournament draft forms one formation node's teams; a mix draft has no node (spec §4.6).
        CheckConstraint(
            "(tournament_id IS NULL) = (formation_node_id IS NULL)", name="ck_draft_session_formation_node"
        ),
        ForeignKeyConstraint(
            ["tournament_id", "workspace_id", "discipline"],
            ["tournament.tournament.id", "tournament.tournament.workspace_id", "tournament.tournament.discipline"],
            ondelete="CASCADE",
            name="fk_draft_session_tournament",
        ),
        ForeignKeyConstraint(
            ["custom_game_id", "workspace_id", "discipline"],
            ["mix.custom_game.id", "mix.custom_game.workspace_id", "mix.custom_game.discipline"],
            ondelete="CASCADE",
            name="fk_draft_session_custom_game",
        ),
        # A lobby that goes (``set_lobby_count``) takes its drafts with it.
        ForeignKeyConstraint(
            ["custom_game_id", "lobby_index"],
            ["mix.lobby.custom_game_id", "mix.lobby.lobby_index"],
            ondelete="CASCADE",
            name="fk_draft_session_lobby",
        ),
        {"schema": "draft"},
    )

    tournament_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    formation_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.flow_node.id", ondelete="CASCADE"), nullable=True
    )
    #: The mix owning this draft, with ``lobby_index`` the lobby it forms teams for (spec §9.1).
    custom_game_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    lobby_index: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    #: Copy of the owner's discipline (``catalog.discipline.code``): the owner FKs check it.
    discipline: Mapped[str] = mapped_column(String(32), nullable=False)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="setup", default="setup")
    blocked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    format: Mapped[str] = mapped_column(String(16), nullable=False, server_default="snake", default="snake")
    rounds: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="4", default=4)
    pick_time_seconds: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="45", default=45)
    # Grace period granted once, after the main pick clock runs out, before the
    # autopick fires. 0 (the default) keeps the old behaviour: expiry autopicks.
    overtime_seconds: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    # Circular FK with draft.pick — created with use_alter so DDL ordering works.
    current_pick_id: Mapped[int | None] = mapped_column(
        ForeignKey("draft.pick.id", ondelete="SET NULL", use_alter=True, name="fk_draft_session_current_pick"),
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
    version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)

    workspace: Mapped[Workspace] = relationship()
    source_balance: Mapped[BalancerBalance | None] = relationship()
    teams: Mapped[list[DraftTeam]] = relationship(back_populates="session", cascade="all, delete-orphan")
    players: Mapped[list[DraftPlayer]] = relationship(back_populates="session", cascade="all, delete-orphan")
    picks: Mapped[list[DraftPick]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        foreign_keys="DraftPick.session_id",
    )
    audit_events: Mapped[list[DraftAuditEvent]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        foreign_keys="DraftAuditEvent.session_id",
    )
    current_pick: Mapped[DraftPick | None] = relationship(foreign_keys=[current_pick_id], post_update=True)


class DraftTeam(db.TimeStampIntegerMixin):
    __tablename__ = "team"
    __table_args__ = (
        UniqueConstraint("session_id", "draft_position", name="uq_draft_team_session_position"),
        {"schema": "draft"},
    )

    session_id: Mapped[int] = mapped_column(ForeignKey("draft.session.id", ondelete="CASCADE"), index=True)
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
    #: The captain's private autopick priority ("My list"): draft_player ids, in
    #: the captain's own order. Deliberately NOT on ``DraftTeamRead`` -- the board
    #: is public and this is the one piece of a team that is not.
    pick_queue: Mapped[list[int]] = mapped_column(JSONB, nullable=False, server_default="[]", default=list)

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
    """A seat in a draft pool: a registration (tournament) or a workspace member (mix), plus draft state.

    Deliberately holds NO roles, ranks, sub-role, flex flag or division. Those
    are a function of the registration and are resolved live by the one engine,
    ``shared.services.roster`` -- ``draftreg1`` deleted the copy this table used
    to keep, because it was written once from the RAW
    ``registration_role.rank_value`` while the balancer resolved the same rank
    through three layers, and nothing ever re-synced it.

    The surviving derivations in the draft are ``DraftPick.target_role`` /
    ``target_rank_value`` -- a historical fact about a pick that was made, not a
    cache of something readable elsewhere -- and ``captain_role``, the role the
    organizer seated a captain on. Both are draft decisions, not registration
    data.
    """

    __tablename__ = "player"
    __table_args__ = (
        UniqueConstraint("session_id", "registration_id", name="uq_draft_player_session_registration"),
        CheckConstraint("num_nonnulls(registration_id, workspace_member_id) >= 1", name="ck_draft_player_identity"),
        Index("ix_draft_player_session_status", "session_id", "status"),
        ForeignKeyConstraint(
            ["captain_role_id", "dimension_id"],
            ["catalog.role.id", "catalog.role.dimension_id"],
            name="fk_draft_player_captain_role",
            deferrable=True,
            initially="DEFERRED",
        ),
        {"schema": "draft"},
    )

    # session_id index is provided by ix_draft_player_session_status (leftmost prefix).
    session_id: Mapped[int] = mapped_column(ForeignKey("draft.session.id", ondelete="CASCADE"))
    # A tournament seat's anchor; a mix seat has none and is its member. RESTRICT because a registration is
    # soft-deleted: a hard delete would be somebody erasing a row a draft depends on, and refusing beats silently
    # dropping draft history.
    registration_id: Mapped[int | None] = mapped_column(
        ForeignKey("registration.registration.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # A mix seat's anchor; on a tournament seat kept alongside the registration (which also carries it) because the
    # draft's own ACL and audit rows join on the member: captain identity, picked_by, and the workspace RBAC baseline.
    # Never the source of a tournament seat's roles or ranks. NO ACTION, deferred: the anchor rule of
    # ``encounter.team_member`` -- a SET NULL would leave a mix seat naming nobody (``ck_draft_player_identity``),
    # while deleting the whole workspace removes both sides by commit; a user merge repoints the seat first.
    workspace_member_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "workspace_member.id", name="fk_draft_player_workspace_member", deferrable=True, initially="DEFERRED"
        ),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="available", default="available")
    is_captain: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    drafted_by_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("draft.team.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: A top-level rated role pinned at seed time; None resolves the captain's lead role live.
    dimension_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    captain_role_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True, index=True)
    captain_role_row: Mapped[CatalogRole | None] = relationship(
        primaryjoin="foreign(DraftPlayer.captain_role_id) == CatalogRole.id",
        foreign_keys=[captain_role_id],
        lazy="joined",
    )

    @property
    def captain_role(self) -> str | None:
        return None if self.captain_role_row is None else self.captain_role_row.code

    version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)

    session: Mapped[DraftSession] = relationship(back_populates="players")
    registration: Mapped[Registration | None] = relationship()
    member: Mapped[WorkspaceMember | None] = relationship()
    drafted_by_team: Mapped[DraftTeam | None] = relationship(foreign_keys=[drafted_by_team_id], overlaps="roster")

    @property
    def user_id(self) -> int | None:
        """The player's domain id (players.user.id) via its member.

        ``member`` must be eager-loaded.
        """
        member = self.member
        return member.player_id if member is not None else None


class DraftAuditEvent(db.TimeStampIntegerMixin):
    """Private organizer audit trail for exceptional draft mutations."""

    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_draft_audit_session_created", "session_id", "created_at"),
        {"schema": "draft"},
    )

    session_id: Mapped[int] = mapped_column(
        ForeignKey("draft.session.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_auth_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    before_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    after_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    session: Mapped[DraftSession] = relationship(back_populates="audit_events", foreign_keys=[session_id])
    actor: Mapped[AuthUser | None] = relationship(foreign_keys=[actor_auth_user_id])


class DraftPick(db.TimeStampIntegerMixin):
    __tablename__ = "pick"
    __table_args__ = (
        # (session_id, overall_no) unique constraint also serves as the
        # session+order lookup index — no separate ix needed.
        UniqueConstraint("session_id", "overall_no", name="uq_draft_pick_session_overall"),
        Index("ix_draft_pick_session_status", "session_id", "status"),
        ForeignKeyConstraint(
            ["target_role_id", "dimension_id"],
            ["catalog.role.id", "catalog.role.dimension_id"],
            name="fk_draft_pick_target_role",
            deferrable=True,
            initially="DEFERRED",
        ),
        {"schema": "draft"},
    )

    session_id: Mapped[int] = mapped_column(ForeignKey("draft.session.id", ondelete="CASCADE"))
    overall_no: Mapped[int] = mapped_column(Integer(), nullable=False)
    round_no: Mapped[int] = mapped_column(Integer(), nullable=False)
    pick_in_round: Mapped[int] = mapped_column(Integer(), nullable=False)
    draft_team_id: Mapped[int] = mapped_column(ForeignKey("draft.team.id", ondelete="CASCADE"), index=True)
    dimension_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    target_role_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True, index=True)
    target_role_row: Mapped[CatalogRole | None] = relationship(
        primaryjoin="foreign(DraftPick.target_role_id) == CatalogRole.id",
        foreign_keys=[target_role_id],
        lazy="joined",
    )

    @property
    def target_role(self) -> str | None:
        return None if self.target_role_row is None else self.target_role_row.code

    # Frozen rank of the drafted role at finalize time, so a pick is a complete
    # ``(player, role, rank)`` record (resolved via ``ranks.role_rank``).
    target_rank_value: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="upcoming", default="upcoming")
    picked_player_id: Mapped[int | None] = mapped_column(
        ForeignKey("draft.player.id", ondelete="SET NULL"), nullable=True, index=True
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
    # None while the pick is on its main clock; stamped when the main clock ran
    # out and ``clock_expires_at`` was re-armed to the overtime deadline, so the
    # grace period is granted exactly once per pick.
    overtime_started_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
