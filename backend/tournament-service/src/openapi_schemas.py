"""OpenAPI request/response model map for tournament-service RPC subjects.

Schemas-only module (no flows/DB) consumed by the export script — see
``shared.rpc.openapi``. Models below mirror the return annotations of the flow
functions each handler calls (src/rpc/*.py + src/services/*/flows.py) and the
generic-CRUD registry (src/services/admin/registry.py).

Endpoints returning ad-hoc dicts / None (204) are intentionally omitted — they
fall back to a generic object in the gateway docs.
"""

from __future__ import annotations

from shared.core.pagination import Paginated
from shared.rpc.openapi import Op, QueryParam
from src import schemas
from src.schemas import captain as captain_schemas
from src.schemas import encounter_report_form as report_form_schemas
from src.schemas import registration as reg_schemas
from src.schemas import registration_team as reg_team_schemas

# Reusable ad-hoc query params (handlers read these via _q/_q1, no query model).
_ENTITIES = QueryParam("entities", array=True)
_WS = QueryParam("workspace_id", "integer")
_SEASON = QueryParam("season")

OPERATIONS: dict[str, Op] = {
    # ── public reads (single object) ───────────────────────────────────────
    "rpc.tournament.get_tournament": Op(response=schemas.TournamentRead, query_params=(_ENTITIES,)),
    "rpc.tournament.get_team": Op(response=schemas.TeamRead, query_params=(_ENTITIES,)),
    "rpc.tournament.get_encounter": Op(response=schemas.EncounterRead, query_params=(_ENTITIES,)),
    "rpc.tournament.get_match": Op(response=schemas.MatchReadWithStats, query_params=(_ENTITIES, _WS)),
    "rpc.tournament.get_match_kill_feed": Op(response=schemas.MatchKillFeedRead, query_params=(_WS,)),
    "rpc.tournament.encounters_overview": Op(
        response=schemas.EncounterOverviewRead, query=schemas.EncounterSearchQueryParams
    ),
    "rpc.tournament.statistics_overall": Op(response=schemas.OverallStatistics, query_params=(_WS,)),
    "rpc.tournament.owal_results": Op(response=schemas.OwalStandings, query_params=(_WS, _SEASON)),
    "rpc.tournament.owal_seasons": Op(query_params=(_WS,)),
    # ── public reads (arrays) ──────────────────────────────────────────────
    "rpc.tournament.lookup_tournaments": Op(
        response=schemas.LookupItem, response_array=True, query_params=(_WS, QueryParam("is_league", "boolean"))
    ),
    "rpc.tournament.get_stages": Op(response=schemas.StageRead, response_array=True),
    "rpc.tournament.get_standings": Op(response=schemas.StandingRead, response_array=True, query_params=(_ENTITIES,)),
    "rpc.tournament.statistics_history": Op(
        response=schemas.TournamentStatistics, response_array=True, query_params=(_WS,)
    ),
    "rpc.tournament.statistics_division": Op(
        response=schemas.DivisionStatistics, response_array=True, query_params=(_WS,)
    ),
    "rpc.tournament.owal_stacks": Op(
        response=schemas.LeaguePlayerStack, response_array=True, query_params=(_WS, _SEASON)
    ),
    "rpc.tournament.saved_views": Op(response=schemas.EncounterSavedViewRead, response_array=True, query_params=(_WS,)),
    # ── public reads (paginated) ───────────────────────────────────────────
    "rpc.tournament.list_tournaments": Op(
        response=Paginated[schemas.TournamentRead], query=schemas.TournamentPaginationSortSearchQueryParams
    ),
    "rpc.tournament.tournaments_facets": Op(
        response=schemas.TournamentFacets, query=schemas.TournamentFacetsQueryParams
    ),
    "rpc.tournament.list_encounters": Op(
        response=Paginated[schemas.EncounterRead], query=schemas.EncounterSearchQueryParams
    ),
    "rpc.tournament.list_matches": Op(response=Paginated[schemas.MatchRead], query=schemas.MatchSearchQueryParams),
    "rpc.tournament.list_teams": Op(response=Paginated[schemas.TeamRead], query=schemas.TeamFilterQueryParams),
    # ── computation job reads ──────────────────────────────────────────────
    "rpc.tournament.job_get": Op(response=schemas.TournamentComputationJobRead),
    "rpc.tournament.job_list": Op(response=schemas.TournamentComputationJobRead, response_array=True),
    # ── generic CRUD engine (create/update/get/list by entity) ─────────────
    "rpc.tournament.admin.create#tournament": Op(request=schemas.TournamentCreate, response=schemas.TournamentRead),
    "rpc.tournament.admin.create#team": Op(request=schemas.TeamCreate, response=schemas.TeamRead),
    "rpc.tournament.admin.create#player": Op(request=schemas.PlayerCreate, response=schemas.PlayerRead),
    "rpc.tournament.admin.create#stage": Op(request=schemas.StageCreate, response=schemas.StageRead),
    "rpc.tournament.admin.create#stage_item": Op(request=schemas.StageItemCreate, response=schemas.StageItemRead),
    "rpc.tournament.admin.create#stage_item_input": Op(
        request=schemas.StageItemInputCreate, response=schemas.StageItemInputRead
    ),
    "rpc.tournament.admin.create#encounter": Op(request=schemas.EncounterCreate, response=schemas.EncounterRead),
    "rpc.tournament.admin.create#player_sub_role": Op(
        request=schemas.PlayerSubRoleCreate, response=schemas.PlayerSubRoleRead
    ),
    "rpc.tournament.admin.create#tournament_link": Op(
        request=schemas.TournamentLinkCreate, response=schemas.TournamentLinkRead
    ),
    "rpc.tournament.admin.update#tournament": Op(request=schemas.TournamentUpdate, response=schemas.TournamentRead),
    "rpc.tournament.admin.update#team": Op(request=schemas.TeamUpdate, response=schemas.TeamRead),
    "rpc.tournament.admin.update#player": Op(request=schemas.PlayerUpdate, response=schemas.PlayerRead),
    "rpc.tournament.admin.update#stage": Op(request=schemas.StageUpdate, response=schemas.StageRead),
    "rpc.tournament.admin.update#stage_item": Op(request=schemas.StageItemUpdate, response=schemas.StageItemRead),
    "rpc.tournament.admin.update#stage_item_input": Op(
        request=schemas.StageItemInputUpdate, response=schemas.StageItemInputRead
    ),
    "rpc.tournament.admin.update#encounter": Op(request=schemas.EncounterUpdate, response=schemas.EncounterRead),
    "rpc.tournament.admin.update#standing": Op(request=schemas.StandingUpdate, response=schemas.StandingRead),
    "rpc.tournament.admin.update#player_sub_role": Op(
        request=schemas.PlayerSubRoleUpdate, response=schemas.PlayerSubRoleRead
    ),
    "rpc.tournament.admin.update#tournament_link": Op(
        request=schemas.TournamentLinkUpdate, response=schemas.TournamentLinkRead
    ),
    "rpc.tournament.admin.get#tournament": Op(response=schemas.TournamentRead),
    "rpc.tournament.admin.get#team": Op(response=schemas.TeamRead),
    "rpc.tournament.admin.get#stage": Op(response=schemas.StageRead),
    "rpc.tournament.admin.list#stage": Op(response=schemas.StageRead, response_array=True),
    "rpc.tournament.admin.list#player_sub_role": Op(
        response=schemas.PlayerSubRoleRead,
        response_array=True,
        query_params=(_WS, QueryParam("role"), QueryParam("include_inactive", "boolean")),
    ),
    "rpc.tournament.admin.list#tournament_link": Op(
        response=schemas.TournamentLinkRead,
        response_array=True,
        query_params=(
            QueryParam("tournament_id", "integer", required=True),
            QueryParam("active_only", "boolean"),
        ),
    ),
    # ── bespoke: team image (binary upload + delete) ───────────────────────
    "rpc.tournament.teams.image_upload": Op(response=schemas.TeamRead),
    "rpc.tournament.teams.image_delete": Op(response=schemas.TeamRead),
    # ── bespoke: tournament cover/logo (binary upload + delete) ────────────
    "rpc.tournament.tournaments.image_upload": Op(response=schemas.TournamentRead),
    "rpc.tournament.tournaments.image_delete": Op(response=schemas.TournamentRead),
    # ── bespoke: registered-team image (binary upload + delete) ────────────
    "rpc.tournament.regteam_image_upload": Op(response=reg_team_schemas.RegistrationTeamRead),
    "rpc.tournament.regteam_image_delete": Op(response=reg_team_schemas.RegistrationTeamRead),
    # ── bespoke: tournament status / lifecycle ─────────────────────────────
    "rpc.tournament.tournament_finish": Op(response=schemas.TournamentRead),
    "rpc.tournament.tournament_status": Op(request=schemas.TournamentStatusTransition, response=schemas.TournamentRead),
    "rpc.tournament.tournament_schedule_set": Op(
        request=schemas.TournamentScheduleSet, response=schemas.TournamentRead
    ),
    "rpc.tournament.standing_recalculate": Op(response=schemas.TournamentComputationJobRead),
    # ── bespoke: stage workflow ────────────────────────────────────────────
    "rpc.tournament.stage_merge": Op(request=schemas.MergeGroupStagesRequest, response=schemas.StageRead),
    "rpc.tournament.stage_activate": Op(response=schemas.StageRead),
    "rpc.tournament.stage_deactivate": Op(response=schemas.StageRead),
    "rpc.tournament.stage_generate": Op(response=schemas.TournamentComputationJobRead),
    "rpc.tournament.stage_activate_and_generate": Op(response=schemas.TournamentComputationJobRead),
    "rpc.tournament.stage_auto_wire": Op(response=schemas.StageRead),
    "rpc.tournament.stage_wire": Op(request=schemas.WireFromGroupsRequest, response=schemas.StageRead),
    "rpc.tournament.stage_seed": Op(request=schemas.SeedTeamsRequest, response=schemas.StageRead),
    # ── integrations: division grids ───────────────────────────────────────
    "rpc.tournament.grid_workspace_create": Op(request=schemas.DivisionGridCreate, response=schemas.DivisionGridRead),
    "rpc.tournament.grid_update": Op(request=schemas.DivisionGridUpdate, response=schemas.DivisionGridRead),
    "rpc.tournament.grid_portable_export": Op(response=schemas.DivisionGridPortableDocument),
    "rpc.tournament.grid_portable_import": Op(
        request=schemas.DivisionGridPortableImportRequest, response=schemas.DivisionGridRead
    ),
    "rpc.tournament.grid_version_get": Op(response=schemas.DivisionGridVersionRead),
    "rpc.tournament.grid_version_create": Op(
        request=schemas.DivisionGridVersionCreate, response=schemas.DivisionGridVersionRead
    ),
    "rpc.tournament.grid_version_update": Op(
        request=schemas.DivisionGridVersionUpdate, response=schemas.DivisionGridVersionRead
    ),
    "rpc.tournament.grid_version_publish": Op(response=schemas.DivisionGridVersionRead),
    "rpc.tournament.grid_version_readiness": Op(response=schemas.DivisionGridActivationReadiness),
    "rpc.tournament.grid_version_activate": Op(response=schemas.DivisionGridVersionRead),
    "rpc.tournament.grid_version_clone": Op(response=schemas.DivisionGridVersionRead),
    "rpc.tournament.grid_save": Op(request=schemas.DivisionGridSaveRequest, response=schemas.DivisionGridSaveResult),
    "rpc.tournament.grid_mapping_put": Op(
        request=schemas.DivisionGridMappingWrite, response=schemas.DivisionGridMappingRead
    ),
    "rpc.tournament.grid_marketplace_preflight": Op(
        request=schemas.DivisionGridMarketplaceImportRequest,
        response=schemas.DivisionGridMarketplacePreflightResult,
    ),
    "rpc.tournament.grid_marketplace_import": Op(
        request=schemas.DivisionGridMarketplaceImportRequest, response=schemas.DivisionGridImportJobRead
    ),
    "rpc.tournament.grid_import_job_get": Op(response=schemas.DivisionGridImportJobRead),
    "rpc.tournament.grid_import_jobs_list": Op(
        response=schemas.DivisionGridImportJobRead,
        response_array=True,
        query_params=(_WS, QueryParam("active_only", "boolean"), QueryParam("limit", "integer")),
    ),
    # ── integrations: Challonge fetch (reads) ──────────────────────────────
    "rpc.tournament.challonge_fetch_tournament": Op(response=schemas.ChallongeTournament),
    "rpc.tournament.challonge_fetch_participants": Op(response=schemas.ChallongeParticipant, response_array=True),
    "rpc.tournament.challonge_fetch_matches": Op(response=schemas.ChallongeMatch, response_array=True),
    # ── bootstrap importers (formerly parser-service rpc.parser.*) ─────────
    "rpc.tournament.challonge_create_tournament": Op(
        response=schemas.TournamentRead,
        query_params=(
            QueryParam("workspace_id", "integer", required=True),
            QueryParam("start_date", required=True),
            QueryParam("end_date", required=True),
            QueryParam("challonge_slug", required=True),
            QueryParam("is_league", "boolean"),
            QueryParam("division_grid_version_id", "integer"),
        ),
    ),
    "rpc.tournament.challonge_team_preview": Op(
        response=schemas.ChallongeTeamSyncPreview, query_params=(QueryParam("tournament_id", "integer", required=True),)
    ),
    "rpc.tournament.challonge_team_apply": Op(
        request=schemas.ChallongeTeamSyncRequest,
        response=schemas.ChallongeTeamSyncResult,
        query_params=(QueryParam("tournament_id", "integer", required=True),),
    ),
    # ── integrations: Google Sheets ────────────────────────────────────────
    "rpc.tournament.sheet_get": Op(response=schemas.BalancerGoogleSheetFeedRead),
    "rpc.tournament.sheet_upsert": Op(
        request=schemas.BalancerGoogleSheetFeedUpsert, response=schemas.BalancerGoogleSheetFeedRead
    ),
    "rpc.tournament.sheet_sync": Op(response=schemas.BalancerGoogleSheetFeedSyncResponse),
    "rpc.tournament.sheet_mapping_catalog": Op(response=schemas.BalancerGoogleSheetMappingCatalogResponse),
    "rpc.tournament.sheet_suggest_mapping": Op(
        request=schemas.BalancerGoogleSheetMappingSuggestRequest,
        response=schemas.BalancerGoogleSheetMappingSuggestResponse,
    ),
    "rpc.tournament.sheet_preview": Op(
        request=schemas.BalancerGoogleSheetMappingPreviewRequest,
        response=schemas.BalancerGoogleSheetMappingPreviewResponse,
    ),
    "rpc.tournament.sheet_players_export": Op(
        response=schemas.BalancerPlayerExportResponse,
        query_params=(
            QueryParam("format", description="xv-1 (solver input, default) or owt-1 (full snapshot)"),
            QueryParam(
                "include_private",
                "boolean",
                description="owt-1 only: add notes, admin notes, custom fields and contacts",
            ),
        ),
    ),
    # ── registration admin ─────────────────────────────────────────────────
    "rpc.tournament.reg_form_get": Op(response=reg_schemas.RegistrationFormRead),
    "rpc.tournament.reg_form_upsert": Op(
        request=reg_schemas.RegistrationFormUpsert, response=reg_schemas.RegistrationFormRead
    ),
    "rpc.tournament.reg_list": Op(response=schemas.BalancerRegistrationRead, response_array=True),
    "rpc.tournament.reg_create_manual": Op(
        request=schemas.BalancerRegistrationCreateRequest, response=schemas.BalancerRegistrationRead
    ),
    "rpc.tournament.reg_update": Op(
        request=schemas.BalancerRegistrationUpdateRequest, response=schemas.BalancerRegistrationRead
    ),
    "rpc.tournament.reg_approve": Op(response=schemas.BalancerRegistrationRead),
    "rpc.tournament.reg_reject": Op(response=schemas.BalancerRegistrationRead),
    "rpc.tournament.reg_include_balancer": Op(response=schemas.BalancerRegistrationRead),
    "rpc.tournament.reg_withdraw": Op(response=schemas.BalancerRegistrationRead),
    "rpc.tournament.reg_restore": Op(response=schemas.BalancerRegistrationRead),
    "rpc.tournament.reg_bulk_approve": Op(response=schemas.BulkApproveResponse),
    "rpc.tournament.reg_set_balancer_status": Op(
        request=schemas.SetBalancerStatusRequest, response=schemas.BalancerRegistrationRead
    ),
    "rpc.tournament.reg_bulk_add_balancer": Op(response=schemas.BulkBalancerStatusResponse),
    "rpc.tournament.reg_bulk_set_balancer_status": Op(
        request=schemas.BulkSetBalancerStatusRequest, response=schemas.BulkBalancerStatusResponse
    ),
    "rpc.tournament.reg_rank_autofill_preview": Op(
        request=schemas.BalancerRegistrationRankAutofillRequest,
        response=schemas.BalancerRegistrationRankAutofillResponse,
    ),
    "rpc.tournament.reg_rank_autofill_apply": Op(
        request=schemas.BalancerRegistrationRankAutofillRequest,
        response=schemas.BalancerRegistrationRankAutofillResponse,
    ),
    "rpc.tournament.reg_export_users": Op(response=schemas.RegistrationUserExportResponse),
    "rpc.tournament.reg_check_in": Op(request=schemas.CheckInRequest, response=schemas.BalancerRegistrationRead),
    "rpc.tournament.reg_user_rank_history": Op(response=schemas.BalancerRegistrationRankHistoryResponse),
    # ── registration status catalog ────────────────────────────────────────
    "rpc.tournament.regstatus_catalog": Op(response=schemas.BalancerRegistrationStatusRead, response_array=True),
    "rpc.tournament.regstatus_list": Op(response=schemas.BalancerRegistrationStatusRead, response_array=True),
    "rpc.tournament.regstatus_create": Op(
        request=schemas.BalancerRegistrationStatusCreate, response=schemas.BalancerRegistrationStatusRead
    ),
    "rpc.tournament.regstatus_update": Op(
        request=schemas.BalancerRegistrationStatusUpdate, response=schemas.BalancerRegistrationStatusRead
    ),
    "rpc.tournament.regstatus_builtin_upsert": Op(
        request=schemas.BalancerRegistrationStatusUpdate, response=schemas.BalancerRegistrationStatusRead
    ),
    # ── workspace subscription provider config ─────────────────────────────
    "rpc.tournament.sub_config_list": Op(response=reg_schemas.SubscriptionProviderConfigListResponse),
    "rpc.tournament.sub_config_upsert": Op(
        request=reg_schemas.SubscriptionProviderConfigUpsert,
        response=reg_schemas.SubscriptionProviderConfigRead,
    ),
    # ── workspace subscription requirement ─────────────────────────────────
    "rpc.tournament.sub_requirement_get": Op(response=reg_schemas.WorkspaceSubscriptionRequirementRead),
    "rpc.tournament.sub_requirement_upsert": Op(
        request=reg_schemas.WorkspaceSubscriptionRequirementUpsert,
        response=reg_schemas.WorkspaceSubscriptionRequirementRead,
    ),
    # ── public registration (captain/self-service) ─────────────────────────
    "rpc.tournament.reg_pub_create": Op(request=reg_schemas.RegistrationCreate, response=reg_schemas.RegistrationRead),
    "rpc.tournament.reg_pub_update_me": Op(
        request=reg_schemas.RegistrationUpdate, response=reg_schemas.RegistrationRead
    ),
    "rpc.tournament.reg_pub_withdraw_me": Op(response=reg_schemas.RegistrationStatusResponse),
    "rpc.tournament.reg_pub_check_in": Op(response=reg_schemas.RegistrationRead),
    "rpc.tournament.sub_me": Op(response=reg_schemas.SubscriptionStatusRead),
    "rpc.tournament.sub_redeem_code": Op(
        request=reg_schemas.SubscriptionRedeemRequest,
        response=reg_schemas.SubscriptionStatusRead,
    ),
    # ── team registration: public + captain surfaces ───────────────────────
    # ``regteam_invite`` declares a request only: its response is the invite read
    # model PLUS the one-time raw token, a superset of any model in this package.
    "rpc.tournament.regteam_list_public": Op(response=reg_team_schemas.RegistrationTeamListResponse),
    "rpc.tournament.regteam_invite_preview": Op(response=reg_team_schemas.RegistrationTeamInvitePreview),
    "rpc.tournament.regteam_create": Op(
        request=reg_team_schemas.RegistrationTeamCreateRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_invite": Op(request=reg_team_schemas.RegistrationTeamInviteCreateRequest),
    "rpc.tournament.regteam_accept": Op(
        request=reg_team_schemas.RegistrationTeamAcceptRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_free_agents": Op(response=reg_team_schemas.RegistrationFreeAgentListResponse),
    "rpc.tournament.regteam_my_invites": Op(response=reg_team_schemas.RegistrationTeamInviteOfferListResponse),
    "rpc.tournament.regteam_invite_history_public": Op(response=reg_team_schemas.RegistrationTeamInviteHistoryResponse),
    # ── team registration: organizer surfaces ──────────────────────────────
    "rpc.tournament.regteam_list": Op(
        response=reg_team_schemas.RegistrationTeamListResponse,
        query_params=(QueryParam("include_terminal", "boolean"),),
    ),
    "rpc.tournament.regteam_reject": Op(
        request=reg_team_schemas.RegistrationTeamRejectRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_invite_history": Op(response=reg_team_schemas.RegistrationTeamInviteHistoryResponse),
    "rpc.tournament.regteam_rename": Op(
        request=reg_team_schemas.RegistrationTeamRenameRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_place_member": Op(
        request=reg_team_schemas.RegistrationTeamPlaceMemberRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_set_manager": Op(
        request=reg_team_schemas.RegistrationTeamSetManagerRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_extend_invite": Op(request=reg_team_schemas.RegistrationTeamExtendInviteRequest),
    "rpc.tournament.regteam_lock": Op(response=reg_team_schemas.RegistrationTeamRead),
    "rpc.tournament.regteam_check_in": Op(
        request=reg_team_schemas.RegistrationTeamCheckInRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_cover_subscription": Op(
        request=reg_team_schemas.RegistrationTeamRedeemSubscriptionRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_rename_admin": Op(
        request=reg_team_schemas.RegistrationTeamRenameRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_unlock": Op(response=reg_team_schemas.RegistrationTeamRead),
    "rpc.tournament.regteam_admission": Op(
        request=reg_team_schemas.RegistrationTeamAdmissionRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_notes": Op(
        request=reg_team_schemas.RegistrationTeamNotesRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_place_admin": Op(
        request=reg_team_schemas.RegistrationTeamPlaceMemberRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    "rpc.tournament.regteam_attach_admin": Op(
        request=reg_team_schemas.RegistrationTeamAttachAdminRequest,
        response=reg_team_schemas.RegistrationTeamRead,
    ),
    # ── encounter saved-view write ─────────────────────────────────────────
    "rpc.tournament.saved_view_create": Op(
        request=schemas.EncounterSavedViewCreate, response=schemas.EncounterSavedViewRead
    ),
    # ── scrim rooms (docs/plans/2026-08-12-scrim-rooms.md) ─────────────────
    # Unlike the pre-game pick-ban subjects a room is played through, these five
    # return whole typed models, so they carry request/response maps rather than
    # falling back to a generic object.
    "rpc.tournament.scrim_create": Op(request=schemas.ScrimCreateRequest, response=schemas.ScrimRoomRead),
    "rpc.tournament.scrim_list_mine": Op(response=schemas.ScrimRoomListRead, query_params=(_WS,)),
    "rpc.tournament.scrim_get": Op(response=schemas.ScrimRoomRead),
    "rpc.tournament.scrim_claim": Op(response=schemas.ScrimRoomRead),
    "rpc.tournament.scrim_close": Op(response=schemas.ScrimRoomRead),
    # ── match report form (per-tournament captain-report config) ───────────
    "rpc.tournament.report_form_get": Op(response=report_form_schemas.MatchReportFormRead),
    "rpc.tournament.report_form_upsert": Op(
        request=report_form_schemas.MatchReportFormUpsert, response=report_form_schemas.MatchReportFormRead
    ),
    # captain_reports is deliberately absent: it answers the ad-hoc envelope
    # {reports, form} rather than a bare CaptainReportRead array, and this module
    # maps whole request/response models only (see the module docstring).
    # ── encounter result (the single admin write + its audit trail) ────────
    "rpc.tournament.encounter_set_result": Op(
        request=schemas.EncounterSetResultInput, response=schemas.EncounterResultRead
    ),
    "rpc.tournament.encounter_reopen_result": Op(response=schemas.EncounterResultRead),
    "rpc.tournament.encounter_result_audit": Op(response=schemas.EncounterResultAuditRead, response_array=True),
    # ── per-map match edit (admin) ─────────────────────────────────────────
    # Answers an ad-hoc dict of the match's own columns rather than MatchRead, so
    # only the request body is mapped here.
    "rpc.tournament.encounter_update_match": Op(request=schemas.MatchUpdate),
    # ── captain pick/ban + map reporting (request bodies only) ─────────────
    # Each of these answers the room's ad-hoc state dict -- the pick-ban state,
    # one serialized entry, the undo block, the reconciliation verdict -- not a
    # model, so they map their inputs and leave the response generic.
    "rpc.tournament.captain_pick_ban_act": Op(request=captain_schemas.PickBanActionInput),
    "rpc.tournament.captain_pick_ban_elect_opener": Op(request=captain_schemas.ElectOpenerInput),
    "rpc.tournament.captain_pick_ban_undo": Op(request=captain_schemas.PickBanUndoInput),
    "rpc.tournament.captain_report_map": Op(request=captain_schemas.MapReportInput),
    # ── captain reports admin list (cross-tournament, workspace-scoped) ────
    "rpc.tournament.admin_encounter_reports_list": Op(
        response=Paginated[schemas.EncounterReportsRow],
        query=schemas.EncounterReportsQueryParams,
    ),
    "rpc.tournament.admin_encounter_reports_stats": Op(
        response=schemas.EncounterReportsStats,
        query=schemas.EncounterReportsQueryParams,
    ),
    # ── parsed matches (one row per played map) ────────────────────────────
    "rpc.tournament.admin_matches_list": Op(
        response=Paginated[schemas.AdminMatchRow],
        query=schemas.AdminMatchesQueryParams,
    ),
    "rpc.tournament.admin_match_get": Op(response=schemas.AdminMatchDetail),
}
