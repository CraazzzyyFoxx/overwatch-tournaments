"""Pydantic schemas for tournament registration."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from shared.core.enums import SubscriptionEnforcementStage
from shared.services.subscriptions import VERIFICATION_METHODS, VerificationMethod, parse_requirement
from src.schemas.admission import AdmissionRead
from src.schemas.division_grid import DivisionGridVersionRead

# ---------------------------------------------------------------------------
# Registration form (config)
# ---------------------------------------------------------------------------


class FieldValidationConfig(BaseModel):
    regex: str | None = None
    error_message: str | None = None


class CustomFieldDefinition(BaseModel):
    key: str
    label: str
    type: Literal["text", "number", "select", "checkbox", "url"] = "text"
    required: bool = False
    placeholder: str | None = None
    options: list[str] | None = None
    validation: FieldValidationConfig | None = None
    # Whether this answer is surfaced in the live draft's player inspector.
    # Off by default and per-field on purpose: the draft board is PUBLIC, so
    # showing an answer there is an explicit organizer decision, not a
    # consequence of asking the question. Read by balancer-service
    # (services/draft/board.py) straight off ``custom_fields_json``.
    show_in_draft: bool = False


class BuiltInFieldConfig(BaseModel):
    enabled: bool = True
    required: bool = False
    subroles: dict[str, list[str]] | None = None
    validation: FieldValidationConfig | None = None
    # ``top_heroes`` field only: max heroes a player may select per role (default 5).
    max_heroes: int | None = None
    # Identity fields (battle_tag/discord_nick/twitch_nick) only: when true the
    # submitted handle must match one of the registrant's OAuth-verified social
    # accounts for the field's provider. Implies the field is effectively required.
    require_verified: bool = False
    # ``flex_role`` field only. None/absent == "optional", so every existing form
    # keeps its current behaviour.
    #
    # - "optional"  — the registrant picks which roles they play at all; flex is
    #   an opt-in preset.
    # - "all_roles" — every role is mandatory; the registrant names exactly one
    #   priority role, or declares flex. Their non-priority roles keep carrying
    #   discomfort, so the solver keeps a real balance-versus-comfort trade-off.
    # - "forced"    — every role is mandatory AND every role primary. There is no
    #   choice, and discomfort is nil everywhere, which collapses that trade-off
    #   to sub-role collisions alone.
    #
    # Both non-optional modes rate a player by their highest rank across all
    # roles: balancer eligibility is the presence of a rating for a role, so
    # requiring readiness to play anything requires a rating for everything.
    mode: Literal["optional", "all_roles", "forced"] | None = None


class SubroleOption(BaseModel):
    slug: str
    label: str


class RegistrationFormRead(BaseModel):
    id: int
    tournament_id: int
    workspace_id: int
    # DERIVED, read-only: "is registration open right now", computed from the
    # tournament's REGISTRATION phase-schedule window. No longer a column on the
    # form — see shared.services.registration_window.
    is_open: bool
    auto_approve: bool = False
    require_open_profile: bool = False
    open_profile_scope: str = "main"
    show_ranks: bool = False
    require_subscription: bool = False
    # WHEN the requirement bites, once the toggle above is on. See
    # ``enums.SubscriptionEnforcementStage``: ``registration`` implies check-in too.
    subscription_stage: SubscriptionEnforcementStage = SubscriptionEnforcementStage.check_in
    # Server-resolved from the workspace's requirement and READ-ONLY: the rule is no
    # longer a property of the form (see WorkspaceSubscriptionRequirementUpsert). It
    # stays on the read model because the public check-in dialog and the wizard's
    # review step render it, and there is no value in teaching every public consumer
    # about a new table.
    subscription_requirement_json: dict[str, Any] = Field(default_factory=dict)
    built_in_fields: dict[str, BuiltInFieldConfig] = Field(default_factory=dict)
    custom_fields: list[CustomFieldDefinition] = Field(default_factory=list)
    #: Bench size for team registration. Zero disables substitutes. Not a starter
    #: slot — see ``BalancerRegistrationForm.max_substitutes``.
    max_substitutes: int = Field(default=0, ge=0)
    #: ``player`` (default) keeps the per-entrant subscription gate. ``team`` is
    #: "the captain pays": a stamp on the registered team covers the roster.
    subscription_scope: Literal["player", "team"] = "player"
    team_rank_min: int | None = Field(default=None, ge=0)
    team_rank_max: int | None = Field(default=None, ge=0)
    team_max_rank_spread: int | None = Field(default=None, ge=0)
    team_unique_identity: bool = False
    team_require_discord_guild: bool = False
    # Workspace sub-role catalog keyed by registration role code (tank/dps/support).
    # The single source of truth for available sub-roles; per-tournament
    # built_in_fields[*].subroles selects which of these are offered.
    subrole_catalog: dict[str, list[SubroleOption]] = Field(default_factory=dict)


class RegistrationFormUpsert(BaseModel):
    # No `subscription_requirement_json`: the rule is workspace-scoped now. No
    # `is_open` either: registration openness is the tournament's REGISTRATION
    # schedule window, so the form has no say. A stale client that still sends
    # either one is TOLERATED, not rejected -- Pydantic's default `extra="ignore"`
    # drops the key and the rest of the save succeeds. Deliberate: no schema in
    # this module sets `extra`, and turning every unknown field into a 422 is a
    # separate decision with a much wider blast radius than these moves.
    auto_approve: bool = False
    require_open_profile: bool = False
    open_profile_scope: str = "main"
    show_ranks: bool = False
    require_subscription: bool = False
    # Defaults to the looser stage, so a client that does not know the field yet
    # cannot silently turn a check-in requirement into a sign-up wall.
    subscription_stage: SubscriptionEnforcementStage = SubscriptionEnforcementStage.check_in
    built_in_fields: dict[str, BuiltInFieldConfig] = Field(default_factory=dict)
    #: Omitted by an older client becomes 0, same as every other field on this
    #: full-replace upsert. The builder always sends it.
    max_substitutes: int = Field(default=0, ge=0)
    #: Omitted by an older client becomes ``player``, same full-replace trap as
    #: ``max_substitutes``. The builder always sends it.
    subscription_scope: Literal["player", "team"] = "player"
    team_rank_min: int | None = Field(default=None, ge=0)
    team_rank_max: int | None = Field(default=None, ge=0)
    team_max_rank_spread: int | None = Field(default=None, ge=0)
    team_unique_identity: bool = False
    team_require_discord_guild: bool = False
    custom_fields: list[CustomFieldDefinition] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Registration (public user-facing)
# ---------------------------------------------------------------------------


class RoleWithSubrole(BaseModel):
    role: str
    subrole: str | None = None
    is_primary: bool = False
    # Ordered hero slugs (top picks). Length capped by built_in_fields.top_heroes.max_heroes.
    top_heroes: list[str] | None = None


class RegistrationCreate(BaseModel):
    battle_tag: str | None = None
    smurf_tags: list[str] | None = None
    discord_nick: str | None = None
    twitch_nick: str | None = None
    boosty_nick: str | None = None
    roles: list[RoleWithSubrole] | None = None
    stream_pov: bool = False
    notes: str | None = None
    custom_fields: dict[str, Any] | None = None


class RegistrationUpdate(BaseModel):
    battle_tag: str | None = None
    discord_nick: str | None = None
    twitch_nick: str | None = None
    boosty_nick: str | None = None
    # No ``primary_role``: the column was normalized away into
    # ``balancer.registration_role`` (migration q7l9m1n5o6p7). It stayed on this
    # schema long after that, so the write path had nowhere to put it.
    stream_pov: bool | None = None
    notes: str | None = None
    custom_fields: dict[str, Any] | None = None


class RegistrationRoleRead(BaseModel):
    role: str
    subrole: str | None = None
    is_primary: bool = False
    priority: int = 0
    rank_value: int | None = None
    top_heroes: list[str] = Field(default_factory=list)  # ordered hero slugs


class RegistrationTeamBrief(BaseModel):
    """The registered team a roster read carries inline.

    Deliberately not the full ``RegistrationTeamRead``: this rides in every row of
    the public participants list, so it holds only what a team column and the
    §12.5 status line need. In particular it carries **no invites** — a public
    roster must not leak who has been asked and declined.
    """

    id: int
    name: str
    status: str
    slot_code: str | None = None
    is_substitute: bool = False
    is_captain: bool = False


class RegistrationRead(BaseModel):
    id: int
    tournament_id: int
    workspace_id: int
    user_id: int | None = None
    battle_tag: str | None = None
    smurf_tags_json: list[str] | None = None
    discord_nick: str | None = None
    twitch_nick: str | None = None
    boosty_nick: str | None = None
    stream_pov: bool = False
    roles: list[RegistrationRoleRead] = Field(default_factory=list)
    notes: str | None = None
    custom_fields_json: dict[str, Any] | None = None
    status: str = "pending"
    status_meta: dict[str, Any] | None = None
    balancer_status: str = "not_in_balancer"
    balancer_status_meta: dict[str, Any] | None = None
    checked_in: bool = False
    # The single admission answer, computed server-side. Never ``None``: a
    # registration the list did not resolve carries ``AdmissionRead.unknown()``,
    # so no consumer needs a null branch -- the five client-side re-derivations
    # this replaced all grew out of per-consumer defaulting.
    admission: AdmissionRead = Field(default_factory=AdmissionRead.unknown)
    # All-profiles-open verdict when the tournament requires it:
    # True = public, False = closed, None = unknown / not required.
    profiles_open: bool | None = None
    # Subscription admission verdict when the tournament requires one.
    # ``subscription_outcome`` is the COMPOSED answer ("satisfied"/"refused"/
    # "undetermined"); only "refused" blocks, mirroring ``profiles_open is False``.
    # ``subscription_verdicts`` is per provider and drives the per-row chips —
    # under ``any`` mode one red chip next to a green one is still a pass, which is
    # why the composed outcome is sent separately rather than derived client-side.
    subscription_outcome: str | None = None
    subscription_verdicts: dict[str, Any] | None = None
    # Team registration: which registered team this player belongs to, if any.
    # Present on the PUBLIC roster because the participants table needs a team
    # column and the "Your Registration" card must be able to say "your team is
    # still incomplete" — §12.5's whole point is that the people in a stuck team
    # learn it from their own card, not from an admin-only list.
    team: RegistrationTeamBrief | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None


class TournamentHistoryEntry(BaseModel):
    tournament_id: int
    tournament_name: str
    role: str | None = None
    division: int | None = None
    # References a version in ``RegistrationListResponse.division_grids`` instead of
    # embedding the (large) version per entry. ``None`` when the rank/division is unknown.
    division_grid_version_id: int | None = None


class SubscriptionRedeemRequest(BaseModel):
    """Body of the challenge-code redemption endpoint.

    ``provider`` defaults to ``boosty`` because the challenge code exists
    specifically for it -- Twitch has a real API and needs no code.
    """

    code: str = Field(min_length=1, max_length=128)
    provider: str = "boosty"


class SubscriptionProviderVerdictRead(BaseModel):
    """One provider's verdict, as shown to the patron.

    Deliberately narrow: ``evidence`` may hold guild ids and role ids, so only
    ``reason`` is exposed -- the UI branches on it to pick a call to action
    ("link Discord" vs "reconnect Twitch").
    """

    state: str
    tier_rank: int | None = None
    tier_label: str | None = None
    reason: str | None = None
    # Whether pasting a code can help HERE. Not derivable from `reason`: under the
    # permissive method an unlinked patron reports `no_linked_discord_account`, and a
    # code would ALSO satisfy them — so the UI cannot infer this and would either
    # hide a working input or offer one the server is about to reject.
    code_accepted: bool = False


class SubscriptionStatusRead(BaseModel):
    """The caller's own subscription standing for one tournament.

    ``outcome`` is the COMPOSED answer over the tournament's requirement;
    ``verdicts`` is per provider so the form can render a chip per account row.
    ``required`` is false when the tournament does not gate on a subscription, in
    which case the rest is informational only.
    """

    required: bool = False
    mode: str | None = None
    outcome: str | None = None
    rule: str | None = None
    # Whether signing up is refused right now. Narrower than ``outcome == refused``:
    # a provider the patron can still satisfy with a challenge code is deferred,
    # because that field only exists at check-in. The form uses it to explain the
    # block up front instead of letting submit answer 400.
    blocks_registration: bool = False
    verdicts: dict[str, SubscriptionProviderVerdictRead] = Field(default_factory=dict)


# ── workspace subscription provider config ──────────────────────────────────
#
# Minimal surface on purpose: raw ids typed by hand. Resolving Discord role names
# through the API and offering a picker is the "more elegant" follow-up.

_SUBSCRIPTION_PROVIDERS = ("boosty", "twitch")


class RoleTierUpsert(BaseModel):
    """One ``discord role -> subscription tier`` mapping.

    ``role_id`` is a string because a Discord snowflake exceeds 2**53 and must
    never survive a float round-trip.
    """

    role_id: str = Field(min_length=1, max_length=32)
    tier_rank: int = Field(default=1, ge=1, le=100)
    tier_label: str = Field(default="", max_length=64)


class ChallengeCodeUpsert(BaseModel):
    """A challenge code, supplied either as plaintext (new) or as its digest.

    Plaintext is hashed server-side and never persisted. The digest form exists so
    the redacted read model can be sent back unchanged without double-hashing.
    """

    code: str | None = Field(default=None, min_length=1, max_length=128)
    code_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    tier_rank: int = Field(default=1, ge=1, le=100)
    tier_label: str = Field(default="", max_length=64)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _needs_one_form(self) -> ChallengeCodeUpsert:
        if not self.code and not self.code_sha256:
            raise ValueError("a code row needs either `code` or `code_sha256`")
        return self


class SubscriptionProviderConfigUpsert(BaseModel):
    """Per-workspace provider setup.

    Every field except ``provider``/``enabled`` is optional and OMITTING it keeps
    whatever is stored. That matters most for ``codes``: the admin never sees the
    existing ones (only digests are kept), so a plain save must not wipe them.
    Passing an explicit list replaces them.
    """

    provider: str
    enabled: bool = False
    role_tiers: list[RoleTierUpsert] | None = None
    broadcaster_id: str | None = Field(default=None, max_length=32)
    broadcaster_login: str | None = Field(default=None, max_length=64)
    codes: list[ChallengeCodeUpsert] | None = None
    verification_method: str | None = None

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        if value not in _SUBSCRIPTION_PROVIDERS:
            raise ValueError(f"provider must be one of {_SUBSCRIPTION_PROVIDERS}")
        return value

    @field_validator("role_tiers")
    @classmethod
    def _unique_roles(cls, value: list[RoleTierUpsert] | None) -> list[RoleTierUpsert] | None:
        if value is None:
            return value
        seen: set[str] = set()
        for row in value:
            if row.role_id in seen:
                raise ValueError(f"duplicate role_id {row.role_id!r}")
            seen.add(row.role_id)
        return value

    @field_validator("verification_method")
    @classmethod
    def _known_method(cls, value: str | None) -> str | None:
        """Reject an unknown method on WRITE, unlike the runtime parser which widens
        it to ``any``. Asymmetric on purpose: a typo the admin can still fix must be
        an error, while a bad stored blob must never lock a tournament out.
        """
        if value is None:
            return value
        if value not in VERIFICATION_METHODS:
            raise ValueError(f"verification_method must be one of {sorted(VERIFICATION_METHODS)}")
        return value


class RoleTierRead(BaseModel):
    role_id: str
    tier_rank: int
    tier_label: str = ""


class ChallengeCodeRead(BaseModel):
    """Redacted: never carries the code or its digest.

    A digest is still brute-forcible offline, so the UI only learns that a code
    exists, at what tier, and until when.
    """

    tier_rank: int
    tier_label: str = ""
    expires_at: datetime | None = None


class SubscriptionProviderConfigRead(BaseModel):
    provider: str
    enabled: bool = False
    role_tiers: list[RoleTierRead] = Field(default_factory=list)
    broadcaster_id: str | None = None
    broadcaster_login: str | None = None
    codes: list[ChallengeCodeRead] = Field(default_factory=list)
    verification_method: str = VerificationMethod.ANY


class SubscriptionProviderConfigListResponse(BaseModel):
    configs: list[SubscriptionProviderConfigRead] = Field(default_factory=list)
    # One field for the whole response, not one per provider: the guild belongs to
    # the workspace. The admin card renders it read-only and warns when it is unset.
    discord_guild_id: str | None = None


class WorkspaceSubscriptionRequirementRead(BaseModel):
    """The rule a whole workspace enforces, shared by every tournament in it.

    ``requirement`` is the raw ``{mode, requirements: [{provider, min_tier_rank}]}``
    blob rather than a nested model on purpose: ``parse_requirement`` is the single
    authority on that shape (it clamps thresholds and keeps the strictest duplicate),
    and a second Pydantic definition of it would be a second source of truth for the
    admission rule.
    """

    requirement: dict[str, Any] = Field(default_factory=dict)
    #: How many live tournaments this rule would gate. One workspace rule now governs
    #: every tournament in the workspace, so clearing or tightening it is not a local
    #: edit -- the admin surface names the blast radius rather than leaving the organizer
    #: to guess it. Counts open, unfinished tournaments whose form has the subscription
    #: toggle on: the collector's TOURNAMENT-side predicate only. It deliberately omits
    #: the collector's inner join on the workspace rule row and its drop of empty blobs,
    #: so it reports what a rule WOULD gate rather than only what one currently does --
    #: otherwise it would read 0 for "toggles on, no rule saved yet", the very state the
    #: card exists to warn about.
    enforcing_tournaments: int = 0


class WorkspaceSubscriptionRequirementUpsert(BaseModel):
    """Replaces the rule wholesale -- a partial merge of an admission rule would be
    a silent policy change, and an empty ``requirements`` list is the way to clear it.
    """

    requirement: dict[str, Any] = Field(default_factory=dict)

    @field_validator("requirement")
    @classmethod
    def _validate_requirement(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Reject a malformed requirement on SAVE, not at check-in.

        Moved here verbatim from ``RegistrationFormUpsert`` when the rule moved to the
        workspace: ``parse_requirement`` raises on an unknown ``mode`` (silently picking
        one would change the admission rule) and drops rows with no provider -- which
        would leave the organizer believing they configured a gate that does nothing, so
        an all-dropped payload is rejected too. Better a 422 on save than a surprise at
        check-in, and the read path deliberately stays fail-open for anything that got
        past here.
        """
        if not value:
            return {}
        requirement = parse_requirement(value)
        if (value.get("requirements") or []) and not requirement.requirements:
            raise ValueError("subscription requirement rows must each name a provider")
        return value


class RegistrationListRead(RegistrationRead):
    # Capped to the most recent ``HISTORY_LIMIT`` entries; ``tournament_history_count``
    # holds the true total so the UI can render an accurate count badge.
    tournament_history: list[TournamentHistoryEntry] = Field(default_factory=list)
    tournament_history_count: int = 0


class RegistrationListResponse(BaseModel):
    """Envelope for the public registration list.

    Division grid versions are deduplicated into ``division_grids`` (keyed by version
    id) so each history entry only carries a ``division_grid_version_id`` reference,
    keeping the payload small even when participants have long tournament histories.
    """

    registrations: list[RegistrationListRead] = Field(default_factory=list)
    # Keyed by stringified version id to match the JSON wire format (object keys are
    # always strings); ``TournamentHistoryEntry.division_grid_version_id`` references these.
    division_grids: dict[str, DivisionGridVersionRead] = Field(default_factory=dict)


class RegistrationStatusResponse(BaseModel):
    status: str
    message: str
