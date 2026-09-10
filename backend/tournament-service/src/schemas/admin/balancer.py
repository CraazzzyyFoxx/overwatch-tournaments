from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from shared.domain.roster_shape import RegistrationRoleCode
from src.schemas.admission import AdmissionRead
from src.schemas.base import BaseRead
from src.schemas.registration import SubroleOption

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
    "unverified",
    "missing_rank",
    "blocked",
]
RankAutofillSource = Literal["analytics", "balancer"]
RankAutofillUsedSource = Literal["division_history", "ow", "analytics"]
# Individual source of a rank-autofill stage chain.
RankAutofillSourceKey = Literal["ow", "division_history", "analytics"]
# Priority chains for rank autofill:
#   ow_first       -> OW (week composite) -> balancer (division history) -> analytics (past tournaments)
#   balancer_first -> balancer -> analytics -> OW
# Legacy presets; superseded by an explicit ``stages`` chain when one is supplied.
RankAutofillMode = Literal["ow_first", "balancer_first"]

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
    "BalancerPlayerExportRoster",
    "BalancerPlayerExportSource",
    "BalancerRegistrationCreateRequest",
    "BalancerRegistrationRead",
    "BalancerRankAutofillStage",
    "BalancerRegistrationRankAutofillRequest",
    "BalancerRegistrationRankAutofillResponse",
    "BalancerRegistrationRankAutofillPlayer",
    "BalancerRegistrationRankAutofillRole",
    "BalancerRegistrationRankHistoryEntry",
    "BalancerRegistrationRankHistoryResponse",
    "BalancerRegistrationRoleInput",
    "BalancerRegistrationRoleRead",
    "BalancerRegistrationStatusCreate",
    "BalancerRegistrationStatusRead",
    "BalancerRegistrationStatusUpdate",
    "StatusMetaRead",
    "BalancerRegistrationUpdateRequest",
    "BulkApproveResponse",
    "BulkBalancerStatusResponse",
    "BulkSetBalancerStatusRequest",
    "CheckInRequest",
    "SetBalancerStatusRequest",
)


class BalancerPlayerExportSource(BaseModel):
    """Where an ``owt-1`` export came from -- enough to replay or re-import it."""

    tournament_id: int
    tournament_name: str | None = None
    workspace_id: int | None = None
    #: Which roster field the ``players`` keys carry (``registration_id``).
    player_key: str
    #: Which registrations the file covers; ``pool`` is the balancer pool.
    scope: str
    division_grid_version_id: int | None = None


class BalancerPlayerExportRoster(BaseModel):
    """The team shape the export was taken under, flex slot included."""

    slots: dict[str, int]
    team_size: int
    flex_slots: int
    #: ``optional`` | ``all_roles`` | ``forced``.
    flex_role_mode: str


class BalancerPlayerExportResponse(BaseModel):
    """Both player-pool export formats.

    ``xv-1`` is the solver's input contract and carries ``format``/``players``
    only. ``owt-1`` is our full snapshot: the same player nodes plus an ``owt``
    block on each, and the three context fields below. See
    ``shared.services.roster.RosterEngine.full_export``.
    """

    format: str
    players: dict[str, Any]
    generated_at: str | None = None
    source: BalancerPlayerExportSource | None = None
    roster: BalancerPlayerExportRoster | None = None


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
    subrole_catalog: dict[str, list[SubroleOption]] = Field(default_factory=dict)


class BalancerRegistrationRoleRead(BaseModel):
    role: RegistrationRoleCode
    subrole: BalancerRoleSubtype | None = None
    priority: int = 0
    is_primary: bool = False
    rank_value: int | None = None
    rank_source: Literal["registration", "workspace", "ow", "none"] = "none"
    #: Playability, not the checkbox: the role is active AND the rank resolver
    #: found a number for it. This is exactly what the balancer and the draft
    #: act on -- the one predicate, reported once.
    is_active: bool = True
    #: The raw ``registration_role.is_active`` column: what the registrant (or
    #: the sheet, or the editor) declared. The role editor toggles THIS.
    is_declared_active: bool = True
    top_heroes: list[str] = Field(default_factory=list)  # ordered hero slugs (read-only display)
    # Latest OW2 rank for this role, normalised to the workspace grid. Injected from
    # UserRankSnapshot at list time; None when no snapshot maps to a grid tier.
    ow_rank_value: int | None = None


