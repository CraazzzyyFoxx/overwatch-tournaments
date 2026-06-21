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
from src.schemas import registration as reg_schemas
from src.schemas.admin import balancer as admin_balancer
from src.schemas.admin import encounter as admin_encounter
from src.schemas.admin import player_sub_role as admin_player_sub_role
from src.schemas.admin import stage as admin_stage
from src.schemas.admin import standing as admin_standing
from src.schemas.admin import team as admin_team
from src.schemas.admin import tournament as admin_tournament
from src.schemas.admin.computation import TournamentComputationJobRead

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
    "rpc.tournament.encounters_overview": Op(response=schemas.EncounterOverviewRead, query=schemas.EncounterSearchQueryParams),
    "rpc.tournament.statistics_overall": Op(response=schemas.OverallStatistics, query_params=(_WS,)),
    "rpc.tournament.owal_results": Op(response=schemas.OwalStandings, query_params=(_WS, _SEASON)),
    "rpc.tournament.owal_seasons": Op(query_params=(_WS,)),
    # ── public reads (arrays) ──────────────────────────────────────────────
    "rpc.tournament.lookup_tournaments": Op(response=schemas.LookupItem, response_array=True, query_params=(_WS, QueryParam("is_league", "boolean"))),
    "rpc.tournament.get_stages": Op(response=schemas.StageRead, response_array=True),
    "rpc.tournament.get_standings": Op(response=schemas.StandingRead, response_array=True, query_params=(_ENTITIES,)),
    "rpc.tournament.statistics_history": Op(response=schemas.TournamentStatistics, response_array=True, query_params=(_WS,)),
    "rpc.tournament.statistics_division": Op(response=schemas.DivisionStatistics, response_array=True, query_params=(_WS,)),
    "rpc.tournament.owal_stacks": Op(response=schemas.LeaguePlayerStack, response_array=True, query_params=(_WS, _SEASON)),
    "rpc.tournament.saved_views": Op(response=schemas.EncounterSavedViewRead, response_array=True, query_params=(_WS,)),
    # ── public reads (paginated) ───────────────────────────────────────────
    "rpc.tournament.list_tournaments": Op(response=Paginated[schemas.TournamentRead], query=schemas.TournamentPaginationSortSearchQueryParams),
    "rpc.tournament.list_encounters": Op(response=Paginated[schemas.EncounterRead], query=schemas.EncounterSearchQueryParams),
    "rpc.tournament.list_matches": Op(response=Paginated[schemas.MatchRead], query=schemas.MatchSearchQueryParams),
    "rpc.tournament.list_teams": Op(response=Paginated[schemas.TeamRead], query=schemas.TeamFilterQueryParams),
    # ── computation job reads ──────────────────────────────────────────────
    "rpc.tournament.job_get": Op(response=TournamentComputationJobRead),
    "rpc.tournament.job_list": Op(response=TournamentComputationJobRead, response_array=True),
    # ── generic CRUD engine (create/update/get/list by entity) ─────────────
    "rpc.tournament.admin.create#tournament": Op(request=admin_tournament.TournamentCreate, response=schemas.TournamentRead),
    "rpc.tournament.admin.create#team": Op(request=admin_team.TeamCreate, response=schemas.TeamRead),
    "rpc.tournament.admin.create#player": Op(request=admin_team.PlayerCreate, response=schemas.PlayerRead),
    "rpc.tournament.admin.create#stage": Op(request=admin_stage.StageCreate, response=schemas.StageRead),
    "rpc.tournament.admin.create#stage_item": Op(request=admin_stage.StageItemCreate, response=schemas.StageItemRead),
    "rpc.tournament.admin.create#stage_item_input": Op(request=admin_stage.StageItemInputCreate, response=schemas.StageItemInputRead),
    "rpc.tournament.admin.create#encounter": Op(request=admin_encounter.EncounterCreate, response=schemas.EncounterRead),
    "rpc.tournament.admin.create#player_sub_role": Op(request=admin_player_sub_role.PlayerSubRoleCreate, response=admin_player_sub_role.PlayerSubRoleRead),
    "rpc.tournament.admin.update#tournament": Op(request=admin_tournament.TournamentUpdate, response=schemas.TournamentRead),
    "rpc.tournament.admin.update#team": Op(request=admin_team.TeamUpdate, response=schemas.TeamRead),
    "rpc.tournament.admin.update#player": Op(request=admin_team.PlayerUpdate, response=schemas.PlayerRead),
    "rpc.tournament.admin.update#stage": Op(request=admin_stage.StageUpdate, response=schemas.StageRead),
    "rpc.tournament.admin.update#stage_item": Op(request=admin_stage.StageItemUpdate, response=schemas.StageItemRead),
    "rpc.tournament.admin.update#stage_item_input": Op(request=admin_stage.StageItemInputUpdate, response=schemas.StageItemInputRead),
    "rpc.tournament.admin.update#encounter": Op(request=admin_encounter.EncounterUpdate, response=schemas.EncounterRead),
    "rpc.tournament.admin.update#standing": Op(request=admin_standing.StandingUpdate, response=schemas.StandingRead),
    "rpc.tournament.admin.update#player_sub_role": Op(request=admin_player_sub_role.PlayerSubRoleUpdate, response=admin_player_sub_role.PlayerSubRoleRead),
    "rpc.tournament.admin.get#tournament": Op(response=schemas.TournamentRead),
    "rpc.tournament.admin.get#team": Op(response=schemas.TeamRead),
    "rpc.tournament.admin.get#stage": Op(response=schemas.StageRead),
    "rpc.tournament.admin.list#stage": Op(response=schemas.StageRead, response_array=True),
    "rpc.tournament.admin.list#player_sub_role": Op(response=admin_player_sub_role.PlayerSubRoleRead, response_array=True, query_params=(_WS, QueryParam("role"), QueryParam("include_inactive", "boolean"))),
    # ── bespoke: tournament status / lifecycle ─────────────────────────────
    "rpc.tournament.tournament_finish": Op(response=schemas.TournamentRead),
    "rpc.tournament.tournament_status": Op(request=admin_tournament.TournamentStatusTransition, response=schemas.TournamentRead),
    "rpc.tournament.standing_recalculate": Op(response=TournamentComputationJobRead),
    # ── bespoke: stage workflow ────────────────────────────────────────────
    "rpc.tournament.stage_merge": Op(request=admin_stage.MergeGroupStagesRequest, response=schemas.StageRead),
    "rpc.tournament.stage_activate": Op(response=schemas.StageRead),
    "rpc.tournament.stage_generate": Op(response=TournamentComputationJobRead),
    "rpc.tournament.stage_activate_and_generate": Op(response=TournamentComputationJobRead),
    "rpc.tournament.stage_wire": Op(request=admin_stage.WireFromGroupsRequest, response=schemas.StageRead),
    "rpc.tournament.stage_seed": Op(request=admin_stage.SeedTeamsRequest, response=schemas.StageRead),
    # ── integrations: division grids ───────────────────────────────────────
    "rpc.tournament.grid_workspace_create": Op(request=schemas.DivisionGridCreate, response=schemas.DivisionGridRead),
    "rpc.tournament.grid_version_get": Op(response=schemas.DivisionGridVersionRead),
    "rpc.tournament.grid_version_create": Op(request=schemas.DivisionGridVersionCreate, response=schemas.DivisionGridVersionRead),
    "rpc.tournament.grid_version_update": Op(request=schemas.DivisionGridVersionUpdate, response=schemas.DivisionGridVersionRead),
    "rpc.tournament.grid_version_publish": Op(response=schemas.DivisionGridVersionRead),
    "rpc.tournament.grid_version_clone": Op(response=schemas.DivisionGridVersionRead),
    "rpc.tournament.grid_mapping_put": Op(request=schemas.DivisionGridMappingWrite, response=schemas.DivisionGridMappingRead),
    "rpc.tournament.grid_marketplace_import": Op(request=schemas.DivisionGridMarketplaceImportRequest, response=schemas.DivisionGridMarketplaceImportResult),
    # ── integrations: Challonge fetch (reads) ──────────────────────────────
    "rpc.tournament.challonge_fetch_tournament": Op(response=schemas.ChallongeTournament),
    "rpc.tournament.challonge_fetch_participants": Op(response=schemas.ChallongeParticipant, response_array=True),
    "rpc.tournament.challonge_fetch_matches": Op(response=schemas.ChallongeMatch, response_array=True),
    # ── integrations: Google Sheets ────────────────────────────────────────
    "rpc.tournament.sheet_get": Op(response=admin_balancer.BalancerGoogleSheetFeedRead),
    "rpc.tournament.sheet_upsert": Op(request=admin_balancer.BalancerGoogleSheetFeedUpsert, response=admin_balancer.BalancerGoogleSheetFeedRead),
    "rpc.tournament.sheet_sync": Op(response=admin_balancer.BalancerGoogleSheetFeedSyncResponse),
    "rpc.tournament.sheet_mapping_catalog": Op(response=admin_balancer.BalancerGoogleSheetMappingCatalogResponse),
    "rpc.tournament.sheet_suggest_mapping": Op(request=admin_balancer.BalancerGoogleSheetMappingSuggestRequest, response=admin_balancer.BalancerGoogleSheetMappingSuggestResponse),
    "rpc.tournament.sheet_preview": Op(request=admin_balancer.BalancerGoogleSheetMappingPreviewRequest, response=admin_balancer.BalancerGoogleSheetMappingPreviewResponse),
    "rpc.tournament.sheet_players_export": Op(response=admin_balancer.BalancerPlayerExportResponse),
    # ── registration admin ─────────────────────────────────────────────────
    "rpc.tournament.reg_form_get": Op(response=reg_schemas.RegistrationFormRead),
    "rpc.tournament.reg_form_upsert": Op(request=reg_schemas.RegistrationFormUpsert, response=reg_schemas.RegistrationFormRead),
    "rpc.tournament.reg_list": Op(response=admin_balancer.BalancerRegistrationRead, response_array=True),
    "rpc.tournament.reg_create_manual": Op(request=admin_balancer.BalancerRegistrationCreateRequest, response=admin_balancer.BalancerRegistrationRead),
    "rpc.tournament.reg_update": Op(request=admin_balancer.BalancerRegistrationUpdateRequest, response=admin_balancer.BalancerRegistrationRead),
    "rpc.tournament.reg_approve": Op(response=admin_balancer.BalancerRegistrationRead),
    "rpc.tournament.reg_reject": Op(response=admin_balancer.BalancerRegistrationRead),
    "rpc.tournament.reg_exclusion": Op(request=admin_balancer.BalancerRegistrationExclusionRequest, response=admin_balancer.BalancerRegistrationRead),
    "rpc.tournament.reg_withdraw": Op(response=admin_balancer.BalancerRegistrationRead),
    "rpc.tournament.reg_restore": Op(response=admin_balancer.BalancerRegistrationRead),
    "rpc.tournament.reg_bulk_approve": Op(response=admin_balancer.BulkApproveResponse),
    "rpc.tournament.reg_set_balancer_status": Op(request=admin_balancer.SetBalancerStatusRequest, response=admin_balancer.BalancerRegistrationRead),
    "rpc.tournament.reg_bulk_add_balancer": Op(response=admin_balancer.BulkBalancerStatusResponse),
    "rpc.tournament.reg_rank_autofill_preview": Op(request=admin_balancer.BalancerRegistrationRankAutofillRequest, response=admin_balancer.BalancerRegistrationRankAutofillResponse),
    "rpc.tournament.reg_rank_autofill_apply": Op(request=admin_balancer.BalancerRegistrationRankAutofillRequest, response=admin_balancer.BalancerRegistrationRankAutofillResponse),
    "rpc.tournament.reg_export_users": Op(response=admin_balancer.RegistrationUserExportResponse),
    "rpc.tournament.reg_check_in": Op(request=admin_balancer.CheckInRequest, response=admin_balancer.BalancerRegistrationRead),
    "rpc.tournament.reg_user_rank_history": Op(response=admin_balancer.BalancerRegistrationRankHistoryResponse),
    # ── registration status catalog ────────────────────────────────────────
    "rpc.tournament.regstatus_catalog": Op(response=admin_balancer.BalancerRegistrationStatusRead, response_array=True),
    "rpc.tournament.regstatus_list": Op(response=admin_balancer.BalancerRegistrationStatusRead, response_array=True),
    "rpc.tournament.regstatus_create": Op(request=admin_balancer.BalancerRegistrationStatusCreate, response=admin_balancer.BalancerRegistrationStatusRead),
    "rpc.tournament.regstatus_update": Op(request=admin_balancer.BalancerRegistrationStatusUpdate, response=admin_balancer.BalancerRegistrationStatusRead),
    "rpc.tournament.regstatus_builtin_upsert": Op(request=admin_balancer.BalancerRegistrationStatusUpdate, response=admin_balancer.BalancerRegistrationStatusRead),
    # ── public registration (captain/self-service) ─────────────────────────
    "rpc.tournament.reg_pub_create": Op(request=reg_schemas.RegistrationCreate, response=reg_schemas.RegistrationRead),
    "rpc.tournament.reg_pub_update_me": Op(request=reg_schemas.RegistrationUpdate, response=reg_schemas.RegistrationRead),
    "rpc.tournament.reg_pub_withdraw_me": Op(response=reg_schemas.RegistrationStatusResponse),
    "rpc.tournament.reg_pub_check_in": Op(response=reg_schemas.RegistrationRead),
    # ── encounter saved-view write ─────────────────────────────────────────
    "rpc.tournament.saved_view_create": Op(request=schemas.EncounterSavedViewCreate, response=schemas.EncounterSavedViewRead),
}
