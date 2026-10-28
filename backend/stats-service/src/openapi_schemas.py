"""OpenAPI request/response model map for stats-service RPC subjects.

Schemas-only module consumed by the export script — see ``shared.rpc.openapi``.
Models mirror the handlers' direct model construction / flow return annotations
(src/rpc/*.py). Sync acks, ad-hoc dicts and 204 handlers are omitted.
"""

from __future__ import annotations

import typing

from shared.core.pagination import Paginated, PaginationQueryParams, PaginationSortQueryParams
from shared.rpc.openapi import Op, QueryParam
from shared.schemas.match_doc import MatchDoc
from src import schemas

# Sort-field whitelists of the public reads mirror the handlers' Literal constraints. Drift only affects the `sort`
# enum shown in docs.
_STAT_SORT = typing.Literal["id", "name", "value"]
_ENC_SORT = typing.Literal["id", "name", "closeness", "round", "played_at"]
_MATE_SORT = typing.Literal["id", "name", "winrate", "tournaments"]

# Reusable ad-hoc query params of the public reads (handlers read these via c.q/c.q1, no query model).
_ENTITIES = QueryParam("entities", array=True)
_WS = QueryParam("workspace_id", "integer")
_TID = QueryParam("tournament_id", "integer")
# Every statistics read names its game explicitly (no default, no fallback).
_DISCIPLINE = QueryParam("discipline", required=True, description="Installed discipline code")
# A list read's optional game (spec §8.1): absent or "all" is every game.
_OPTIONAL_DISCIPLINE = QueryParam("discipline", description='Installed discipline code; absent or "all": every game')

