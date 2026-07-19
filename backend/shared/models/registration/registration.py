from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.catalog.hero import Hero
    from shared.models.identity.auth_user import AuthUser
    from shared.models.tenancy.workspace import Workspace, WorkspaceMember
    from shared.models.tournament.tournament import Tournament

__all__ = (
    "BalancerRegistration",
    "BalancerRegistrationForm",
    "BalancerRegistrationGoogleSheetBinding",
    "BalancerRegistrationGoogleSheetFeed",
    "BalancerRegistrationRole",
    "BalancerRegistrationRoleHero",
    "BalancerRegistrationStatus",
)


class BalancerRegistrationForm(db.TimeStampIntegerMixin):
    """Configuration of the registration form for a tournament."""

    __tablename__ = "registration_form"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_balancer_registration_form_tournament"),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    is_open: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    auto_approve: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    built_in_fields_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default="{}", default=dict
    )
    custom_fields_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, server_default="[]", default=list
    )
    require_open_profile: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    open_profile_scope: Mapped[str] = mapped_column(String(8), nullable=False, server_default="main", default="main")
    show_ranks: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)

    tournament: Mapped[Tournament] = relationship()
    workspace: Mapped[Workspace] = relationship()


class BalancerRegistrationStatus(db.TimeStampIntegerMixin):
    __tablename__ = "registration_status"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "scope",
            "slug",
            "kind",
            name="uq_balancer_registration_status_workspace_scope_slug",
        ),
        Index(
            "ix_balancer_registration_status_workspace_scope",
            "workspace_id",
            "scope",
        ),
        {"schema": "balancer"},
    )

    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="custom", server_default="custom")
    icon_slug: Mapped[str | None] = mapped_column(String(128), nullable=True)
    icon_color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)

    workspace: Mapped[Workspace] = relationship()


