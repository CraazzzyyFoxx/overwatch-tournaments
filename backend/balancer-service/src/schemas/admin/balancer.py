from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.schemas.base import BaseRead

BalancerRole = Literal["tank", "dps", "support"]
BalancerRoleSubtype = str
DuplicateResolution = Literal["replace", "skip"]
DuplicateStrategy = Literal["manual", "replace_all", "skip_all"]
RegistrationStatus = str
BalancerStatus = str
StatusScope = Literal["registration", "balancer"]
StatusKind = Literal["builtin", "custom"]
RegistrationSource = Literal["manual", "google_sheets"]

__all__ = (
    "ApplicationUserExportResponse",
    "RegistrationUserExportResponse",
    "BalanceExportResponse",
    "BalanceRead",
    "BalanceSaveRequest",
    "BalancerTournamentConfigRead",
    "BalancerTournamentConfigUpsert",
    "BalancerApplicationRead",
    "BalancerGoogleSheetFeedRead",
    "BalancerGoogleSheetFeedSyncResponse",
    "BalancerGoogleSheetFeedUpsert",
    "BalancerGoogleSheetMappingPreviewRequest",
    "BalancerGoogleSheetMappingPreviewResponse",
    "BalancerGoogleSheetMappingSuggestRequest",
    "BalancerGoogleSheetMappingSuggestResponse",
    "BalancerPlayerCreateRequest",
    "BalancerPlayerExportResponse",
    "BalancerPlayerImportDuplicate",
    "BalancerPlayerImportPreviewResponse",
    "BalancerPlayerImportResult",
    "BalancerPlayerImportSkipped",
    "BalancerPlayerRead",
    "BalancerPlayerRoleEntry",
    "BalancerPlayerRoleSyncResponse",
    "BalancerPlayerUpdate",
    "BalancerRegistrationCreateRequest",
    "BalancerRegistrationExclusionRequest",
    "BalancerRegistrationRead",
    "BalancerRegistrationRoleInput",
    "BalancerRegistrationRoleRead",
    "BalancerRegistrationStatusCreate",
    "BalancerRegistrationStatusRead",
    "BalancerRegistrationStatusUpdate",
    "StatusMetaRead",
    "BalancerRegistrationUpdateRequest",
    "BalancerTeamRead",
    "BalancerTournamentSheetRead",
    "BalancerTournamentSheetUpsert",
    "BulkApproveResponse",
    "BulkBalancerStatusResponse",
    "CheckInRequest",
    "SetBalancerStatusRequest",
    "SheetSyncResponse",
)


class BalancerTournamentSheetUpsert(BaseModel):
    source_url: str
    title: str | None = None
    column_mapping_json: dict[str, Any] | None = None
    role_mapping_json: dict[str, str | None] | None = None


class BalancerPlayerRoleEntry(BaseModel):
    role: BalancerRole
    subtype: BalancerRoleSubtype | None = None
    priority: int
    division_number: int | None = None
    rank_value: int | None = None
    is_active: bool = True


class BalancerPlayerRead(BaseRead):
    tournament_id: int
    application_id: int
    battle_tag: str
    battle_tag_normalized: str
    user_id: int | None
    role_entries_json: list[BalancerPlayerRoleEntry] = Field(default_factory=list)
    is_flex: bool
    is_in_pool: bool
    admin_notes: str | None


class BalancerApplicationRead(BaseRead):
    tournament_id: int
    tournament_sheet_id: int
    battle_tag: str
    battle_tag_normalized: str
    smurf_tags_json: list[str] = Field(default_factory=list)
    twitch_nick: str | None
    discord_nick: str | None
    stream_pov: bool
    last_tournament_text: str | None
    primary_role: str | None
    additional_roles_json: list[str] = Field(default_factory=list)
    notes: str | None
    submitted_at: datetime | None
    synced_at: datetime
    is_active: bool
    player: BalancerPlayerRead | None = None


class BalancerTournamentSheetRead(BaseRead):
    tournament_id: int
    source_url: str
    sheet_id: str
    gid: str | None
    title: str | None
    header_row_json: list[str] | None = None
    column_mapping_json: dict[str, Any] | None = None
    role_mapping_json: dict[str, str | None] | None = None
    is_active: bool
    last_synced_at: datetime | None
    last_sync_status: str | None
    last_error: str | None


class SheetSyncResponse(BaseModel):
    created: int
    updated: int
    deactivated: int
    total: int
    sheet: BalancerTournamentSheetRead


class BalancerPlayerCreateRequest(BaseModel):
    application_ids: list[int]


