"""OpenAPI request/response model map for parser-service RPC subjects.

Schemas-only module consumed by the export script — see ``shared.rpc.openapi``.
Models mirror the handlers' direct model construction / flow return annotations
(src/rpc/*.py). Sync acks, ad-hoc dicts and 204 handlers are omitted.
"""

from __future__ import annotations

from shared.core.pagination import Paginated
from shared.rpc.openapi import Op, QueryParam
from src import schemas

OPERATIONS: dict[str, Op] = {
    # ── match-log admin ────────────────────────────────────────────────────
    "rpc.parser.logs.queue_status": Op(response=schemas.QueueDepth, response_array=True),
    "rpc.parser.logs.history": Op(
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
    "rpc.parser.logs.stats": Op(
        response=schemas.LogStatsRead,
        query_params=(
            QueryParam("tournament_id", "integer"),
            QueryParam("encounter_id", "integer"),
            QueryParam("workspace_id", "integer"),
        ),
    ),
    "rpc.parser.logs.retry": Op(response=schemas.LogRecordRead),
    "rpc.parser.logs.upload": Op(response=schemas.LogUploadResponse),
    # ── OverFast rank (public reads) ───────────────────────────────────────
    "rpc.parser.rank.user_history": Op(
        response=schemas.RankHistoryResponse,
        query_params=(
            QueryParam("granularity"),
            QueryParam("date_from"),
            QueryParam("date_to"),
            QueryParam("social_account_id", "integer"),
            QueryParam("platform"),
            QueryParam("role"),
        ),
    ),
    "rpc.parser.rank.battle_tag_history": Op(
        response=schemas.RankHistoryResponse,
        query_params=(
            QueryParam("granularity"),
            QueryParam("date_from"),
            QueryParam("date_to"),
            QueryParam("platform"),
            QueryParam("role"),
        ),
    ),
    "rpc.parser.rank.user_current": Op(
        response=schemas.CurrentRanksResponse, query_params=(QueryParam("platform", required=True),)
    ),
    "rpc.parser.rank.stats": Op(response=schemas.RankCollectionStats),
    "rpc.parser.rank.fetch_log": Op(response=schemas.FetchLogRead, response_array=True),
    "rpc.parser.rank.user_collection": Op(response=schemas.CollectionStatusRead, response_array=True),
    "rpc.parser.rank.collect": Op(request=schemas.CollectTriggerRequest, response=schemas.CollectTriggerResponse),
    "rpc.parser.rank.reenable_disabled": Op(
        request=schemas.ReenableDisabledRequest, response=schemas.ReenableDisabledResponse
    ),
    # ── subscription collection admin ──────────────────────────────────────
    "rpc.parser.subscription.stats": Op(response=schemas.SubscriptionCollectionStats),
    "rpc.parser.subscription.check_log": Op(response=schemas.SubscriptionCheckLogRead, response_array=True),
    "rpc.parser.subscription.user_collection": Op(response=schemas.SubscriptionUserCollectionRead, response_array=True),
    "rpc.parser.subscription.collect": Op(
        request=schemas.SubscriptionCollectTriggerRequest,
        response=schemas.SubscriptionCollectTriggerResponse,
    ),
    # ── achievement calculate ──────────────────────────────────────────────
    "rpc.parser.ach.calculate": Op(
        request=schemas.AchievementCalculateRequest, response=schemas.AchievementCalculateResponse
    ),
    "rpc.parser.ach.calculate_tournament": Op(
        request=schemas.AchievementCalculateRequest, response=schemas.AchievementCalculateResponse
    ),
    # ── settings ───────────────────────────────────────────────────────────
    "rpc.parser.settings.list": Op(response=schemas.SettingRead, response_array=True),
    "rpc.parser.settings.get": Op(response=schemas.SettingRead),
    "rpc.parser.settings.upsert": Op(request=schemas.SettingUpsert, response=schemas.SettingRead),
    # ── discord channel ────────────────────────────────────────────────────
    "rpc.parser.discord_channel.get": Op(response=schemas.DiscordChannelRead),
    "rpc.parser.discord_channel.upsert": Op(request=schemas.DiscordChannelUpsert, response=schemas.DiscordChannelRead),
    # ── achievement rules admin ────────────────────────────────────────────
    "rpc.parser.ach.condition_types": Op(response=schemas.ConditionTypeInfo, response_array=True),
    "rpc.parser.ach.validate": Op(
        request=schemas.ConditionTreeValidateRequest, response=schemas.ConditionTreeValidateResponse
    ),
    "rpc.parser.ach.list": Op(
        response=Paginated[schemas.AchievementRuleRead],
        query=schemas.AchievementRuleListQueryParams,
    ),
    "rpc.parser.ach.get": Op(response=schemas.AchievementRuleRead),
    "rpc.parser.ach.create": Op(request=schemas.AchievementRuleCreate, response=schemas.AchievementRuleRead),
    "rpc.parser.ach.update": Op(request=schemas.AchievementRuleUpdate, response=schemas.AchievementRuleRead),
    "rpc.parser.ach.evaluate": Op(request=schemas.EvaluateRequest, response=schemas.EvaluationRunRead),
    "rpc.parser.ach.runs": Op(response=schemas.EvaluationRunRead, response_array=True),
    "rpc.parser.ach.lib_workspaces": Op(response=schemas.AchievementLibraryWorkspaceRead, response_array=True),
    "rpc.parser.ach.lib_list": Op(response=schemas.AchievementLibraryRuleRead, response_array=True),
    "rpc.parser.ach.overrides_list": Op(response=schemas.OverrideRead, response_array=True),
    "rpc.parser.ach.override_create": Op(request=schemas.OverrideCreate, response=schemas.OverrideRead),
}
