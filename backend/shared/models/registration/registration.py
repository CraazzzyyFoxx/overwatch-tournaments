from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums

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
    "BalancerRegistrationTeam",
    "BalancerRegistrationTeamInvite",
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
    #: Bench size for team registration (decision 4): the roster ``RosterShape`` is
    #: strict, but an organizer may allow this many extra ``is_substitute`` members
    #: per team. Zero disables the bench entirely. Deliberately here and not on
    #: ``Tournament.roster_slots_json``: a substitute holds no starter slot, so the
    #: shape -- and the lock guarding it -- stay untouched.
    max_substitutes: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    # Subscription admission gate. ``require_subscription`` is the per-tournament
    # decision and stays here; the RULE it enforces does not. That moved to
    # ``subscriptions.requirement`` (one row per workspace) so a new tournament no
    # longer re-asks for it -- see the 2026-08-05 workspace-subscription-requirement
    # design. Resolve it through ``SubscriptionResolver.load_requirement``, never by
    # reading a column here.
    #
    # The former ``subscription_requirement_json`` attribute is gone from the mapper
    # AND from the schema: ``initial_v6`` squashed the subscription tables, and
    # ``registration_form`` there goes straight from ``require_subscription`` to
    # ``subscription_stage``. This comment used to warn that a ``wsreq0002``
    # migration would drop the column and break every form query while it was
    # still mapped -- that migration does not exist and will not, so the warning is
    # recorded here as history rather than left reading like an open task.
    require_subscription: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    #: WHEN the requirement bites, once ``require_subscription`` is on. Ordered, not
    #: a set -- ``registration`` implies check-in as well; see
    #: ``enums.SubscriptionEnforcementStage``. Plain String like
    #: ``open_profile_scope`` above, matching this schema's convention of storing
    #: enum-like values as their StrEnum text rather than a PG enum type (which
    #: would need a migration to add a value).
    subscription_stage: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=enums.SubscriptionEnforcementStage.check_in.value,
        default=enums.SubscriptionEnforcementStage.check_in.value,
    )

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
    boosty_nick: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stream_pov: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # Reason note for the current status, populated when balancer_status ==
    # "excluded" (why the registration was manually pulled from the pool).
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

    # ── Team registration (see docs/plans/2026-08-20-team-registration.md) ────
    # A registered team's roster IS a set of these rows; there is deliberately no
    # slot table, because a slot would carry its own state machine alongside
    # ``status`` and the two would have to be kept in sync forever. ``NULL`` means
    # "not on a team", so no backfill is needed for existing rows.
    registration_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("balancer.registration_team.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The captain-assigned roster slot. NOT derivable from ``roles``:
    # ``REGISTRATION_ROLE_CODES`` is tank/dps/support only, while ``flex`` is a
    # roster SLOT code, so a role-less roster's slot cannot be expressed as a
    # role row. Values are ``shared.domain.roster_shape.RosterSlotCode``.
    team_slot_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Bench member. Exported as ``Player.is_substitution=True`` with a NULL
    # ``related_player_id`` (nobody has been replaced yet); ``Team.avg_sr`` /
    # ``total_sr`` filter on ``is_substitution`` alone, so that stays correct.
    is_substitute: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)

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
    # Never lazy-loaded in async code: readers wanting the team must eager-load
    # it (the same standing rule as ``workspace_member`` above).
    registration_team: Mapped[BalancerRegistrationTeam | None] = relationship(
        back_populates="members",
        foreign_keys=[registration_team_id],
    )


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


class BalancerRegistrationTeam(db.TimeStampIntegerMixin):
    """A team registering for a tournament as a unit.

    Its roster is the set of ``BalancerRegistration`` rows pointing back here —
    ordinary registrations, so every existing gate, count and reader keeps
    working. Completeness is ``members grouped by team_slot_code`` compared to the
    tournament's resolved ``RosterShape``; ``status`` denormalizes that answer for
    indexable querying and is only ever written under the same row lock that
    accepts and kicks take, so it cannot drift.
    """

    __tablename__ = "registration_team"
    __table_args__ = (
        # Mirrors the export writer's dedup rule (it reuses a team whose
        # LOWERCASED name already exists in the tournament), which is what makes
        # a silent two-teams-become-one merge structurally impossible.
        Index(
            "uq_balancer_registration_team_name_active",
            "tournament_id",
            "name_normalized",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "ix_balancer_registration_team_tournament_status",
            "tournament_id",
            "status",
            postgresql_where="deleted_at IS NULL",
        ),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Lowercased ``name``, maintained by the service layer — same convention as
    #: ``BalancerRegistration.battle_tag_normalized``. The unique index above is
    #: on this, not on ``name``.
    name_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: The captain's own registration. Circular with
    #: ``BalancerRegistration.registration_team_id``, hence ``use_alter``.
    captain_registration_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "balancer.registration.id",
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

    tournament: Mapped[Tournament] = relationship()
    workspace: Mapped[Workspace] = relationship()
    members: Mapped[list[BalancerRegistration]] = relationship(
        back_populates="registration_team",
        foreign_keys="BalancerRegistration.registration_team_id",
    )
    captain_registration: Mapped[BalancerRegistration | None] = relationship(
        foreign_keys=[captain_registration_id],
        post_update=True,
    )
    invites: Mapped[list[BalancerRegistrationTeamInvite]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class BalancerRegistrationTeamInvite(db.TimeStampIntegerMixin):
    """An offer of one roster slot on a registering team.

    Deliberately NOT a placeholder ``BalancerRegistration``: an unaccepted invite
    has no person behind it, and a placeholder row would silently inflate
    ``get_registration_count_by_tournament`` — the public participant count —
    with no compile-time error anywhere.

    Two addressing modes share one row: ``target_auth_user_id`` for an in-app
    invite to a known account, and ``token_sha256`` for a shareable link to
    someone with no account yet. Both may be set.
    """

    __tablename__ = "registration_team_invite"
    __table_args__ = (
        # Only the HASH is stored (see the module docstring of the invite service):
        # redeeming this token creates a registration bound to the redeemer inside
        # a third party's roster, which puts it in the ApiKey tier, not the
        # scrim-room-address tier.
        Index(
            "uq_balancer_registration_team_invite_token",
            "token_sha256",
            unique=True,
            postgresql_where="token_sha256 IS NOT NULL",
        ),
        Index("ix_balancer_registration_team_invite_team_state", "team_id", "state"),
        {"schema": "balancer"},
    )

    team_id: Mapped[int] = mapped_column(ForeignKey("balancer.registration_team.id", ondelete="CASCADE"), index=True)
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
        ForeignKey("balancer.registration.id", ondelete="SET NULL"), nullable=True
    )

    team: Mapped[BalancerRegistrationTeam] = relationship(back_populates="invites")
    target_auth_user: Mapped[AuthUser | None] = relationship(foreign_keys=[target_auth_user_id])
    invited_by_user: Mapped[AuthUser | None] = relationship(foreign_keys=[invited_by])
    revoked_by_user: Mapped[AuthUser | None] = relationship(foreign_keys=[revoked_by])