class BalancerPlayerUpdate(BaseModel):
    role_entries_json: list[BalancerPlayerRoleEntry] | None = None
    is_flex: bool | None = None
    is_in_pool: bool | None = None
    admin_notes: str | None = None


class BalancerPlayerImportDuplicate(BaseModel):
    battle_tag: str
    battle_tag_normalized: str
    application_id: int
    existing_player_id: int
    imported_role_entries_json: list[BalancerPlayerRoleEntry] = Field(default_factory=list)
    existing_role_entries_json: list[BalancerPlayerRoleEntry] = Field(default_factory=list)
    imported_is_in_pool: bool = True
    existing_is_in_pool: bool = True
    imported_admin_notes: str | None = None
    existing_admin_notes: str | None = None


class BalancerPlayerImportSkipped(BaseModel):
    battle_tag: str
    battle_tag_normalized: str
    reason: Literal["missing_active_application", "duplicate_in_file", "no_ranked_roles"]


class BalancerPlayerImportPreviewResponse(BaseModel):
    total_players: int
    creatable_players: int
    duplicate_players: int
    skipped_players: int
    duplicates: list[BalancerPlayerImportDuplicate] = Field(default_factory=list)
    skipped: list[BalancerPlayerImportSkipped] = Field(default_factory=list)


class BalancerPlayerImportResult(BaseModel):
    success: bool
    created: int
    replaced: int
    skipped_duplicates: int
    skipped_missing_application: int
    skipped_duplicate_in_file: int
    skipped_no_ranked_roles: int
    total_players: int


class BalancerPlayerExportResponse(BaseModel):
    format: str
    players: dict[str, Any]


class BalancerPlayerRoleSyncResponse(BaseModel):
    updated: int
    skipped: int


class BalancerGoogleSheetFeedUpsert(BaseModel):
    source_url: str
    title: str | None = None
    auto_sync_enabled: bool = False
    auto_sync_interval_seconds: int = 300
    mapping_config_json: dict[str, Any] | None = None
    value_mapping_json: dict[str, Any] | None = None


class BalancerGoogleSheetFeedRead(BaseRead):
    tournament_id: int
    source_url: str
    sheet_id: str
    gid: str | None
    title: str | None
    header_row_json: list[str] | None = None
    mapping_config_json: dict[str, Any] | None = None
    value_mapping_json: dict[str, Any] | None = None
    auto_sync_enabled: bool
    auto_sync_interval_seconds: int
    last_synced_at: datetime | None
    last_sync_status: str | None
    last_error: str | None


class BalancerGoogleSheetFeedSyncResponse(BaseModel):
    created: int
    updated: int
    withdrawn: int
    total: int
    feed: BalancerGoogleSheetFeedRead


class BalancerGoogleSheetMappingSuggestRequest(BaseModel):
    source_url: str | None = None


class BalancerGoogleSheetMappingSuggestResponse(BaseModel):
    headers: list[str] = Field(default_factory=list)
    mapping_config_json: dict[str, Any] = Field(default_factory=dict)


class BalancerGoogleSheetMappingPreviewRequest(BaseModel):
    source_url: str | None = None
    mapping_config_json: dict[str, Any] | None = None
    value_mapping_json: dict[str, Any] | None = None


class BalancerGoogleSheetMappingPreviewResponse(BaseModel):
    headers: list[str] = Field(default_factory=list)
    sample_raw_row: dict[str, str] = Field(default_factory=dict)
    parsed_fields: dict[str, Any] = Field(default_factory=dict)


class BalancerRegistrationRoleRead(BaseModel):
    role: BalancerRole
    subrole: BalancerRoleSubtype | None = None
    priority: int = 0
    is_primary: bool = False
    rank_value: int | None = None
    is_active: bool = True
    top_heroes: list[str] = Field(default_factory=list)  # ordered hero slugs (read-only display)


class BalancerRegistrationRoleInput(BaseModel):
    role: BalancerRole
    subrole: BalancerRoleSubtype | None = None
    priority: int = 0
    is_primary: bool = False
    rank_value: int | None = None
    is_active: bool = True


class StatusMetaRead(BaseModel):
    value: str
    scope: StatusScope
    is_builtin: bool
    kind: StatusKind = "custom"
    is_override: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_reset: bool = False
    icon_slug: str | None = None
    icon_color: str | None = None
    name: str
    description: str | None = None


