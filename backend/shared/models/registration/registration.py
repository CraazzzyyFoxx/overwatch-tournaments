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
    func,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import ColumnElement

from shared.core import db
from shared.models.catalog.role import CatalogRole, leaf_code
from shared.schemas.role import RoleRef

if TYPE_CHECKING:
    from shared.models.catalog.entity import CatalogEntity
    from shared.models.identity.auth_user import AuthUser
    from shared.models.tenancy.workspace import Workspace, WorkspaceMember
    from shared.models.tournament.tournament import Tournament

__all__ = (
    "Registration",
    "RegistrationEntry",
    "RegistrationForm",
    "RegistrationFormTemplate",
    "RegistrationFormVersion",
    "RegistrationGoogleSheetBinding",
    "RegistrationGoogleSheetFeed",
    "RegistrationIdentity",
    "RegistrationRole",
    "RegistrationRoleEntity",
    "RegistrationStatus",
    "RegistrationTeam",
    "RegistrationTeamInvite",
)


class RegistrationForm(db.TimeStampIntegerMixin):
    """Configuration of the registration form for a tournament."""

    __tablename__ = "form"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_registration_form_tournament"),
        {"schema": "registration"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    #: The schema the form currently asks. NULLABLE ON PURPOSE: ``registration_form``
    #: and ``registration_form_version`` point at each other, and PostgreSQL never
    #: defers a NOT NULL check, so a NOT NULL pointer could not be written for a
    #: version row that needs the form's id first. The service creates the form and
    #: version #1 in one flush; readers treat NULL as "not configured".
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("registration.form_version.id", ondelete="SET NULL"), nullable=True
    )
    require_open_profile: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    open_profile_scope: Mapped[str] = mapped_column(String(8), nullable=False, server_default="main", default="main")
    show_ranks: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    #: Collapses the PUBLIC participants list to an aggregate (count + per-role
    #: distribution). Enforced server-side in ``build_public_registration_list``:
    #: the list payload is cached anonymously, so a client-side hide would be
    #: cosmetic and a per-viewer branch would poison that cache. Organizers read
    #: the full roster through the admin registrations table instead.
    hide_registrations: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)

    tournament: Mapped[Tournament] = relationship()
    workspace: Mapped[Workspace] = relationship()
    #: Never lazy-loaded in async code: readers wanting the schema must eager-load
    #: it (the same standing rule as ``Registration.workspace_member``).
    #: ``post_update`` breaks the insert cycle -- the form row is inserted first,
    #: then UPDATEd with the id of the version it just created.
    current_version: Mapped[RegistrationFormVersion | None] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class RegistrationFormVersion(db.TimeStampIntegerMixin):
    """One immutable snapshot of a form's schema. Append-only: a save whose
    canonical JSON differs from the current version inserts number+1."""

    __tablename__ = "form_version"
    __table_args__ = (
        UniqueConstraint("form_id", "number", name="uq_registration_form_version_number"),
        {"schema": "registration"},
    )

    form_id: Mapped[int] = mapped_column(ForeignKey("registration.form.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer(), nullable=False)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)


class RegistrationFormTemplate(db.TimeStampIntegerMixin):
    """A workspace-level named schema, copied into a tournament's form on apply.

    Copy-on-apply: nothing links the tournament back to the template afterwards,
    so editing a template never rewrites a live form. Owned by one game
    (``discipline``): its identity question is that game's, and it applies to
    that game's tournaments only.
    """

    __tablename__ = "form_template"
    __table_args__ = (
        Index(
            "uq_registration_form_template_name",
            "workspace_id",
            text("lower(name)"),
            unique=True,
        ),
        {"schema": "registration"},
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    #: The game the template belongs to (``catalog.discipline.code``); immutable once created.
    discipline: Mapped[str] = mapped_column(
        String(32), ForeignKey("catalog.discipline.code", name="fk_registration_form_template_discipline")
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)


class RegistrationStatus(db.TimeStampIntegerMixin):
    __tablename__ = "status"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "scope",
            "slug",
            "kind",
            name="uq_registration_status_workspace_scope_slug",
        ),
        Index(
            "ix_registration_status_workspace_scope",
            "workspace_id",
            "scope",
        ),
        {"schema": "registration"},
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
    # Only meaningful for scope == "balancer" and kind == "custom": whether a
    # registration currently holding this status counts as part of the
    # balancer pool (mirrors the hardcoded semantics of the builtin
    # not_in_balancer/excluded statuses). Ignored for registration-scope rows
    # and for builtin overrides -- builtin inclusion semantics are fixed in
    # BUILTIN_STATUS_META, not admin-editable.
    excludes_from_balancer: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default="false", default=False
    )
    # Only meaningful for scope == "balancer" and kind == "custom": whether a
    # registration currently holding this status is treated as blocked from
    # the balancer pool's "ready" state, regardless of role-rank
    # completeness -- forces the "Need Fix" lane and the frontend's
    # exclude-from-run gate. Same non-editable-for-builtins rule as
    # excludes_from_balancer.
    excludes_from_ready: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)

    workspace: Mapped[Workspace] = relationship()


