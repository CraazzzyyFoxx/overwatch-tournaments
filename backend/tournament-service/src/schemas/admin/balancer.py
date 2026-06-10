from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.schemas.base import BaseRead

BalancerRole = Literal["tank", "dps", "support"]
BalancerRoleSubtype = str
RegistrationStatus = str
BalancerStatus = str
StatusScope = Literal["registration", "balancer"]
StatusKind = Literal["builtin", "custom"]
RegistrationSource = Literal["manual", "google_sheets"]
RankAutofillPlayerStatus = Literal["will_update", "applied", "skipped", "unchanged"]
RankAutofillRoleAction = Literal[
    "set",
    "overwrite",
    "keep_existing",
    "missing_rank",
    "blocked",
]
RankAutofillSource = Literal["analytics", "balancer"]
RankAutofillUsedSource = Literal["division_history", "ow_peak", "ow_current"]

__all__ = (
    "RegistrationUserExportResponse",
    "BalanceExportResponse",
    "BalanceRead",
    "BalanceSaveRequest",
    "BalancerTournamentConfigRead",
    "BalancerTournamentConfigUpsert",
    "BalancerGoogleSheetFeedRead",
    "BalancerGoogleSheetFeedSyncResponse",
    "BalancerGoogleSheetFeedUpsert",
    "BalancerGoogleSheetMappingCatalogResponse",
    "BalancerGoogleSheetMappingPreviewRequest",
    "BalancerGoogleSheetMappingPreviewResponse",
    "BalancerGoogleSheetMappingSuggestRequest",
    "BalancerGoogleSheetMappingSuggestResponse",
    "MappingParserRead",
    "MappingPreviewFieldError",
    "MappingPreviewRow",
    "MappingTargetRead",
    "MappingValidationError",
    "MappingValueCategoryRead",
    "BalancerPlayerExportResponse",
    "BalancerRegistrationCreateRequest",
    "BalancerRegistrationExclusionRequest",
    "BalancerRegistrationRead",
    "BalancerRegistrationRankAutofillRequest",
    "BalancerRegistrationRankAutofillResponse",
    "BalancerRegistrationRankAutofillPlayer",
    "BalancerRegistrationRankAutofillRole",
    "BalancerRegistrationRoleInput",
    "BalancerRegistrationRoleRead",
    "BalancerRegistrationStatusCreate",
    "BalancerRegistrationStatusRead",
    "BalancerRegistrationStatusUpdate",
    "StatusMetaRead",
    "BalancerRegistrationUpdateRequest",
    "BulkApproveResponse",
    "BulkBalancerStatusResponse",
    "CheckInRequest",
    "SetBalancerStatusRequest",
)


class BalancerPlayerExportResponse(BaseModel):
    format: str
    players: dict[str, Any]


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


class MappingPreviewFieldError(BaseModel):
    target: str
    column: str | None = None
    message: str
    row_index: int | None = None


class MappingValidationError(BaseModel):
    code: str
    message: str
    target: str | None = None
    column: str | None = None


class BalancerGoogleSheetFeedSyncResponse(BaseModel):
    created: int
    updated: int
    withdrawn: int
    total: int
    skipped: int = 0
    errors: list[MappingPreviewFieldError] = Field(default_factory=list)
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
    sample_rows: int = 5


class MappingPreviewRow(BaseModel):
    row_index: int
    sample_raw_row: dict[str, str] = Field(default_factory=dict)
    parsed_fields: dict[str, Any] = Field(default_factory=dict)
    errors: list[MappingPreviewFieldError] = Field(default_factory=list)
    warnings: list[MappingPreviewFieldError] = Field(default_factory=list)
    disposition: Literal["create", "update", "skip"]


class BalancerGoogleSheetMappingPreviewResponse(BaseModel):
    headers: list[str] = Field(default_factory=list)
    header_keys: list[str] = Field(default_factory=list)
    rows: list[MappingPreviewRow] = Field(default_factory=list)
    create_count: int = 0
    update_count: int = 0
    skip_count: int = 0
    # Back-compat single-row fields (populated from the first preview row).
    sample_raw_row: dict[str, str] = Field(default_factory=dict)
    parsed_fields: dict[str, Any] = Field(default_factory=dict)


class MappingTargetRead(BaseModel):
    key: str
    label: str
    group: str
    accepted_parsers: list[str] = Field(default_factory=list)
    default_parser: str
    default_mode: str = "disabled"
    default_is_list: bool = False
    multi_column: bool = False
    required: bool = False


class MappingParserRead(BaseModel):
    parser: str
    label: str
    cardinality: Literal["single", "multi"]
    produces: str


class MappingValueCategoryRead(BaseModel):
    category: Literal["booleans", "roles", "subroles", "role_subroles", "divisions"]
    entries: dict[str, Any] = Field(default_factory=dict)


class BalancerGoogleSheetMappingCatalogResponse(BaseModel):
    targets: list[MappingTargetRead] = Field(default_factory=list)
    parsers: list[MappingParserRead] = Field(default_factory=list)
    value_categories: list[MappingValueCategoryRead] = Field(default_factory=list)
    custom_fields: list[dict[str, Any]] = Field(default_factory=list)
    header_keys: list[str] = Field(default_factory=list)


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
    top_heroes: list[str] | None = None


class BalancerRegistrationRankAutofillRequest(BaseModel):
    registration_ids: list[int] | None = None
    overwrite_existing: bool = False
    add_to_balancer: bool = False


class BalancerRegistrationRankAutofillRole(BaseModel):
    role: BalancerRole
    current_rank_value: int | None = None
    parsed_rank_value: int | None = None
    action: RankAutofillRoleAction
    reason: str | None = None
    platform: str | None = None
    division: str | None = None
    tier: int | None = None
    season: int | None = None
    captured_at: datetime | None = None
    source: RankAutofillSource = "analytics"
    division_history_rank_value: int | None = None
    ow_peak_rank_value: int | None = None
    ow_current_rank_value: int | None = None
    ow_peak_season: int | None = None
    used_source: RankAutofillUsedSource | None = None


class BalancerRegistrationRankAutofillPlayer(BaseModel):
    registration_id: int
    display_name: str | None = None
    battle_tag: str | None = None
    status: RankAutofillPlayerStatus
    reason: str | None = None
    will_add_to_balancer: bool = False
    balancer_reason: str | None = None
    roles: list[BalancerRegistrationRankAutofillRole] = Field(default_factory=list)


class BalancerRegistrationRankAutofillResponse(BaseModel):
    total_registrations: int
    updatable_registrations: int
    applied_registrations: int
    skipped_registrations: int
    unchanged_registrations: int
    role_updates: int
    overwrite_existing: bool
    add_to_balancer: bool
    balancer_additions: int
    players: list[BalancerRegistrationRankAutofillPlayer] = Field(default_factory=list)


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


class BalanceExportResponse(BaseModel):
    success: bool
    removed_teams: int
    imported_teams: int
    balance_id: int


class RegistrationUserExportResponse(BaseModel):
    processed: int
    skipped: int
    total: int
