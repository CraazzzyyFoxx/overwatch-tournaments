"""Wire models for the registration form: its toggles, its schema, its templates.

Split out of ``schemas/registration.py`` when ``built_in_fields_json`` /
``custom_fields_json`` collapsed into one versioned :class:`FormSchema`. The
registration ANSWER models stay in ``schemas/registration.py``; what a
tournament ASKS lives here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from shared.core.enums import SubscriptionEnforcementStage
from shared.domain.forms import FormSchema
from src.schemas.registration import SubroleOption


class RegistrationFormRead(BaseModel):
    id: int
    tournament_id: int
    workspace_id: int
    # DERIVED, read-only: "is registration open right now", computed from the
    # tournament's REGISTRATION phase-schedule window. No longer a column on the
    # form -- see shared.services.registration_window.
    is_open: bool
    auto_approve: bool = False
    require_open_profile: bool = False
    open_profile_scope: str = "main"
    show_ranks: bool = False
    #: Collapses the public participants list to an aggregate. See
    #: ``BalancerRegistrationForm.hide_registrations`` -- enforced in the read model.
    hide_registrations: bool = False
    #: Advisory capacity, never enforced. ``None`` means "not announced".
    max_participants: int | None = Field(default=None, ge=0)
    require_subscription: bool = False
    # WHEN the requirement bites, once the toggle above is on. See
    # ``enums.SubscriptionEnforcementStage``: ``registration`` implies check-in too.
    subscription_stage: SubscriptionEnforcementStage = SubscriptionEnforcementStage.check_in
    # Server-resolved from the WORKSPACE's requirement and READ-ONLY: the rule is no
    # longer a property of the form (see WorkspaceSubscriptionRequirementUpsert), and
    # there is no such column on the mapper. The caller passes the resolved blob in.
    subscription_requirement_json: dict[str, Any] = Field(default_factory=dict)
    #: Bench size for team registration. Zero disables substitutes. Not a starter
    #: slot -- see ``BalancerRegistrationForm.max_substitutes``.
    max_substitutes: int = Field(default=0, ge=0)
    #: ``player`` (default) keeps the per-entrant subscription gate. ``team`` is
    #: "the captain pays": a stamp on the registered team covers the roster.
    subscription_scope: Literal["player", "team"] = "player"
    team_rank_min: int | None = Field(default=None, ge=0)
    team_rank_max: int | None = Field(default=None, ge=0)
    team_max_rank_spread: int | None = Field(default=None, ge=0)
    team_unique_identity: bool = False
    team_require_discord_guild: bool = False
    #: The questions this form asks, as of ``version_id``.
    form_schema: FormSchema
    version_id: int
    version_number: int
    #: Live registrations answering an OLDER version. Organizer reads only: the
    #: public form read passes ``None`` rather than paying for the count.
    stale_registrations: int | None = None
    # Workspace sub-role catalog keyed by registration role code (tank/damage/support).
    # The single source of truth for available sub-roles; the ``roles`` builtin's
    # ``subroles`` params select which of these are offered.
    subrole_catalog: dict[str, list[SubroleOption]] = Field(default_factory=dict)


class RegistrationFormUpsert(BaseModel):
    # No `subscription_requirement_json`: the rule is workspace-scoped now. No
    # `is_open` either: registration openness is the tournament's REGISTRATION
    # schedule window, so the form has no say. A stale client that still sends
    # either one is TOLERATED, not rejected -- Pydantic's default `extra="ignore"`
    # drops the key and the rest of the save succeeds.
    auto_approve: bool = False
    require_open_profile: bool = False
    open_profile_scope: str = "main"
    show_ranks: bool = False
    hide_registrations: bool = False
    #: Informational only -- deliberately no cross-check against the live count.
    max_participants: int | None = Field(default=None, ge=0)
    require_subscription: bool = False
    # Defaults to the looser stage, so a client that does not know the field yet
    # cannot silently turn a check-in requirement into a sign-up wall.
    subscription_stage: SubscriptionEnforcementStage = SubscriptionEnforcementStage.check_in
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
    #: The whole question set, full-replace. A save whose canonical JSON differs
    #: from the current version appends a new version; an identical one does not.
    form_schema: FormSchema


class RegistrationFormTemplateRead(BaseModel):
    id: int
    workspace_id: int
    name: str
    form_schema: FormSchema
    updated_at: datetime


class RegistrationFormTemplateUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    form_schema: FormSchema


class RegistrationFormTemplateApply(BaseModel):
    """Which workspace template to copy onto the tournament in the path."""

    template_id: int


class RegistrationFormTemplateSave(BaseModel):
    """The name to file the tournament's current questions under."""

    name: str = Field(min_length=1, max_length=64)
