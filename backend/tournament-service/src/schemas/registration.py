"""Pydantic schemas for tournament registration."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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


class SubroleOption(BaseModel):
    slug: str
    label: str


class RegistrationFormRead(BaseModel):
    id: int
    tournament_id: int
    workspace_id: int
    is_open: bool
    auto_approve: bool = False
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    require_open_profile: bool = False
    open_profile_scope: str = "main"
    show_ranks: bool = False
    built_in_fields: dict[str, BuiltInFieldConfig] = Field(default_factory=dict)
    custom_fields: list[CustomFieldDefinition] = Field(default_factory=list)
    # Workspace sub-role catalog keyed by registration role code (tank/dps/support).
    # The single source of truth for available sub-roles; per-tournament
    # built_in_fields[*].subroles selects which of these are offered.
    subrole_catalog: dict[str, list[SubroleOption]] = Field(default_factory=dict)


class RegistrationFormUpsert(BaseModel):
    is_open: bool = False
    auto_approve: bool = False
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    require_open_profile: bool = False
    open_profile_scope: str = "main"
    show_ranks: bool = False
    built_in_fields: dict[str, BuiltInFieldConfig] = Field(default_factory=dict)
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
    roles: list[RoleWithSubrole] | None = None
    stream_pov: bool = False
    notes: str | None = None
    custom_fields: dict[str, Any] | None = None


class RegistrationUpdate(BaseModel):
    battle_tag: str | None = None
    discord_nick: str | None = None
    twitch_nick: str | None = None
    primary_role: str | None = None
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


class RegistrationRead(BaseModel):
    id: int
    tournament_id: int
    workspace_id: int
    auth_user_id: int | None = None
    user_id: int | None = None
    battle_tag: str | None = None
    smurf_tags_json: list[str] | None = None
    discord_nick: str | None = None
    twitch_nick: str | None = None
    stream_pov: bool = False
    roles: list[RegistrationRoleRead] = Field(default_factory=list)
    notes: str | None = None
    custom_fields_json: dict[str, Any] | None = None
    status: str = "pending"
    status_meta: dict[str, Any] | None = None
    checked_in: bool = False
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


class RegistrationListRead(RegistrationRead):
    balancer_status: str = "not_in_balancer"
    balancer_status_meta: dict[str, Any] | None = None
    checked_in: bool = False
    # All-profiles-open verdict (only computed when the tournament requires it):
    # True = public, False = closed, None = unknown / not required.
    profiles_open: bool | None = None
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