OPERATIONS: dict[str, Op] = {
    # ── canonical match ingest: the public request is the bare owt.match/1 document ─
    "rpc.stats.ingest.submit": Op(request=MatchDoc, response=schemas.IngestJobRead),
    "rpc.stats.ingest.get": Op(response=schemas.IngestJobRead),
    "rpc.stats.ingest.game_observation": Op(response=schemas.GameObservationRead),
    "rpc.stats.ingest.bind": Op(request=schemas.BindIngestRequest, response=schemas.IngestJobRead),
    # ── match-log admin ────────────────────────────────────────────────────
    "rpc.stats.logs.queue_status": Op(response=schemas.QueueDepth, response_array=True),
    "rpc.stats.logs.history": Op(
        response=schemas.LogHistoryResponse,
        query_params=(
            QueryParam("tournament_id", "integer"),
            QueryParam("encounter_id", "integer"),
            QueryParam("workspace_id", "integer"),
            QueryParam("status"),
            QueryParam("search"),
            QueryParam("limit", "integer"),
            QueryParam("offset", "integer"),
        ),
    ),
    "rpc.stats.logs.stats": Op(
        response=schemas.LogStatsRead,
        query_params=(
            QueryParam("tournament_id", "integer"),
            QueryParam("encounter_id", "integer"),
            QueryParam("workspace_id", "integer"),
        ),
    ),
    "rpc.stats.logs.retry": Op(request=schemas.LogRetryRequest, response=schemas.LogRecordRead),
    "rpc.stats.logs.upload": Op(response=schemas.LogUploadResponse),
    # ── OverFast rank (public reads) ───────────────────────────────────────
    "rpc.stats.rank.user_history": Op(
        response=schemas.RankHistoryResponse,
        query_params=(
            QueryParam("granularity"),
            QueryParam("date_from"),
            QueryParam("date_to"),
            QueryParam("social_account_id", "integer"),
            QueryParam("platform"),
            QueryParam("role"),
            QueryParam("discipline"),
        ),
    ),
    "rpc.stats.rank.game_account_history": Op(
        response=schemas.RankHistoryResponse,
        query_params=(
            QueryParam("granularity"),
            QueryParam("date_from"),
            QueryParam("date_to"),
            QueryParam("platform"),
            QueryParam("role"),
            QueryParam("discipline"),
        ),
    ),
    "rpc.stats.rank.user_current": Op(
        response=schemas.CurrentRanksResponse, query_params=(QueryParam("platform"), QueryParam("discipline"))
    ),
    "rpc.stats.rank.stats": Op(
        response=schemas.RankCollectionStats,
        query_params=(QueryParam("workspace_id", "integer"), QueryParam("discipline")),
    ),
    "rpc.stats.rank.fetch_log": Op(
        response=schemas.FetchLogRead,
        response_array=True,
        query_params=(
            QueryParam("workspace_id", "integer"),
            QueryParam("status"),
            QueryParam("source"),
            QueryParam("before_id", "integer"),
            QueryParam("limit", "integer"),
            QueryParam("discipline"),
        ),
    ),
    "rpc.stats.rank.user_collection": Op(
        response=schemas.CollectionStatusRead,
        response_array=True,
        query_params=(QueryParam("workspace_id", "integer"), QueryParam("discipline")),
    ),
    "rpc.stats.rank.collect": Op(
        request=schemas.CollectTriggerRequest,
        response=schemas.CollectTriggerResponse,
        query_params=(QueryParam("workspace_id", "integer"), QueryParam("discipline")),
    ),
    "rpc.stats.rank.reenable_disabled": Op(
        request=schemas.ReenableDisabledRequest,
        response=schemas.ReenableDisabledResponse,
        query_params=(QueryParam("workspace_id", "integer"), QueryParam("discipline")),
    ),
    # ── subscription collection admin ──────────────────────────────────────
    "rpc.stats.subscription.stats": Op(response=schemas.SubscriptionCollectionStats),
    "rpc.stats.subscription.check_log": Op(response=schemas.SubscriptionCheckLogRead, response_array=True),
    "rpc.stats.subscription.user_collection": Op(response=schemas.SubscriptionUserCollectionRead, response_array=True),
    "rpc.stats.subscription.collect": Op(
        request=schemas.SubscriptionCollectTriggerRequest,
        response=schemas.SubscriptionCollectTriggerResponse,
    ),
    # ── achievement calculate ──────────────────────────────────────────────
    "rpc.stats.ach.calculate": Op(
        request=schemas.AchievementCalculateRequest, response=schemas.AchievementCalculateResponse
    ),
    "rpc.stats.ach.calculate_tournament": Op(
        request=schemas.AchievementCalculateRequest, response=schemas.AchievementCalculateResponse
    ),
    # ── catalog sync (the status answers null when no snapshot is stored) ───────────
    "rpc.stats.catalog.sync": Op(response=schemas.CatalogSyncState),
    "rpc.stats.catalog.sync_status": Op(response=schemas.CatalogSyncState),
    # ── settings ───────────────────────────────────────────────────────────
    "rpc.stats.settings.list": Op(response=schemas.SettingRead, response_array=True),
    "rpc.stats.settings.get": Op(response=schemas.SettingRead),
    "rpc.stats.settings.upsert": Op(request=schemas.SettingUpsert, response=schemas.SettingRead),
    # ── achievement rules admin ────────────────────────────────────────────
    "rpc.stats.ach.condition_types": Op(
        response=schemas.ConditionTypeInfo,
        response_array=True,
        query_params=(QueryParam("discipline", required=True),),
    ),
    "rpc.stats.ach.validate": Op(
        request=schemas.ConditionTreeValidateRequest, response=schemas.ConditionTreeValidateResponse
    ),
    "rpc.stats.ach.seed": Op(response=schemas.SeedResultRead, query_params=(QueryParam("discipline", required=True),)),
    "rpc.stats.ach.reset": Op(
        response=schemas.HardResetResultRead, query_params=(QueryParam("discipline", required=True),)
    ),
    "rpc.stats.ach.export": Op(query_params=(QueryParam("discipline", required=True),)),
    "rpc.stats.ach.import": Op(
        request=schemas.AchievementRuleExportEnvelope, response=schemas.AchievementRuleImportResult
    ),
    "rpc.stats.ach.lib_import": Op(
        request=schemas.AchievementLibraryImportRequest, response=schemas.AchievementRuleImportResult
    ),
    "rpc.stats.ach.list": Op(
        response=Paginated[schemas.AchievementRuleRead],
        query=schemas.AchievementRuleListQueryParams,
    ),
    "rpc.stats.ach.get": Op(response=schemas.AchievementRuleRead),
    "rpc.stats.ach.create": Op(request=schemas.AchievementRuleCreate, response=schemas.AchievementRuleRead),
    "rpc.stats.ach.update": Op(request=schemas.AchievementRuleUpdate, response=schemas.AchievementRuleRead),
    "rpc.stats.ach.evaluate": Op(request=schemas.EvaluateRequest, response=schemas.EvaluationRunRead),
    "rpc.stats.ach.runs": Op(response=schemas.EvaluationRunRead, response_array=True),
    "rpc.stats.ach.lib_workspaces": Op(
        response=schemas.AchievementLibraryWorkspaceRead,
        response_array=True,
        query_params=(QueryParam("discipline", required=True),),
    ),
    "rpc.stats.ach.lib_list": Op(
        response=schemas.AchievementLibraryRuleRead,
        response_array=True,
        query_params=(
            QueryParam("source_workspace_id", "integer", required=True),
            QueryParam("discipline", required=True),
        ),
    ),
    "rpc.stats.ach.overrides_list": Op(
        response=schemas.OverrideRead,
        response_array=True,
        query_params=(QueryParam("discipline", required=True),),
    ),
    "rpc.stats.ach.override_create": Op(request=schemas.OverrideCreate, response=schemas.OverrideRead),
    # ── public reads: statistics, /users/* and achievements ───────────────────
    "rpc.stats.statistics.character_playtime": Op(
        response=Paginated[schemas.CharacterPlaytime], query=schemas.CharacterPlaytimeQueryPaginationParams
    ),
    "rpc.stats.statistics.character_leaderboard": Op(
        response=schemas.CharacterLeaderboardResponse, query=schemas.CharacterLeaderboardQueryParams
    ),
    "rpc.stats.statistics.tournament_player_stats": Op(response=schemas.TournamentPlayerStats),
    "rpc.stats.statistics.champion": Op(
        response=Paginated[schemas.PlayerStatistics],
        query=PaginationSortQueryParams[_STAT_SORT],
        query_params=(_OPTIONAL_DISCIPLINE,),
    ),
    "rpc.stats.statistics.winrate": Op(
        response=Paginated[schemas.PlayerStatistics],
        query=PaginationSortQueryParams[_STAT_SORT],
        query_params=(_OPTIONAL_DISCIPLINE,),
    ),
    "rpc.stats.statistics.players": Op(
        response=Paginated[schemas.PlayerLeaderboardRow],
        query=schemas.PlayerLeaderboardQueryParams,
        query_params=(_OPTIONAL_DISCIPLINE, _WS),
    ),
    "rpc.stats.statistics.records": Op(response=schemas.StatRecords, query_params=(_OPTIONAL_DISCIPLINE, _WS)),
    "rpc.stats.statistics.maps": Op(response=schemas.MapStatsResponse, query_params=(_WS,)),
    "rpc.stats.users.get_profile": Op(response=schemas.UserProfile, query_params=(_OPTIONAL_DISCIPLINE, _WS)),
    "rpc.stats.users.draft_card": Op(response=schemas.UserDraftCard, query_params=(_DISCIPLINE, _WS)),
    "rpc.stats.users.overview": Op(
        response=schemas.UserOverviewResponse,
        query=schemas.UserOverviewQueryParams,
        query_params=(_OPTIONAL_DISCIPLINE,),
    ),
    "rpc.stats.users.overview_stats": Op(
        response=schemas.UserOverviewStats,
        query=schemas.UserOverviewStatsQueryParams,
        query_params=(_OPTIONAL_DISCIPLINE,),
    ),
    "rpc.stats.users.overview_catalog": Op(
        response=schemas.UserCatalogResponse,
        query=schemas.UserCatalogQueryParams,
        query_params=(_OPTIONAL_DISCIPLINE,),
    ),
    "rpc.stats.users.compare": Op(
        response=schemas.UserCompareResponse, query=schemas.UserCompareQueryParams, query_params=(_DISCIPLINE,)
    ),
    "rpc.stats.users.compare_characters": Op(
        response=schemas.UserCharacterCompareResponse,
        query=schemas.UserCharacterCompareQueryParams,
        query_params=(_DISCIPLINE,),
    ),
    "rpc.stats.users.tournaments": Op(response=schemas.UserTournamentList, query_params=(_OPTIONAL_DISCIPLINE, _WS)),
    "rpc.stats.users.tournament": Op(response=schemas.UserTournamentWithStats),
    "rpc.stats.users.tournament_encounters": Op(response=schemas.EncounterReadWithUserStats, response_array=True),
    "rpc.stats.users.tournament_leaderboard": Op(response=schemas.LobbyLeaderboard, query_params=(QueryParam("stat"),)),
    "rpc.stats.users.maps": Op(
        response=Paginated[schemas.UserMap], query=schemas.UserMapsSearchQueryParams, query_params=(_DISCIPLINE,)
    ),
    "rpc.stats.users.maps_summary": Op(
        response=schemas.UserMapsSummary, query=schemas.UserMapsSearchQueryParams, query_params=(_DISCIPLINE,)
    ),
    "rpc.stats.users.encounters": Op(
        response=Paginated[schemas.EncounterReadWithUserStats],
        query=PaginationSortQueryParams[_ENC_SORT],
        query_params=(
            _OPTIONAL_DISCIPLINE,
            QueryParam("result"),
            QueryParam("stage"),
            QueryParam("mvp1", "boolean"),
            QueryParam("has_logs", "boolean"),
            QueryParam("opponent"),
        ),
    ),
    "rpc.stats.users.matches_summary": Op(response=schemas.UserMatchesSummary, query_params=(_DISCIPLINE, _WS)),
    "rpc.stats.users.characters": Op(
        response=Paginated[schemas.CharacterWithUserStats],
        query=PaginationQueryParams,
        query_params=(_DISCIPLINE, QueryParam("stats", array=True), _TID, _WS),
    ),
    "rpc.stats.users.teammates": Op(
        response=Paginated[schemas.UserBestTeammate],
        query=PaginationSortQueryParams[_MATE_SORT],
        query_params=(_DISCIPLINE,),
    ),
    "rpc.stats.achievements.get": Op(response=schemas.AchievementRead),
    "rpc.stats.achievements.list": Op(
        response=Paginated[schemas.AchievementRead], query=schemas.AchievementListQueryParams
    ),
    "rpc.stats.achievements.user": Op(
        response=schemas.UserAchievementRead,
        response_array=True,
        query_params=(
            _TID,
            QueryParam("without_tournament", "boolean"),
            _ENTITIES,
            _WS,
            QueryParam("include_locked", "boolean"),
            QueryParam(
                "discipline", description="Installed discipline code: only that game's rules (earned and locked)"
            ),
        ),
    ),
    "rpc.stats.achievements.users": Op(response=Paginated[schemas.AchievementEarned], query=PaginationQueryParams),
}