class BalancerRegistrationStatusRead(BaseRead):
    workspace_id: int | None = None
    scope: StatusScope
    slug: str
    kind: StatusKind = "custom"
    is_override: bool = False
    can_delete: bool = False
    can_reset: bool = False
    icon_slug: str | None = None
    icon_color: str | None = None
    name: str
    description: str | None = None


class BalancerRegistrationStatusCreate(BaseModel):
    scope: StatusScope
    icon_slug: str | None = None
    icon_color: str | None = None
    name: str
    description: str | None = None


class BalancerRegistrationStatusUpdate(BaseModel):
    icon_slug: str | None = None
    icon_color: str | None = None
    name: str | None = None
    description: str | None = None


class BalancerRegistrationRead(BaseRead):
    tournament_id: int
    workspace_id: int
    auth_user_id: int | None = None
    user_id: int | None = None
    display_name: str | None = None
    battle_tag: str | None = None
    battle_tag_normalized: str | None = None
    source: RegistrationSource
    source_record_key: str | None = None
    smurf_tags_json: list[str] = Field(default_factory=list)
    discord_nick: str | None = None
    twitch_nick: str | None = None
    stream_pov: bool = False
    notes: str | None = None
    admin_notes: str | None = None
    custom_fields_json: dict[str, Any] | None = None
    is_flex: bool = False
    status: RegistrationStatus
    balancer_status: BalancerStatus = "not_in_balancer"
    status_meta: StatusMetaRead
    balancer_status_meta: StatusMetaRead
    exclude_from_balancer: bool = False
    exclude_reason: str | None = None
    checked_in: bool = False
    checked_in_at: datetime | None = None
    checked_in_by_username: str | None = None
    deleted_at: datetime | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by_username: str | None = None
    balancer_profile_overridden_at: datetime | None = None
    roles: list[BalancerRegistrationRoleRead] = Field(default_factory=list)


class BalancerRegistrationCreateRequest(BaseModel):
    display_name: str | None = None
    battle_tag: str | None = None
    smurf_tags_json: list[str] | None = None
    discord_nick: str | None = None
    twitch_nick: str | None = None
    stream_pov: bool = False
    notes: str | None = None
    admin_notes: str | None = None
    is_flex: bool = False
    roles: list[BalancerRegistrationRoleInput] = Field(default_factory=list)


class BalancerRegistrationUpdateRequest(BaseModel):
    display_name: str | None = None
    battle_tag: str | None = None
    smurf_tags_json: list[str] | None = None
    discord_nick: str | None = None
    twitch_nick: str | None = None
    stream_pov: bool | None = None
    notes: str | None = None
    admin_notes: str | None = None
    is_flex: bool | None = None
    status: RegistrationStatus | None = None
    balancer_status: BalancerStatus | None = None
    roles: list[BalancerRegistrationRoleInput] | None = None


class BalancerRegistrationExclusionRequest(BaseModel):
    exclude_from_balancer: bool
    exclude_reason: str | None = None


class SetBalancerStatusRequest(BaseModel):
    balancer_status: BalancerStatus


class CheckInRequest(BaseModel):
    checked_in: bool


class BulkBalancerStatusResponse(BaseModel):
    updated: int
    skipped: int


class BulkApproveResponse(BaseModel):
    approved: int
    skipped: int


class BalancerTeamRead(BaseRead):
    balance_id: int
    exported_team_id: int | None = None
    name: str
    balancer_name: str
    captain_battle_tag: str | None
    avg_sr: float
    total_sr: int
    roster_json: dict[str, Any]
    sort_order: int


class BalanceSaveRequest(BaseModel):
    config_json: dict[str, Any] | None = None
    result_json: dict[str, Any]


class BalancerTournamentConfigUpsert(BaseModel):
    config_json: dict[str, Any] | None = None


class BalancerTournamentConfigRead(BaseRead):
    tournament_id: int
    workspace_id: int
    config_json: dict[str, Any]
    updated_by: int | None = None
    updated_at: datetime | None = None


class BalanceRead(BaseRead):
    tournament_id: int
    config_json: dict[str, Any] | None = None
    result_json: dict[str, Any]
    saved_by: int | None
    saved_at: datetime
    exported_at: datetime | None = None
    export_status: str | None = None
    export_error: str | None = None
    teams: list[BalancerTeamRead] = Field(default_factory=list)


class BalanceExportResponse(BaseModel):
    success: bool
    removed_teams: int
    imported_teams: int
    balance_id: int


class ApplicationUserExportResponse(BaseModel):
    processed: int
    skipped: int
    total: int


class RegistrationUserExportResponse(BaseModel):
    processed: int
    skipped: int
    total: int
