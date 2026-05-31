from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.auth_user import AuthUser
    from shared.models.hero import Hero
    from shared.models.tournament import Tournament
    from shared.models.user import User
    from shared.models.workspace import Workspace

__all__ = (
    "BalancerApplication",
    "BalancerBalance",
    "BalancerBalanceVariant",
    "BalancerPlayer",
    "BalancerPlayerRoleEntry",
    "BalancerRegistration",
    "BalancerRegistrationForm",
    "BalancerRegistrationGoogleSheetBinding",
    "BalancerRegistrationGoogleSheetFeed",
    "BalancerRegistrationRole",
    "BalancerRegistrationRoleHero",
    "BalancerRegistrationStatus",
    "BalancerTeam",
    "BalancerTeamSlot",
    "BalancerTournamentConfig",
    "BalancerTournamentSheet",
)


class BalancerTournamentSheet(db.TimeStampIntegerMixin):
    __tablename__ = "tournament_sheet"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_balancer_tournament_sheet_tournament"),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    source_url: Mapped[str] = mapped_column(Text())
    sheet_id: Mapped[str] = mapped_column(String(255))
    gid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    header_row_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    column_mapping_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    role_mapping_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true", default=True)
    last_synced_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)

    tournament: Mapped["Tournament"] = relationship()
    applications: Mapped[list["BalancerApplication"]] = relationship(back_populates="tournament_sheet")


class BalancerApplication(db.TimeStampIntegerMixin):
    __tablename__ = "application"
    __table_args__ = (
        UniqueConstraint("tournament_id", "battle_tag_normalized", name="uq_balancer_application_tournament_tag"),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    tournament_sheet_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.tournament_sheet.id", ondelete="CASCADE"),
        index=True,
    )
    registration_id: Mapped[int | None] = mapped_column(
        ForeignKey("balancer.registration.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    battle_tag: Mapped[str] = mapped_column(String(255))
    battle_tag_normalized: Mapped[str] = mapped_column(String(255), index=True)
    smurf_tags_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    twitch_nick: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discord_nick: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stream_pov: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    last_tournament_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    primary_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    additional_roles_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    raw_row_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    submitted_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[db.DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true", default=True)

    tournament: Mapped["Tournament"] = relationship()
    tournament_sheet: Mapped["BalancerTournamentSheet"] = relationship(back_populates="applications")
    registration: Mapped["BalancerRegistration | None"] = relationship()
    player: Mapped["BalancerPlayer | None"] = relationship(back_populates="application", uselist=False)


class BalancerPlayer(db.TimeStampIntegerMixin):
    __tablename__ = "player"
    __table_args__ = (
        UniqueConstraint("application_id", name="uq_balancer_player_application"),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.application.id", ondelete="CASCADE"),
        index=True,
    )
    battle_tag: Mapped[str] = mapped_column(String(255))
    battle_tag_normalized: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("players.user.id", ondelete="SET NULL"), nullable=True, index=True)
    role_entries_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    is_flex: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    primary_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    secondary_roles_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    division_number: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    rank_value: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    is_in_pool: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true", default=True)
    admin_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)

    tournament: Mapped["Tournament"] = relationship()
    application: Mapped["BalancerApplication"] = relationship(back_populates="player")
    user: Mapped["User | None"] = relationship()
    role_entries: Mapped[list["BalancerPlayerRoleEntry"]] = relationship(back_populates="player")


class BalancerTournamentConfig(db.TimeStampIntegerMixin):
    __tablename__ = "tournament_config"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_balancer_tournament_config_tournament"),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}", default=dict)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)

    tournament: Mapped["Tournament"] = relationship()
    workspace: Mapped["Workspace"] = relationship()
    updater: Mapped["AuthUser | None"] = relationship()


