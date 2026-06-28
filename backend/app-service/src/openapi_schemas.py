"""OpenAPI request/response model map for app-service RPC subjects.

Schemas-only module (no flows/DB) consumed by the export script — see
``shared.rpc.openapi``. Models mirror the return annotations of the flows each
handler calls (src/rpc/*.py + src/services/*/flows.py + the CRUD registries).

Generic CRUD engine keys are ``<subject>#<entity>``. Endpoints returning ad-hoc
dicts / None (204) are omitted (generic object in the docs).
"""

from __future__ import annotations

import typing

from shared.core.pagination import (
    Paginated,
    PaginationQueryParams,
    PaginationSortQueryParams,
    PaginationSortSearchQueryParams,
)
from shared.rpc.openapi import Op, QueryParam

from src import schemas
from src.schemas.admin.gamemode import GamemodeCreate, GamemodeUpdate
from src.schemas.admin.hero import HeroCreate, HeroUpdate
from src.schemas.admin.map import MapCreate, MapUpdate
from src.schemas.admin.user import (
    SocialAccountCreate,
    SocialAccountUpdate,
    SocialVisibilityUpdate,
    UserCreate,
    UserUpdate,
)
from src.schemas.admin.user_merge import (
    UserMergeExecuteRequest,
    UserMergeExecuteResponse,
    UserMergePreviewRequest,
    UserMergePreviewResponse,
)

# Sort-field whitelists mirror the read handlers' Literal constraints (used to
# build the generic query-param aliases below). Drift only affects the `sort`
# enum shown in docs.
_HERO_SORT = typing.Literal["id", "name", "slug", "similarity:name", "similarity:slug"]
_MAP_SORT = typing.Literal["id", "gamemode_id", "name", "similarity:name"]
_GAMEMODE_SORT = typing.Literal["id", "name", "slug", "similarity:name", "similarity:slug"]
_ACH_SORT = typing.Literal["id", "name", "slug", "rarity", "similarity:name", "similarity:slug"]
_USER_SORT = typing.Literal["id", "name", "similarity:name"]
_STAT_SORT = typing.Literal["id", "name", "value"]
_ENC_SORT = typing.Literal["id", "name", "home_team_id", "away_team_id", "closeness", "round"]
_MATE_SORT = typing.Literal["id", "name", "winrate", "tournaments"]

# Reusable ad-hoc query params (handlers read these via c.q/c.q1, no query model).
_ENTITIES = QueryParam("entities", array=True)
_WS = QueryParam("workspace_id", "integer")
_TID = QueryParam("tournament_id", "integer")