class BalancerRegistrationRoleInput(BaseModel):
    role: RegistrationRoleCode
    subrole: BalancerRoleSubtype | None = None
    priority: int = 0
    is_primary: bool = False
    rank_value: int | None = None
    is_active: bool = True
    top_heroes: list[str] | None = None


class BalancerRankAutofillStage(BaseModel):
    """A single source in the rank-autofill priority chain.

    ``lookback_tournaments`` limits ``division_history``/``analytics`` to the last N tournaments
    before the current one; ``lookback_days`` overrides the OW weekly window. The
    irrelevant lookback for a given ``source`` is ignored by the service.
    """

    source: RankAutofillSourceKey
    enabled: bool = True
    lookback_tournaments: int | None = Field(None, ge=1)
    lookback_days: int | None = Field(None, ge=1)


class BalancerRegistrationRankAutofillRequest(BaseModel):
    registration_ids: list[int] | None = Field(None, max_length=500)
    overwrite_existing: bool = False
    add_to_balancer: bool = False
    # Apply found role ranks even when other active roles have no parsed rank (otherwise the whole
    # registration is skipped). Never clears an existing rank — unfilled roles are left untouched.
    allow_partial: bool = False
    # Legacy preset; only used when ``stages`` is not supplied.
    mode: RankAutofillMode = "ow_first"
    # Explicit ordered priority chain. When non-empty it supersedes ``mode``; disabled stages are
    # dropped and duplicate sources are de-duplicated, preserving order.
    stages: list[BalancerRankAutofillStage] | None = None


class BalancerRegistrationRankAutofillRole(BaseModel):
    role: RegistrationRoleCode
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
    ow_rank_value: int | None = None
    ow_current_rank_value: int | None = None
    analytics_rank_value: int | None = None
    used_source: RankAutofillUsedSource | None = None


class BalancerRegistrationRankAutofillPlayer(BaseModel):
    registration_id: int
    display_name: str | None = None
    battle_tag: str | None = None
    status: RankAutofillPlayerStatus
    reason: str | None = None
    will_add_to_balancer: bool = False
    balancer_reason: str | None = None
    # True when some active roles were filled but others had no parsed rank (allow_partial).
    partial: bool = False
    roles: list[BalancerRegistrationRankAutofillRole] = Field(default_factory=list)


class BalancerRegistrationRankAutofillResponse(BaseModel):
    total_registrations: int
    updatable_registrations: int
    applied_registrations: int
    skipped_registrations: int
    unchanged_registrations: int
    # Registrations with >=1 active role that has a current rank no enabled source could corroborate.
    unverified_registrations: int
    role_updates: int
    overwrite_existing: bool
    add_to_balancer: bool
    balancer_additions: int
    players: list[BalancerRegistrationRankAutofillPlayer] = Field(default_factory=list)


class BalancerRegistrationRankHistoryEntry(BaseModel):
    tournament_id: int
    tournament_name: str | None = None
    role: RegistrationRoleCode
    rank_value: int


class BalancerRegistrationRankHistoryResponse(BaseModel):
    entries: list[BalancerRegistrationRankHistoryEntry] = Field(default_factory=list)


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
    # Whether a registration currently holding this status counts as part of
    # the balancer pool -- see shared.balancer_registration_statuses.StatusMeta.
    excludes_from_balancer: bool = False
    # Whether a registration currently holding this status is blocked from
    # counting as "ready", independent of excludes_from_balancer.
    excludes_from_ready: bool = False


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
    excludes_from_balancer: bool = False
    excludes_from_ready: bool = False


class BalancerRegistrationStatusCreate(BaseModel):
    scope: StatusScope
    icon_slug: str | None = None
    icon_color: str | None = None
    name: str
    description: str | None = None
    # Only meaningful for scope == "balancer": whether a registration holding
    # this custom status counts as part of the balancer pool.
    excludes_from_balancer: bool = False
    # Only meaningful for scope == "balancer": whether a registration holding
    # this custom status is blocked from counting as "ready".
    excludes_from_ready: bool = False


class BalancerRegistrationStatusUpdate(BaseModel):
    icon_slug: str | None = None
    icon_color: str | None = None
    name: str | None = None
    description: str | None = None
    excludes_from_balancer: bool | None = None
    excludes_from_ready: bool | None = None