class BalancerBalance(db.TimeStampIntegerMixin):
    __tablename__ = "balance"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_balancer_balance_tournament"),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="SET NULL"), nullable=True, index=True
    )
    algorithm: Mapped[str | None] = mapped_column(String(32), nullable=True)
    division_grid_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    division_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    saved_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    saved_at: Mapped[db.DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    exported_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    export_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    export_error: Mapped[str | None] = mapped_column(Text(), nullable=True)

    tournament: Mapped["Tournament"] = relationship()
    workspace: Mapped["Workspace | None"] = relationship()
    author: Mapped["AuthUser | None"] = relationship()
    teams: Mapped[list["BalancerTeam"]] = relationship(back_populates="balance")
    variants: Mapped[list["BalancerBalanceVariant"]] = relationship(back_populates="balance")


class BalancerTeam(db.TimeStampIntegerMixin):
    __tablename__ = "team"
    __table_args__ = ({"schema": "balancer"},)

    balance_id: Mapped[int] = mapped_column(ForeignKey("balancer.balance.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("balancer.balance_variant.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    exported_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.team.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    balancer_name: Mapped[str] = mapped_column(String(255))
    captain_battle_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avg_sr: Mapped[float] = mapped_column(Float())
    total_sr: Mapped[int] = mapped_column(Integer())
    roster_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")

    balance: Mapped["BalancerBalance"] = relationship(back_populates="teams")
    variant: Mapped["BalancerBalanceVariant | None"] = relationship()
    slots: Mapped[list["BalancerTeamSlot"]] = relationship(back_populates="team")


class BalancerPlayerRoleEntry(db.TimeStampIntegerMixin):
    """Normalized role entry for a balancer player (replaces role_entries_json)."""

    __tablename__ = "player_role_entry"
    __table_args__ = (
        UniqueConstraint("player_id", "role", name="uq_balancer_player_role_entry"),
        Index("ix_player_role_entry_role_active", "role", "is_active"),
        {"schema": "balancer"},
    )

    player_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.player.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(128), nullable=True)
    priority: Mapped[int] = mapped_column(Integer(), nullable=False)
    rank_value: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    division_number: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true", default=True)

    player: Mapped["BalancerPlayer"] = relationship(back_populates="role_entries")


class BalancerBalanceVariant(db.TimeStampIntegerMixin):
    """One solution variant produced by a balancer algorithm run."""

    __tablename__ = "balance_variant"
    __table_args__ = (
        UniqueConstraint("balance_id", "variant_number", name="uq_balancer_balance_variant"),
        {"schema": "balancer"},
    )

    balance_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.balance.id", ondelete="CASCADE"), index=True
    )
    variant_number: Mapped[int] = mapped_column(Integer(), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    objective_score: Mapped[float | None] = mapped_column(Float(), nullable=True)
    statistics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)

    balance: Mapped["BalancerBalance"] = relationship(back_populates="variants")
    teams: Mapped[list["BalancerTeam"]] = relationship(
        primaryjoin="BalancerTeam.variant_id == BalancerBalanceVariant.id",
        viewonly=True,
    )


class BalancerTeamSlot(db.TimeStampIntegerMixin):
    """One player's slot in a balanced team (replaces roster_json)."""

    __tablename__ = "team_slot"
    __table_args__ = (
        UniqueConstraint("team_id", "player_id", name="uq_balancer_team_slot"),
        {"schema": "balancer"},
    )

    team_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.team.id", ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int | None] = mapped_column(
        ForeignKey("balancer.player.id", ondelete="SET NULL"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    assigned_rank: Mapped[int] = mapped_column(Integer(), nullable=False)
    discomfort: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    is_captain: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)

    team: Mapped["BalancerTeam"] = relationship(back_populates="slots")
    player: Mapped["BalancerPlayer | None"] = relationship()


class BalancerRegistrationForm(db.TimeStampIntegerMixin):
    """Configuration of the registration form for a tournament."""

    __tablename__ = "registration_form"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_balancer_registration_form_tournament"),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    is_open: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    auto_approve: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    opens_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closes_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    built_in_fields_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default="{}", default=dict
    )
    custom_fields_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, server_default="[]", default=list
    )

    tournament: Mapped["Tournament"] = relationship()
    workspace: Mapped["Workspace"] = relationship()


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

    workspace: Mapped["Workspace"] = relationship()


class BalancerRegistration(db.TimeStampIntegerMixin):
    """A player's registration for a tournament and balancer source-of-truth row."""

    __tablename__ = "registration"
    __table_args__ = (
        Index(
            "uq_balancer_registration_user",
            "tournament_id",
            "auth_user_id",
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

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    auth_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.user.id", ondelete="SET NULL"), nullable=True, index=True
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
    is_flex: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    custom_fields_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending", default="pending")
    balancer_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="not_in_balancer", default="not_in_balancer"
    )
    checked_in: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    checked_in_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_in_by: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[db.DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True
    )
    balancer_profile_overridden_at: Mapped[db.DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tournament: Mapped["Tournament"] = relationship()
    workspace: Mapped["Workspace"] = relationship()
    auth_user: Mapped["AuthUser | None"] = relationship(foreign_keys=[auth_user_id])
    user: Mapped["User | None"] = relationship()
    reviewer: Mapped["AuthUser | None"] = relationship(foreign_keys=[reviewed_by])
    deleted_by_user: Mapped["AuthUser | None"] = relationship(foreign_keys=[deleted_by])
    checked_in_by_user: Mapped["AuthUser | None"] = relationship(foreign_keys=[checked_in_by])
    roles: Mapped[list["BalancerRegistrationRole"]] = relationship(
        back_populates="registration", cascade="all, delete-orphan"
    )
    google_sheet_binding: Mapped["BalancerRegistrationGoogleSheetBinding | None"] = relationship(
        back_populates="registration",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @hybrid_property
    def is_flex_computed(self) -> bool:
        """True when the player selected at least one role and all selected roles are primary."""
        return bool(self.roles) and all(role.is_primary for role in self.roles)


class BalancerRegistrationRole(db.TimeStampIntegerMixin):
    """Normalized role entry for a registration."""

    __tablename__ = "registration_role"
    __table_args__ = (
        UniqueConstraint("registration_id", "role", name="uq_balancer_registration_role"),
        {"schema": "balancer"},
    )

    registration_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.registration.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    subrole: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    priority: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    rank_value: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true", default=True)

    registration: Mapped["BalancerRegistration"] = relationship(back_populates="roles")
    hero_entries: Mapped[list["BalancerRegistrationRoleHero"]] = relationship(
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

    role_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.registration_role.id", ondelete="CASCADE"), index=True
    )
    hero_id: Mapped[int] = mapped_column(ForeignKey("overwatch.hero.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(Integer(), nullable=False)

    role: Mapped["BalancerRegistrationRole"] = relationship(back_populates="hero_entries")
    hero: Mapped["Hero"] = relationship()


class BalancerRegistrationGoogleSheetFeed(db.TimeStampIntegerMixin):
    __tablename__ = "registration_google_sheet_feed"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_balancer_registration_google_sheet_feed_tournament"),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True
    )
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

    tournament: Mapped["Tournament"] = relationship()
    bindings: Mapped[list["BalancerRegistrationGoogleSheetBinding"]] = relationship(
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

    feed: Mapped["BalancerRegistrationGoogleSheetFeed"] = relationship(back_populates="bindings")
    registration: Mapped["BalancerRegistration"] = relationship(back_populates="google_sheet_binding")