class Registration(db.TimeStampIntegerMixin):
    """A player's registration for a tournament and balancer source-of-truth row."""

    __tablename__ = "registration"
    __table_args__ = (
        Index(
            "uq_registration_user",
            "tournament_id",
            "workspace_member_id",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        {"schema": "registration"},
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
    stream_pov: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    #: The schema version this registration's answers were validated against;
    #: NULL for legacy/manual rows, which fall back to the form's current version.
    form_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("registration.form_version.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Player → everyone. Published on the public roster.
    public_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    #: Player → organizers. Never leaves an organizer context.
    organizer_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    admin_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    custom_fields_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    submitted_at: Mapped[db.DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    balancer_profile_overridden_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Team registration ────
    # A registered team's roster IS a set of these rows; there is deliberately no
    # slot table, because a slot would carry its own state machine alongside
    # ``status`` and the two would have to be kept in sync forever. ``NULL`` means
    # "not on a team", so no backfill is needed for existing rows.
    registration_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("registration.team.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Captain-assigned roster slot: a module role code or the open-slot key
    # ``flex``, which never creates a role assignment.
    team_slot_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Extra roster editor besides the unique captain. Managers may invite,
    #: kick, rename, reassign and cover a team subscription; they may not
    #: transfer, lock, disband or reject. Default false is "captain only".
    is_team_manager: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)

    tournament: Mapped[Tournament] = relationship()
    # Readers needing the domain player must eager-load this relationship
    # (selectinload / explicit join) — never rely on a lazy load in async code.
    workspace_member: Mapped[WorkspaceMember | None] = relationship()
    deleted_by_user: Mapped[AuthUser | None] = relationship(foreign_keys=[deleted_by])
    # Never lazy-loaded in async code: readers wanting the entries of one node query ``RegistrationEntry``.
    entries: Mapped[list[RegistrationEntry]] = relationship(back_populates="registration", passive_deletes=True)
    roles: Mapped[list[RegistrationRole]] = relationship(back_populates="registration", cascade="all, delete-orphan")
    google_sheet_binding: Mapped[RegistrationGoogleSheetBinding | None] = relationship(
        back_populates="registration",
        cascade="all, delete-orphan",
        uselist=False,
    )
    # Never lazy-loaded in async code: readers wanting the team must eager-load
    # it (the same standing rule as ``workspace_member`` above).
    registration_team: Mapped[RegistrationTeam | None] = relationship(
        back_populates="members",
        foreign_keys=[registration_team_id],
    )
    # Never lazy-loaded in async code: readers wanting the social handles or the
    # schema version must eager-load them (the same standing rule as
    # ``workspace_member`` above); ``registration_load_options`` does.
    identities: Mapped[list[RegistrationIdentity]] = relationship(
        back_populates="registration",
        cascade="all, delete-orphan",
        order_by=lambda: [RegistrationIdentity.provider, RegistrationIdentity.position],
    )
    form_version: Mapped[RegistrationFormVersion | None] = relationship(foreign_keys=[form_version_id])

    def handles(self, provider: str) -> list[str]:
        """This registration's handles for ``provider``, primary first."""
        return [row.handle for row in self.identities if row.provider == provider]

    def primary_handle(self, provider: str) -> str | None:
        return next((row.handle for row in self.identities if row.provider == provider and row.position == 0), None)

    def primary_game_identity(self, *, provider: str) -> RegistrationIdentity | None:
        """The primary handle this registration carries for ``provider`` (the owning
        tournament's identity provider): its identity for sheet keys, rosters and
        lookups. Never another provider's handle."""
        return next((row for row in self.identities if row.provider == provider and row.position == 0), None)


class RegistrationEntry(db.TimeStampIntegerMixin):
    """A registration's participation in ONE registration node (spec §4.5).

    The profile (:class:`Registration`) is one per ``(tournament, member)``; everything that depends on the intake the
    person joined lives here: the review decision, check-in, the balancer pool state and the reserve / substitute flags.
    """

    __tablename__ = "registration_entry"
    __table_args__ = (
        Index(
            "uq_registration_entry_node_registration",
            "registration_node_id",
            "registration_id",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "ix_registration_entry_node_balancer_status",
            "registration_node_id",
            "status",
            "balancer_status",
            postgresql_where="deleted_at IS NULL",
        ),
        {"schema": "registration"},
    )

    registration_node_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.flow_node.id", ondelete="RESTRICT"), index=True
    )
    registration_id: Mapped[int] = mapped_column(
        ForeignKey("registration.registration.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending", default="pending")
    checked_in: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    checked_in_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_in_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    balancer_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="not_in_balancer", default="not_in_balancer"
    )
    # Reason note for the current status, populated when balancer_status == "excluded" (why the entry was manually
    # pulled from the pool).
    exclude_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: "Call me in if a replacement is needed." The registrant's OWN declaration, answered through the ``reserve``
    #: builtin question. It is not a pool state: membership stays ``balancer_status``. Also imposed by the schedule --
    #: a sign-up past the open window's ``ends_at`` is a reserve whatever the answer said.
    is_reserve: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    # Bench member. Exported as ``Player.is_substitution=True`` with a NULL ``related_player_id`` (nobody has been
    # replaced yet); ``Team.avg_sr`` / ``total_sr`` filter on ``is_substitution`` alone, so that stays correct.
    is_substitute: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    reviewed_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    deleted_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)

    registration: Mapped[Registration] = relationship(back_populates="entries")
    reviewer: Mapped[AuthUser | None] = relationship(foreign_keys=[reviewed_by])
    checked_in_by_user: Mapped[AuthUser | None] = relationship(foreign_keys=[checked_in_by])


class RegistrationIdentity(db.TimeStampIntegerMixin):
    """One social handle the registrant gave for a provider (``identity_<provider>``).

    A provider may carry several handles (Battle.net smurfs): ``position`` 0 is
    the primary, the rest follow in the order given.
    """

    __tablename__ = "identity"
    # Deferred: rewriting a provider's handles in place (promoting a smurf to
    # primary swaps two rows' handles) passes through states that collide
    # mid-flush and are consistent again at commit.
    __table_args__ = (
        UniqueConstraint(
            "registration_id",
            "provider",
            "position",
            name="uq_registration_identity_position",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "registration_id",
            "provider",
            "handle_normalized",
            name="uq_registration_identity_handle",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_registration_identity_handle", "provider", "handle_normalized"),
        {"schema": "registration"},
    )

    registration_id: Mapped[int] = mapped_column(
        ForeignKey("registration.registration.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    handle_normalized: Mapped[str] = mapped_column(String(255), nullable=False)

    registration: Mapped[Registration] = relationship(back_populates="identities")


class RegistrationRole(db.TimeStampIntegerMixin):
    """One leaf catalog role per preference."""

    __tablename__ = "role"
    __table_args__ = (
        UniqueConstraint("registration_id", "role_id", name="uq_registration_role_role"),
        ForeignKeyConstraint(
            ["role_id", "dimension_id"],
            ["catalog.role.id", "catalog.role.dimension_id"],
            name="fk_registration_role_role",
            deferrable=True,
            initially="DEFERRED",
        ),
        {"schema": "registration"},
    )

    registration_id: Mapped[int] = mapped_column(
        ForeignKey("registration.registration.id", ondelete="CASCADE"), index=True
    )
    dimension_id: Mapped[int] = mapped_column(BigInteger())
    role_id: Mapped[int] = mapped_column(BigInteger(), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    priority: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    rank_value: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true", default=True)

    registration: Mapped[Registration] = relationship(back_populates="roles")
    catalog_role: Mapped[CatalogRole] = relationship(
        primaryjoin="foreign(RegistrationRole.role_id) == CatalogRole.id", foreign_keys=[role_id], lazy="joined"
    )
    hero_entries: Mapped[list[RegistrationRoleEntity]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
        order_by="RegistrationRoleEntity.priority",
    )

    @hybrid_property
    def role(self) -> str:
        leaf = self.catalog_role
        return leaf.parent.code if leaf.parent is not None else leaf.code

    @role.inplace.expression
    @classmethod
    def _role_expression(cls) -> ColumnElement[str]:
        return leaf_code(cls.role_id, top=True).correlate(cls).label("role")

    @hybrid_property
    def subrole(self) -> str | None:
        leaf = self.catalog_role
        return leaf.code if leaf.parent is not None else None

    @subrole.inplace.expression
    @classmethod
    def _subrole_expression(cls) -> ColumnElement[str | None]:
        return leaf_code(cls.role_id, top=False).correlate(cls).label("subrole")

    @property
    def role_ref(self) -> RoleRef:
        return RoleRef.of(self.catalog_role.dimension.code, self.role, self.subrole)


class RegistrationRoleEntity(db.TimeStampIntegerMixin):
    """Ordered preferred catalog entity ("top hero") of a registration role entry."""

    __tablename__ = "role_entity"
    # DEFERRED (migration ``reghero01``): a pick list is replaced wholesale, and SQLAlchemy emits every INSERT for a
    # table before the DELETEs on it -- so a resave that keeps an entity, or a reorder, passes through a duplicate
    # state mid-flush and ends in a valid one. Checking at COMMIT makes both legal without weakening the invariant.
    __table_args__ = (
        UniqueConstraint(
            "role_id", "priority", name="uq_reg_role_entity_role_priority", deferrable=True, initially="DEFERRED"
        ),
        UniqueConstraint(
            "role_id", "entity_id", name="uq_reg_role_entity_role_entity", deferrable=True, initially="DEFERRED"
        ),
        CheckConstraint("entity_kind = 'character'", name="ck_registration_role_entity_kind"),
        ForeignKeyConstraint(
            ["entity_id", "entity_kind"],
            ["catalog.entity.id", "catalog.entity.kind"],
            ondelete="CASCADE",
            name="fk_registration_role_entity_entity",
        ),
        {"schema": "registration"},
    )

    role_id: Mapped[int] = mapped_column(ForeignKey("registration.role.id", ondelete="CASCADE"), index=True)
    entity_id: Mapped[int] = mapped_column(BigInteger())
    entity_kind: Mapped[str] = mapped_column(String(16), default="character", server_default="character")
    priority: Mapped[int] = mapped_column(Integer(), nullable=False)

    role: Mapped[RegistrationRole] = relationship(back_populates="hero_entries")
    entity: Mapped[CatalogEntity] = relationship(
        primaryjoin="foreign(RegistrationRoleEntity.entity_id) == CatalogEntity.id", viewonly=True
    )


class RegistrationGoogleSheetFeed(db.TimeStampIntegerMixin):
    __tablename__ = "google_sheet_feed"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_registration_google_sheet_feed_tournament"),
        {"schema": "registration"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    #: The registration node the sheet's rows become entries of.
    registration_node_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.flow_node.id", ondelete="RESTRICT"), index=True
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

    tournament: Mapped[Tournament] = relationship()
    bindings: Mapped[list[RegistrationGoogleSheetBinding]] = relationship(
        back_populates="feed",
        cascade="all, delete-orphan",
    )


class RegistrationGoogleSheetBinding(db.TimeStampIntegerMixin):
    __tablename__ = "google_sheet_binding"
    __table_args__ = (
        UniqueConstraint("feed_id", "source_record_key", name="uq_registration_google_sheet_binding_key"),
        UniqueConstraint("registration_id", name="uq_registration_google_sheet_binding_registration"),
        {"schema": "registration"},
    )

    feed_id: Mapped[int] = mapped_column(
        ForeignKey("registration.google_sheet_feed.id", ondelete="CASCADE"),
        index=True,
    )
    registration_id: Mapped[int] = mapped_column(
        ForeignKey("registration.registration.id", ondelete="CASCADE"),
        index=True,
    )
    source_record_key: Mapped[str] = mapped_column(String(255))
    raw_row_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    parsed_fields_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    row_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_seen_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    feed: Mapped[RegistrationGoogleSheetFeed] = relationship(back_populates="bindings")
    registration: Mapped[Registration] = relationship(back_populates="google_sheet_binding")


class RegistrationTeam(db.TimeStampIntegerMixin):
    """A team registering for a tournament as a unit.

    Its roster is the set of ``Registration`` rows pointing back here —
    ordinary registrations, so every existing gate, count and reader keeps
    working. Completeness is ``members grouped by team_slot_code`` compared to the
    tournament's resolved ``RosterShape``; ``status`` denormalizes that answer for
    indexable querying and is only ever written under the same row lock that
    accepts and kicks take, so it cannot drift.
    """

    __tablename__ = "team"
    __table_args__ = (
        # Mirrors the export writer's dedup rule (it reuses a team whose
        # LOWERCASED name already exists in the tournament), which is what makes
        # a silent two-teams-become-one merge structurally impossible.
        Index(
            "uq_registration_team_name_active",
            "tournament_id",
            "name_normalized",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "ix_registration_team_tournament_status",
            "tournament_id",
            "status",
            postgresql_where="deleted_at IS NULL",
        ),
        {"schema": "registration"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    #: The registration node the team signs up through; its members' entries live in the same node.
    registration_node_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.flow_node.id", ondelete="RESTRICT"), index=True
    )
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Lowercased ``name``, maintained by the service layer — same convention as
    #: ``RegistrationIdentity.handle_normalized``. The unique index above is
    #: on this, not on ``name``.
    name_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: The captain's own registration. Circular with
    #: ``Registration.registration_team_id``, hence ``use_alter``.
    captain_registration_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "registration.registration.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_registration_team_captain_registration",
        ),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="forming", default="forming")
    #: Set when the team is materialized into ``tournament.team`` — the only DB
    #: link from the pre-formation domain to the final row, mirroring
    #: ``DraftTeam.exported_team_id``.
    exported_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.team.id", ondelete="SET NULL"), nullable=True, index=True
    )
    exported_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    export_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    export_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    deleted_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    #: Watermark for the cumulative invite cap, not a counter.
    #:
    #: The cap is a COUNT over every invite the team ever created, so "reset" can
    #: only mean "stop counting the ones before this moment". Deleting the old rows
    #: would be the other way to do it and is worse: the invite history is now a
    #: read, and an organizer clearing a cap would silently erase the evidence of
    #: whatever abuse made them clear it.
    invite_cap_reset_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invite_cap_reset_by: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True
    )
    #: Organizer axis, independent of occupancy ``status``. Occupancy still
    #: writes ``forming``/``complete``; this is pending/accepted/waitlisted.
    #: Reject stays a ``status`` (terminal + ``deleted_at``), not an admission.
    admission: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending", default="pending")
    rejection_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    #: Staff-only notes. Never serialized on the public team read.
    organizer_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    roster_locked_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    roster_locked_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    #: Team-scoped subscription stamp. Validity follows ``subscription_expires_at``
    #: rather than re-reading the redeemer's personal entitlement, so a captaincy
    #: transfer cannot drop a paid roster.
    subscription_covered_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription_covered_by: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True
    )
    subscription_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subscription_tier_rank: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    subscription_expires_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tournament: Mapped[Tournament] = relationship()
    workspace: Mapped[Workspace] = relationship()
    members: Mapped[list[Registration]] = relationship(
        back_populates="registration_team",
        foreign_keys="Registration.registration_team_id",
    )
    captain_registration: Mapped[Registration | None] = relationship(
        foreign_keys=[captain_registration_id],
        post_update=True,
    )
    invites: Mapped[list[RegistrationTeamInvite]] = relationship(back_populates="team", cascade="all, delete-orphan")


class RegistrationTeamInvite(db.TimeStampIntegerMixin):
    """An offer of one roster slot on a registering team.

    Deliberately NOT a placeholder ``Registration``: an unaccepted invite
    has no person behind it, and a placeholder row would silently inflate
    ``get_registration_count_by_tournament`` — the public participant count —
    with no compile-time error anywhere.

    Two addressing modes share one row: ``target_auth_user_id`` for an in-app
    invite to a known account, and ``token_sha256`` for a shareable link to
    someone with no account yet. Both may be set.
    """

    __tablename__ = "team_invite"
    __table_args__ = (
        # Only the HASH is stored (see the module docstring of the invite service):
        # redeeming this token creates a registration bound to the redeemer inside
        # a third party's roster, which puts it in the ApiKey tier, not the
        # scrim-room-address tier.
        Index(
            "uq_registration_team_invite_token",
            "token_sha256",
            unique=True,
            postgresql_where="token_sha256 IS NOT NULL",
        ),
        Index("ix_registration_team_invite_team_state", "team_id", "state"),
        {"schema": "registration"},
    )

    team_id: Mapped[int] = mapped_column(ForeignKey("registration.team.id", ondelete="CASCADE"), index=True)
    slot_code: Mapped[str] = mapped_column(String(16), nullable=False)
    is_substitute: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    target_auth_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: ``sha256`` of the raw token, which is returned exactly once at creation.
    token_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending", default="pending")
    invited_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    invited_at: Mapped[db.DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    #: Who withdrew the offer, and when. A captain and an ORGANIZER can both
    #: revoke, and those are materially different events: a captain changing their
    #: mind needs no explanation, an organizer reaching into someone else's roster
    #: does. Without this the two are indistinguishable after the fact, which makes
    #: the organizer power unauditable.
    revoked_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    revoked_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Whether staff took the offer away, recorded by the entry point that knows
    #: rather than inferred at read time. Comparing the revoker against "the
    #: captain" would be a lie: captaincy transfers, so the captain now is not
    #: necessarily the captain then.
    revoked_by_organizer: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    accepted_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_registration_id: Mapped[int | None] = mapped_column(
        ForeignKey("registration.registration.id", ondelete="SET NULL"), nullable=True
    )

    team: Mapped[RegistrationTeam] = relationship(back_populates="invites")
    target_auth_user: Mapped[AuthUser | None] = relationship(foreign_keys=[target_auth_user_id])
    invited_by_user: Mapped[AuthUser | None] = relationship(foreign_keys=[invited_by])
    revoked_by_user: Mapped[AuthUser | None] = relationship(foreign_keys=[revoked_by])