OPERATIONS: dict[str, Op] = {
    # ── generic CRUD read engine (rpc.app.read.{get,list}#<entity>) ────────
    "rpc.app.read.get#hero": Op(response=schemas.HeroRead),
    "rpc.app.read.list#hero": Op(response=Paginated[schemas.HeroRead], query=PaginationSortSearchQueryParams[_HERO_SORT]),
    "rpc.app.read.get#map": Op(response=schemas.MapRead),
    "rpc.app.read.list#map": Op(response=Paginated[schemas.MapRead], query=PaginationSortSearchQueryParams[_MAP_SORT]),
    "rpc.app.read.get#gamemode": Op(response=schemas.GamemodeRead),
    "rpc.app.read.list#gamemode": Op(response=Paginated[schemas.GamemodeRead], query=PaginationSortSearchQueryParams[_GAMEMODE_SORT]),
    "rpc.app.read.get#achievement": Op(response=schemas.AchievementRead),
    "rpc.app.read.list#achievement": Op(response=Paginated[schemas.AchievementRead], query=PaginationSortQueryParams[_ACH_SORT]),
    # ── lookups ────────────────────────────────────────────────────────────
    "rpc.app.heroes.lookup": Op(response=schemas.LookupItem, response_array=True),
    "rpc.app.maps.lookup": Op(response=schemas.LookupItem, response_array=True),
    "rpc.app.gamemodes.lookup": Op(response=schemas.LookupItem, response_array=True),
    # ── heroes (bespoke) ───────────────────────────────────────────────────
    "rpc.app.heroes.playtime": Op(response=Paginated[schemas.HeroPlaytime], query=schemas.HeroPlaytimeQueryPaginationParams),
    "rpc.app.heroes.leaderboard": Op(response=Paginated[schemas.HeroLeaderboardEntry], query=schemas.HeroLeaderboardQueryParams),
    # ── statistics ─────────────────────────────────────────────────────────
    "rpc.app.statistics.dashboard": Op(response=schemas.DashboardStats),
    "rpc.app.statistics.champion": Op(response=Paginated[schemas.PlayerStatistics], query=PaginationSortQueryParams[_STAT_SORT]),
    "rpc.app.statistics.winrate": Op(response=Paginated[schemas.PlayerStatistics], query=PaginationSortQueryParams[_STAT_SORT]),
    "rpc.app.statistics.won_maps": Op(response=Paginated[schemas.PlayerStatistics], query=PaginationSortQueryParams[_STAT_SORT]),
    # ── users (bespoke reads) ──────────────────────────────────────────────
    "rpc.app.users.get_profile": Op(response=schemas.UserProfile),
    "rpc.app.users.search": Op(response=schemas.UserSearch, response_array=True, query_params=(QueryParam("query"), QueryParam("fields", array=True))),
    "rpc.app.users.overview": Op(response=Paginated[schemas.UserOverviewRow], query=schemas.UserOverviewQueryParams),
    "rpc.app.users.overview_stats": Op(response=schemas.UserOverviewStats, query=schemas.UserOverviewStatsQueryParams),
    "rpc.app.users.overview_catalog": Op(response=schemas.UserCatalogResponse, query=schemas.UserCatalogQueryParams),
    "rpc.app.users.compare": Op(response=schemas.UserCompareResponse, query=schemas.UserCompareQueryParams),
    "rpc.app.users.compare_heroes": Op(response=schemas.UserHeroCompareResponse, query=schemas.UserHeroCompareQueryParams),
    "rpc.app.users.by_name": Op(response=schemas.UserRead),
    "rpc.app.users.tournaments": Op(response=schemas.UserTournament, response_array=True),
    "rpc.app.users.tournament": Op(response=schemas.UserTournamentWithStats),
    "rpc.app.users.maps": Op(response=Paginated[schemas.UserMap], query=schemas.UserMapsSearchQueryParams),
    "rpc.app.users.maps_summary": Op(response=schemas.UserMapsSummary, query=schemas.UserMapsSearchQueryParams),
    "rpc.app.users.encounters": Op(response=Paginated[schemas.EncounterReadWithUserStats], query=PaginationSortQueryParams[_ENC_SORT], query_params=(QueryParam("result"), QueryParam("stage"), QueryParam("mvp1", "boolean"), QueryParam("has_logs", "boolean"), QueryParam("opponent"))),
    "rpc.app.users.matches_summary": Op(response=schemas.UserMatchesSummary),
    "rpc.app.users.heroes": Op(response=Paginated[schemas.HeroWithUserStats], query=PaginationQueryParams, query_params=(QueryParam("stats", array=True), _TID, _WS)),
    "rpc.app.users.teammates": Op(response=Paginated[schemas.UserBestTeammate], query=PaginationSortQueryParams[_MATE_SORT]),
    # ── achievements (bespoke) ─────────────────────────────────────────────
    "rpc.app.achievements.user": Op(response=schemas.UserAchievementRead, response_array=True, query_params=(_TID, QueryParam("without_tournament", "boolean"), _ENTITIES, _WS, QueryParam("include_locked", "boolean"))),
    "rpc.app.achievements.users": Op(response=Paginated[schemas.AchievementEarned], query=PaginationQueryParams),
    # ── workspaces ─────────────────────────────────────────────────────────
    "rpc.app.workspaces.get": Op(response=schemas.WorkspaceRead),
    "rpc.app.workspaces.list": Op(response=schemas.WorkspaceRead, response_array=True),
    "rpc.app.workspaces.icon_upload": Op(response=schemas.WorkspaceRead),
    "rpc.app.workspaces.icon_delete": Op(response=schemas.WorkspaceRead),
    "rpc.app.workspaces.create": Op(request=schemas.WorkspaceCreate, response=schemas.WorkspaceRead),
    "rpc.app.admin.update#workspace": Op(request=schemas.WorkspaceUpdate, response=schemas.WorkspaceRead),
    "rpc.app.workspaces.members_list": Op(response=schemas.WorkspaceMemberRead, response_array=True),
    "rpc.app.workspaces.member_add": Op(request=schemas.WorkspaceMemberCreate, response=schemas.WorkspaceMemberRead),
    "rpc.app.workspaces.member_update": Op(request=schemas.WorkspaceMemberUpdate, response=schemas.WorkspaceMemberRead),
    # ── metadata admin (hero/map/gamemode) ─────────────────────────────────
    "rpc.app.heroes.admin_create": Op(request=HeroCreate, response=schemas.HeroRead),
    "rpc.app.heroes.admin_update": Op(request=HeroUpdate, response=schemas.HeroRead),
    "rpc.app.maps.admin_create": Op(request=MapCreate, response=schemas.MapRead),
    "rpc.app.maps.admin_update": Op(request=MapUpdate, response=schemas.MapRead),
    "rpc.app.gamemodes.admin_create": Op(request=GamemodeCreate, response=schemas.GamemodeRead),
    "rpc.app.gamemodes.admin_update": Op(request=GamemodeUpdate, response=schemas.GamemodeRead),
    # ── users admin (CRUD + identities + merge) ────────────────────────────
    "rpc.app.users.admin_create": Op(request=UserCreate, response=schemas.UserRead),
    "rpc.app.users.admin_update": Op(request=UserUpdate, response=schemas.UserRead),
    "rpc.app.users.merge_preview": Op(request=UserMergePreviewRequest, response=UserMergePreviewResponse),
    "rpc.app.users.merge_execute": Op(request=UserMergeExecuteRequest, response=UserMergeExecuteResponse),
    "rpc.app.users.social_add": Op(request=SocialAccountCreate, response=schemas.UserRead),
    "rpc.app.users.social_update": Op(request=SocialAccountUpdate, response=schemas.UserRead),
    "rpc.app.users.social_delete": Op(response=schemas.UserRead),
    "rpc.app.users.social_set_primary": Op(response=schemas.UserRead),
    "rpc.app.users.social_set_visibility": Op(request=SocialVisibilityUpdate, response=schemas.UserRead),
    "rpc.app.users.avatar_delete": Op(response=schemas.UserRead),
    "rpc.app.users.avatar_upload": Op(response=schemas.UserRead),
}