class BalancerRegistration(db.TimeStampIntegerMixin):
    """A player's registration for a tournament and balancer source-of-truth row."""

    __tablename__ = "registration"
    __table_args__ = (
        Index(
            "uq_balancer_registration_user",
            "tournament_id",
            "workspace_member_id",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "uq_balancer_registration_tournament_tag_active",
            "tournament_id",
            "battle_tag_normalized",
            unique=True,
            postgresql_where="battle_tag_normalized IS NOT NULL AND deleted_at IS NULL",
        ),
        Index(
            "ix_balancer_registration_tournament_active",
            "tournament_id",
            "status",
            "exclude_from_balancer",
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "ix_balancer_registration_tournament_balancer_status",
            "tournament_id",
            "status",
            "balancer_status",
            postgresql_where="deleted_at IS NULL",
        ),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    # Sole identity anchor (dbarch02 dropped the legacy user_id column): the
    # domain player is reached via workspace_member.player_id. Nullable — a
    # registration with no member has no player identity at all (e.g. an
    # admin-created manual row, or a sheet row whose identity provisioning
    # was skipped).
    workspace_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace_member.id", ondelete="SET NULL"), nullable=True, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    battle_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    battle_tag_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smurf_tags_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    discord_nick: Mapped[str | None] = mapped_column(String(255), nullable=True)
    twitch_nick: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stream_pov: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    exclude_from_balancer: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default="false", default=False
    )
    exclude_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    admin_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    custom_fields_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending", default="pending")
    balancer_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="not_in_balancer", default="not_in_balancer"
    )
    checked_in: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    checked_in_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_in_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    submitted_at: Mapped[db.DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    deleted_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    balancer_profile_overridden_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tournament: Mapped[Tournament] = relationship()
    # Readers needing the domain player must eager-load this relationship
    # (selectinload / explicit join) — never rely on a lazy load in async code.
    workspace_member: Mapped[WorkspaceMember | None] = relationship()
    reviewer: Mapped[AuthUser | None] = relationship(foreign_keys=[reviewed_by])
    deleted_by_user: Mapped[AuthUser | None] = relationship(foreign_keys=[deleted_by])
    checked_in_by_user: Mapped[AuthUser | None] = relationship(foreign_keys=[checked_in_by])
    roles: Mapped[list[BalancerRegistrationRole]] = relationship(
        back_populates="registration", cascade="all, delete-orphan"
    )
    google_sheet_binding: Mapped[BalancerRegistrationGoogleSheetBinding | None] = relationship(
        back_populates="registration",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @hybrid_property
    def is_flex_computed(self) -> bool:
        """True when the player has more than one role and all are primary (full flex)."""
        return len(self.roles) > 1 and all(role.is_primary for role in self.roles)


class BalancerRegistrationRole(db.TimeStampIntegerMixin):
    """Normalized role entry for a registration."""

    __tablename__ = "registration_role"
    __table_args__ = (
        UniqueConstraint("registration_id", "role", name="uq_balancer_registration_role"),
        {"schema": "balancer"},
    )

    registration_id: Mapped[int] = mapped_column(ForeignKey("balancer.registration.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    subrole: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    priority: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    rank_value: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true", default=True)

    registration: Mapped[BalancerRegistration] = relationship(back_populates="roles")
    hero_entries: Mapped[list[BalancerRegistrationRoleHero]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
        order_by="BalancerRegistrationRoleHero.priority",
    )


class BalancerRegistrationRoleHero(db.TimeStampIntegerMixin):
    """Ordered hero preference ("top hero") for a registration role entry."""

    __tablename__ = "registration_role_hero"
    __table_args__ = (
        UniqueConstraint("role_id", "priority", name="uq_reg_role_hero_role_priority"),
        UniqueConstraint("role_id", "hero_id", name="uq_reg_role_hero_role_hero"),
        {"schema": "balancer"},
    )

    role_id: Mapped[int] = mapped_column(ForeignKey("balancer.registration_role.id", ondelete="CASCADE"), index=True)
    hero_id: Mapped[int] = mapped_column(ForeignKey("overwatch.hero.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(Integer(), nullable=False)

    role: Mapped[BalancerRegistrationRole] = relationship(back_populates="hero_entries")
    hero: Mapped[Hero] = relationship()


class BalancerRegistrationGoogleSheetFeed(db.TimeStampIntegerMixin):
    __tablename__ = "registration_google_sheet_feed"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_balancer_registration_google_sheet_feed_tournament"),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    source_url: Mapped[str] = mapped_column(Text())
    sheet_id: Mapped[str] = mapped_column(String(255))
    gid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    auto_sync_interval_seconds: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        server_default="300",
        default=300,
    )
    header_row_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    mapping_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    value_mapping_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_synced_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)

    tournament: Mapped[Tournament] = relationship()
    bindings: Mapped[list[BalancerRegistrationGoogleSheetBinding]] = relationship(
        back_populates="feed",
        cascade="all, delete-orphan",
    )


class BalancerRegistrationGoogleSheetBinding(db.TimeStampIntegerMixin):
    __tablename__ = "registration_google_sheet_binding"
    __table_args__ = (
        UniqueConstraint("feed_id", "source_record_key", name="uq_balancer_registration_google_sheet_binding_key"),
        UniqueConstraint("registration_id", name="uq_balancer_registration_google_sheet_binding_registration"),
        {"schema": "balancer"},
    )

    feed_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.registration_google_sheet_feed.id", ondelete="CASCADE"),
        index=True,
    )
    registration_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.registration.id", ondelete="CASCADE"),
        index=True,
    )
    source_record_key: Mapped[str] = mapped_column(String(255))
    raw_row_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    parsed_fields_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    row_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_seen_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    feed: Mapped[BalancerRegistrationGoogleSheetFeed] = relationship(back_populates="bindings")
    registration: Mapped[BalancerRegistration] = relationship(back_populates="google_sheet_binding")
