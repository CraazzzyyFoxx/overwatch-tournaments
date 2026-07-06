"""Facade for the registration admin service.

The former god module was split into cohesive submodules (one concern per
file, mirroring ``src/services/tournament``):

* ``_common``       — cross-cutting helpers (tournament/form/grid lookups,
  role replacement, active-role and balancer-status predicates).
* ``sheet_parsing`` — pure Google-Sheets row parsing and mapping suggestion.
* ``sheet_sync``    — sheet fetch, feed CRUD/preview and the sync orchestration.
* ``rank_sources``  — rank-signal loaders (OW composites, balancer/tournament
  history) and grid normalization for the autofill.
* ``rank_autofill`` — autofill stage chain, plan building and application.
* ``lifecycle``     — registration lifecycle CRUD (create/approve/reject/
  check-in/balancer status/bulk ops).
* ``export``        — balancer "xv-1" export and domain-user provisioning.

This module only re-exports every name that used to be importable from
``src.services.registration.admin`` so existing import sites keep working.
Functions resolve their collaborators from their *owning* module's globals —
to monkeypatch a dependency in tests, patch the owning module (e.g.
``src.services.registration.sheet_sync``), not this facade.
"""

from __future__ import annotations

from src import models
from src.services.registration._common import (
    BATTLE_TAG_RE,
    VALID_BALANCER_STATUSES,
    VALID_REGISTRATION_STATUSES,
    _active_roles,
    _register_registration_changed,
    active_roles_all_ranked,
    ensure_tournament_exists,
    form_custom_field_defs,
    get_form_custom_field_defs,
    get_registration_form,
    get_tournament_grid,
    get_tournament_grid_from_rows,
    included_balancer_status,
    registration_has_active_roles,
    replace_registration_roles,
    sync_included_balancer_status,
)
from src.services.registration.export import (
    _ensure_user_battle_tag,
    _find_user_by_battle_tag,
    _registration_identity_handles,
    _upsert_user_from_registration,
    export_active_registrations,
    export_registrations_to_users,
    list_active_registrations_for_balancer,
    registration_source,
    serialize_registration_for_export,
)
from src.services.registration.lifecycle import (
    _as_utc,
    approve_registration,
    bulk_add_to_balancer,
    bulk_approve_registrations,
    check_in_registration,
    create_manual_registration,
    ensure_unique_battle_tag,
    get_registration_by_id,
    is_check_in_window_active,
    list_registrations,
    reject_registration,
    restore_registration,
    set_balancer_status,
    set_registration_exclusion,
    soft_delete_registration,
    uncheck_in_registration,
    update_registration_profile,
    validate_registration_status_value,
    withdraw_registration,
)
from src.services.registration.mapping_catalog import (
    DEFAULT_MAPPING_TARGETS,  # noqa: F401 - compatibility re-export
)
from src.services.registration.rank_autofill import (
    _DEFAULT_STAGE_ORDER_BY_MODE,
    _active_roles_ranked_after_updates,
    _autofill_lookback_cutoff,
    _rank_autofill_balancer_addition,
    _rank_snapshot_payload,
    _ResolvedAutofillStage,
    autofill_registration_ranks_from_parsed,
    build_registration_rank_autofill_plan,
    resolve_autofill_stages,
)
from src.services.registration.rank_sources import (
    HERO_CLASS_TO_REGISTRATION_ROLE,
    OW_RANK_WEEK_WINDOW,
    RANK_ROLE_BY_REGISTRATION_ROLE,
    REGISTRATION_ROLE_LABELS,
    _build_autofill_rank_normalizer,
    _build_priority_rank_data,
    _compute_ow_week_rank_value,
    _group_ow_rank_signals,
    _load_latest_ranks_from_balancer_history,
    _load_latest_ranks_from_tournament_history,
    _load_main_battle_tags_by_key,
    _load_ow_rank_signals_by_social_account_id,
    _load_rank_autofill_registrations,
    _load_tournament_for_autofill,
    _map_ow_rank_value,
    _map_ow_snapshot_rank,
    _normalize_history_rank,
    _OwRankSignals,
    _RankData,
    load_user_balancer_rank_history,
)
from src.services.registration.service import ensure_player_identity
from src.services.registration.sheet_parsing import (
    _parse_sr_value,
    _valid_role_subrole_entry,
    build_default_value_mapping,
    build_registration_role_payloads,
    default_mapping_target,
    extract_battle_tags,
    get_selector_values,
    map_role_subrole_token,
    map_role_subrole_tokens,
    map_role_token,
    map_subrole_token,
    parse_boolean,
    parse_role_subrole_token_list,
    parse_role_token_list,
    parse_sheet_row,
    parse_sheet_row_detailed,
    parse_target_value,
    serialize_datetime,
    serialize_parsed_fields,
    suggest_mapping_from_headers,
)
from src.services.registration.sheet_sync import (
    SYNC_ERROR_SAMPLE_LIMIT,
    SheetSyncResult,
    _existing_match_keys,
    _resolve_header_keys,
    _validate_feed_mapping,
    apply_sheet_fields_to_registration,
    build_mapping_catalog,
    fetch_google_sheet_rows,
    get_google_sheet_feed,
    get_mapping_catalog,
    preview_google_sheet_mapping,
    require_google_sheet_feed,
    suggest_google_sheet_mapping,
    sync_due_google_sheet_feeds,
    sync_google_sheet_feed,
    upsert_google_sheet_feed,
)
from src.services.tournament.events import (
    enqueue_registration_approved,
    enqueue_registration_rejected,
)
from src.services.tournament.realtime_commit import register_tournament_realtime_update

