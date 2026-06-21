"""OpenAPI request/response model map for parser-service RPC subjects.

Schemas-only module consumed by the export script — see ``shared.rpc.openapi``.
Models mirror the handlers' direct model construction / flow return annotations
(src/rpc/*.py). Sync acks, ad-hoc dicts and 204 handlers are omitted.
"""

from __future__ import annotations

from shared.rpc.openapi import Op

from src import schemas
from src.schemas.admin import achievement_rule as ach_schemas
from src.schemas.admin import discord_channel as discord_schemas
from src.schemas.admin import logs as admin_logs_schemas
from src.schemas.admin import rank_collection as rc_schemas
from src.schemas.admin import settings as settings_schemas

OPERATIONS: dict[str, Op] = {
    # ── match-log admin ────────────────────────────────────────────────────
    "rpc.parser.logs.queue_status": Op(response=admin_logs_schemas.QueueDepth, response_array=True),
    "rpc.parser.logs.history": Op(response=admin_logs_schemas.LogHistoryResponse),
    "rpc.parser.logs.retry": Op(response=admin_logs_schemas.LogRecordRead),
    # ── OverFast rank (public reads) ───────────────────────────────────────
    "rpc.parser.rank.user_history": Op(response=schemas.RankHistoryResponse),
    "rpc.parser.rank.battle_tag_history": Op(response=schemas.RankHistoryResponse),
    "rpc.parser.rank.user_current": Op(response=schemas.CurrentRanksResponse),
    "rpc.parser.rank.fetch_log": Op(response=rc_schemas.FetchLogRead, response_array=True),
    "rpc.parser.rank.user_collection": Op(response=rc_schemas.CollectionStatusRead, response_array=True),
    "rpc.parser.rank.collect": Op(request=rc_schemas.CollectTriggerRequest, response=rc_schemas.CollectTriggerResponse),
    # ── achievement calculate ──────────────────────────────────────────────
    "rpc.parser.ach.calculate": Op(request=schemas.AchievementCalculateRequest, response=schemas.AchievementCalculateResponse),
    "rpc.parser.ach.calculate_tournament": Op(request=schemas.AchievementCalculateRequest, response=schemas.AchievementCalculateResponse),
    # ── settings ───────────────────────────────────────────────────────────
    "rpc.parser.settings.list": Op(response=settings_schemas.SettingRead, response_array=True),
    "rpc.parser.settings.get": Op(response=settings_schemas.SettingRead),
    "rpc.parser.settings.upsert": Op(request=settings_schemas.SettingUpsert, response=settings_schemas.SettingRead),
    # ── discord channel ────────────────────────────────────────────────────
    "rpc.parser.discord_channel.get": Op(response=discord_schemas.DiscordChannelRead),
    "rpc.parser.discord_channel.upsert": Op(request=discord_schemas.DiscordChannelUpsert, response=discord_schemas.DiscordChannelRead),
    # ── achievement rules admin ────────────────────────────────────────────
    "rpc.parser.ach.condition_types": Op(response=ach_schemas.ConditionTypeInfo, response_array=True),
    "rpc.parser.ach.validate": Op(request=ach_schemas.ConditionTreeValidateRequest, response=ach_schemas.ConditionTreeValidateResponse),
    "rpc.parser.ach.list": Op(response=ach_schemas.AchievementRuleRead, response_array=True),
    "rpc.parser.ach.get": Op(response=ach_schemas.AchievementRuleRead),
    "rpc.parser.ach.create": Op(request=ach_schemas.AchievementRuleCreate, response=ach_schemas.AchievementRuleRead),
    "rpc.parser.ach.update": Op(request=ach_schemas.AchievementRuleUpdate, response=ach_schemas.AchievementRuleRead),
    "rpc.parser.ach.evaluate": Op(request=ach_schemas.EvaluateRequest, response=ach_schemas.EvaluationRunRead),
    "rpc.parser.ach.runs": Op(response=ach_schemas.EvaluationRunRead, response_array=True),
    "rpc.parser.ach.lib_workspaces": Op(response=ach_schemas.AchievementLibraryWorkspaceRead, response_array=True),
    "rpc.parser.ach.lib_list": Op(response=ach_schemas.AchievementLibraryRuleRead, response_array=True),
    "rpc.parser.ach.overrides_list": Op(response=ach_schemas.OverrideRead, response_array=True),
    "rpc.parser.ach.override_create": Op(request=ach_schemas.OverrideCreate, response=ach_schemas.OverrideRead),
    # ── bootstrap importers ────────────────────────────────────────────────
    "rpc.parser.tournament.create_with_groups": Op(response=schemas.TournamentRead),
    "rpc.parser.teams.challonge_preview": Op(response=schemas.ChallongeTeamSyncPreview),
    "rpc.parser.teams.create_challonge": Op(request=schemas.ChallongeTeamSyncRequest, response=schemas.ChallongeTeamSyncResult),
}
