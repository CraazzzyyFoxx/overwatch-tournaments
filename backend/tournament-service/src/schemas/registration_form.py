"""Wire models for the registration form: its toggles, its schema, its templates.

The registration ANSWER models live in ``schemas/registration.py``; what a
tournament ASKS lives here, as one versioned :class:`FormSchema`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from shared.domain.forms import FormSchema
from src.schemas.registration import SubroleOption


class RegistrationFormRead(BaseModel):
    id: int
    tournament_id: int
    workspace_id: int
    #: The tournament's discipline: the owner scope of the form's roles, characters and identity
    #: provider. Carried here so every form consumer (wizard, invite, edit dialog) scopes its
    #: metadata reads from the loaded owner DTO instead of a second tournament read.
    discipline: str
    require_open_profile: bool = False
    open_profile_scope: str = "main"
    show_ranks: bool = False
    #: Collapses the public participants list to an aggregate. See
    #: ``RegistrationForm.hide_registrations`` -- enforced in the read model.
    hide_registrations: bool = False
    # Server-resolved from the WORKSPACE's requirement and READ-ONLY: the rule is
    # workspace-scoped (see WorkspaceSubscriptionRequirementUpsert) and has no
    # column on the form mapper. The caller passes the resolved blob in.
    subscription_requirement_json: dict[str, Any] = Field(default_factory=dict)
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
    # No `subscription_requirement_json` (workspace-scoped) and no intake settings (the registration node's config).
    # A client that sends either is TOLERATED, not rejected -- Pydantic's default `extra="ignore"` drops the key and
    # the rest of the save succeeds.
    require_open_profile: bool = False
    open_profile_scope: str = "main"
    show_ranks: bool = False
    hide_registrations: bool = False
    #: The whole question set, full-replace. A save whose canonical JSON differs
    #: from the current version appends a new version; an identical one does not.
    form_schema: FormSchema


class RegistrationFormTemplateRead(BaseModel):
    id: int
    workspace_id: int
    #: The game the template belongs to: its identity question is that game's.
    discipline: str
    name: str
    form_schema: FormSchema
    updated_at: datetime


class RegistrationFormTemplateUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    #: Required on create (a game the workspace runs). On update omitted or equal; another game is a 409.
    discipline: str | None = None
    form_schema: FormSchema


class RegistrationFormTemplateApply(BaseModel):
    """Which workspace template to copy onto the tournament in the path."""

    template_id: int


class RegistrationFormTemplateSave(BaseModel):
    """The name to file the tournament's current questions under."""

    name: str = Field(min_length=1, max_length=64)