__all__ = [
    # _common
    "BATTLE_TAG_RE",
    "VALID_BALANCER_STATUSES",
    "VALID_REGISTRATION_STATUSES",
    "_active_roles",
    "_register_registration_changed",
    "active_roles_all_ranked",
    "ensure_tournament_exists",
    "form_custom_field_defs",
    "get_form_custom_field_defs",
    "get_registration_form",
    "get_tournament_grid",
    "get_tournament_grid_from_rows",
    "included_balancer_status",
    "registration_has_active_roles",
    "replace_registration_roles",
    "sync_included_balancer_status",
    # sheet_parsing
    "_parse_sr_value",
    "_valid_role_subrole_entry",
    "build_default_value_mapping",
    "build_registration_role_payloads",
    "default_mapping_target",
    "extract_battle_tags",
    "get_selector_values",
    "map_role_subrole_token",
    "map_role_subrole_tokens",
    "map_role_token",
    "map_subrole_token",
    "parse_boolean",
    "parse_role_subrole_token_list",
    "parse_role_token_list",
    "parse_sheet_row",
    "parse_sheet_row_detailed",
    "parse_target_value",
    "serialize_datetime",
    "serialize_parsed_fields",
    "suggest_mapping_from_headers",
    # sheet_sync
    "SYNC_ERROR_SAMPLE_LIMIT",
    "SheetSyncResult",
    "_existing_match_keys",
    "_resolve_header_keys",
    "_validate_feed_mapping",
    "apply_sheet_fields_to_registration",
    "build_mapping_catalog",
    "fetch_google_sheet_rows",
    "get_google_sheet_feed",
    "get_mapping_catalog",
    "preview_google_sheet_mapping",
    "require_google_sheet_feed",
    "suggest_google_sheet_mapping",
    "sync_due_google_sheet_feeds",
    "sync_google_sheet_feed",
    "upsert_google_sheet_feed",
    # rank_sources
    "HERO_CLASS_TO_REGISTRATION_ROLE",
    "OW_RANK_WEEK_WINDOW",
    "RANK_ROLE_BY_REGISTRATION_ROLE",
    "REGISTRATION_ROLE_LABELS",
    "_OwRankSignals",
    "_RankData",
    "_build_autofill_rank_normalizer",
    "_build_priority_rank_data",
    "_compute_ow_week_rank_value",
    "_group_ow_rank_signals",
    "_load_latest_ranks_from_balancer_history",
    "_load_latest_ranks_from_tournament_history",
    "_load_main_battle_tags_by_key",
    "_load_ow_rank_signals_by_social_account_id",
    "_load_rank_autofill_registrations",
    "_load_tournament_for_autofill",
    "_map_ow_rank_value",
    "_map_ow_snapshot_rank",
    "_normalize_history_rank",
    "load_user_balancer_rank_history",
    # rank_autofill
    "_DEFAULT_STAGE_ORDER_BY_MODE",
    "_ResolvedAutofillStage",
    "_active_roles_ranked_after_updates",
    "_autofill_lookback_cutoff",
    "_rank_autofill_balancer_addition",
    "_rank_snapshot_payload",
    "autofill_registration_ranks_from_parsed",
    "build_registration_rank_autofill_plan",
    "resolve_autofill_stages",
    # lifecycle
    "_as_utc",
    "approve_registration",
    "bulk_add_to_balancer",
    "bulk_approve_registrations",
    "check_in_registration",
    "create_manual_registration",
    "ensure_unique_battle_tag",
    "get_registration_by_id",
    "is_check_in_window_active",
    "list_registrations",
    "reject_registration",
    "restore_registration",
    "set_balancer_status",
    "set_registration_exclusion",
    "soft_delete_registration",
    "uncheck_in_registration",
    "update_registration_profile",
    "validate_registration_status_value",
    "withdraw_registration",
    # export
    "_ensure_user_battle_tag",
    "_find_user_by_battle_tag",
    "_registration_identity_handles",
    "_upsert_user_from_registration",
    "export_active_registrations",
    "export_registrations_to_users",
    "list_active_registrations_for_balancer",
    "registration_source",
    "serialize_registration_for_export",
    # compatibility re-exports (previously importable from this module)
    "DEFAULT_MAPPING_TARGETS",
    "enqueue_registration_approved",
    "enqueue_registration_rejected",
    "ensure_player_identity",
    "models",
    "register_tournament_realtime_update",
]