class BalancerRegistrationRead(BaseRead):
    tournament_id: int
    workspace_id: int
    user_id: int | None = None
    display_name: str | None = None
    battle_tag: str | None = None
    battle_tag_normalized: str | None = None
    source: RegistrationSource
    source_record_key: str | None = None
    smurf_tags_json: list[str] = Field(default_factory=list)
    discord_nick: str | None = None
    twitch_nick: str | None = None
    boosty_nick: str | None = None
    stream_pov: bool = False
    notes: str | None = None
    admin_notes: str | None = None
    custom_fields_json: dict[str, Any] | None = None
    is_flex: bool = False
    status: RegistrationStatus
    balancer_status: BalancerStatus = "not_in_balancer"
    status_meta: StatusMetaRead
    balancer_status_meta: StatusMetaRead
    # Reason note for the current status, populated when balancer_status ==
    # "excluded". Whether the registration is *actually* excluded is read from
    # balancer_status_meta.excludes_from_balancer, not a separate flag.
    exclude_reason: str | None = None
    checked_in: bool = False
    checked_in_at: datetime | None = None
    checked_in_by_username: str | None = None
    deleted_at: datetime | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by_username: str | None = None
    balancer_profile_overridden_at: datetime | None = None
    # The single admission answer, computed server-side and byte-identical to the
    # one the public participants read carries for the same registration -- that
    # equality is the point, and there is a test pinning it.
    #
    # Resolved by the LIST read only. Single-registration mutation responses
    # carry ``AdmissionRead.unknown()`` rather than ``None``: the table
    # invalidates and refetches the list, so nothing renders it, and an absent
    # object would put a null branch in every consumer.
    admission: AdmissionRead = Field(default_factory=AdmissionRead.unknown)
    # Raw signals beside the decision, not duplicates of it: the per-row Profile
    # and Subscription chips render them directly. Lifted out of
    # ``admission.requirements[].detail`` by the list handler, never re-resolved.
    # True = public, False = closed, None = unknown / not required.
    profiles_open: bool | None = None
    # Composed subscription verdict ("satisfied"/"refused"/"undetermined");
    # only "refused" blocks admission, mirroring ``profiles_open is False``.
    subscription_outcome: str | None = None
    #: The player's strongest playable rank -- what a role-less slot is worth and
    #: what the pool sorts by. ``None`` when no role of theirs is playable at all.
    #: Server-side because it is the engine's own answer: the admin table used to
    #: re-derive it with a ``Math.max`` over the active roles' ranks.
    best_rank: int | None = None
    roles: list[BalancerRegistrationRoleRead] = Field(default_factory=list)


class BalancerRegistrationCreateRequest(BaseModel):
    display_name: str | None = None
    battle_tag: str | None = None
    smurf_tags_json: list[str] | None = None
    discord_nick: str | None = None
    twitch_nick: str | None = None
    boosty_nick: str | None = None
    stream_pov: bool = False
    notes: str | None = None
    admin_notes: str | None = None
    # Answers to the tournament's custom field definitions, keyed by definition
    # key — the same shape the public ``RegistrationCreate.custom_fields`` sends.
    custom_fields_json: dict[str, Any] | None = None
    # Review state chosen in the admin editor. ``None`` keeps the historical
    # "manual rows land approved" default.
    status: RegistrationStatus | None = None
    balancer_status: BalancerStatus | None = None
    roles: list[BalancerRegistrationRoleInput] = Field(default_factory=list)
    # Site account to anchor this manual registration on (its player/member).
    # None = unlinked (the historical behavior).
    auth_user_id: int | None = None


class BalancerRegistrationUpdateRequest(BaseModel):
    display_name: str | None = None
    battle_tag: str | None = None
    smurf_tags_json: list[str] | None = None
    discord_nick: str | None = None
    twitch_nick: str | None = None
    boosty_nick: str | None = None
    stream_pov: bool | None = None
    notes: str | None = None
    admin_notes: str | None = None
    custom_fields_json: dict[str, Any] | None = None
    status: RegistrationStatus | None = None
    balancer_status: BalancerStatus | None = None
    roles: list[BalancerRegistrationRoleInput] | None = None
    auth_user_id: int | None = None
    exclude_reason: str | None = None
    pin: bool | None = None
    clear_pin: bool = False


class SetBalancerStatusRequest(BaseModel):
    balancer_status: BalancerStatus
    # Only meaningful together with balancer_status == "excluded".
    exclude_reason: str | None = None


class CheckInRequest(BaseModel):
    checked_in: bool


class BulkBalancerStatusResponse(BaseModel):
    updated: int
    skipped: int


class BulkSetBalancerStatusRequest(BaseModel):
    registration_ids: list[int] = Field(..., max_length=500)
    balancer_status: BalancerStatus
    # Only meaningful together with balancer_status == "excluded".
    exclude_reason: str | None = None


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
