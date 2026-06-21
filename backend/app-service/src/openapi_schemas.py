"""OpenAPI request/response model map for app-service RPC subjects.

Schemas-only module (no flows/DB) consumed by the export script — see
``shared.rpc.openapi``. Models mirror the return annotations of the flows each
handler calls (src/rpc/*.py + src/services/*/flows.py + the CRUD registries).

Generic CRUD engine keys are ``<subject>#<entity>``. Endpoints returning ad-hoc
dicts / None (204) are omitted (generic object in the docs).
"""

from __future__ import annotations

from shared.core.pagination import Paginated
from shared.rpc.openapi import Op

from src import schemas
from src.schemas.admin.gamemode import GamemodeCreate, GamemodeUpdate
from src.schemas.admin.hero import HeroCreate, HeroUpdate
from src.schemas.admin.map import MapCreate, MapUpdate
from src.schemas.admin.user import (
    BattleTagIdentityCreate,
    BattleTagIdentityUpdate,
    DiscordIdentityCreate,
    DiscordIdentityUpdate,
    TwitchIdentityCreate,
    TwitchIdentityUpdate,
    UserCreate,
    UserUpdate,
)
from src.schemas.admin.user_merge import (
    UserMergeExecuteRequest,
    UserMergeExecuteResponse,
    UserMergePreviewRequest,
    UserMergePreviewResponse,
)

OPERATIONS: dict[str, Op] = {
    # ── generic CRUD read engine (rpc.app.read.{get,list}#<entity>) ────────
    "rpc.app.read.get#hero": Op(response=schemas.HeroRead),
    "rpc.app.read.list#hero": Op(response=Paginated[schemas.HeroRead]),
    "rpc.app.read.get#map": Op(response=schemas.MapRead),
    "rpc.app.read.list#map": Op(response=Paginated[schemas.MapRead]),
    "rpc.app.read.get#gamemode": Op(response=schemas.GamemodeRead),
    "rpc.app.read.list#gamemode": Op(response=Paginated[schemas.GamemodeRead]),
    "rpc.app.read.get#achievement": Op(response=schemas.AchievementRead),
    "rpc.app.read.list#achievement": Op(response=Paginated[schemas.AchievementRead]),
    # ── lookups ────────────────────────────────────────────────────────────
    "rpc.app.heroes.lookup": Op(response=schemas.LookupItem, response_array=True),
    "rpc.app.maps.lookup": Op(response=schemas.LookupItem, response_array=True),
    "rpc.app.gamemodes.lookup": Op(response=schemas.LookupItem, response_array=True),
    # ── heroes (bespoke) ───────────────────────────────────────────────────
    "rpc.app.heroes.playtime": Op(response=Paginated[schemas.HeroPlaytime]),
    "rpc.app.heroes.leaderboard": Op(response=Paginated[schemas.HeroLeaderboardEntry]),
    # ── statistics ─────────────────────────────────────────────────────────
    "rpc.app.statistics.dashboard": Op(response=schemas.DashboardStats),
    "rpc.app.statistics.champion": Op(response=Paginated[schemas.PlayerStatistics]),
    "rpc.app.statistics.winrate": Op(response=Paginated[schemas.PlayerStatistics]),
    "rpc.app.statistics.won_maps": Op(response=Paginated[schemas.PlayerStatistics]),
    # ── users (bespoke reads) ──────────────────────────────────────────────
    "rpc.app.users.get_profile": Op(response=schemas.UserProfile),
    "rpc.app.users.search": Op(response=schemas.UserSearch, response_array=True),
    "rpc.app.users.overview": Op(response=Paginated[schemas.UserOverviewRow]),
    "rpc.app.users.overview_stats": Op(response=schemas.UserOverviewStats),
    "rpc.app.users.overview_catalog": Op(response=schemas.UserCatalogResponse),
    "rpc.app.users.compare": Op(response=schemas.UserCompareResponse),
    "rpc.app.users.compare_heroes": Op(response=schemas.UserHeroCompareResponse),
    "rpc.app.users.by_name": Op(response=schemas.UserRead),
    "rpc.app.users.tournaments": Op(response=schemas.UserTournament, response_array=True),
    "rpc.app.users.tournament": Op(response=schemas.UserTournamentWithStats),
    "rpc.app.users.maps": Op(response=Paginated[schemas.UserMap]),
    "rpc.app.users.maps_summary": Op(response=schemas.UserMapsSummary),
    "rpc.app.users.encounters": Op(response=Paginated[schemas.EncounterReadWithUserStats]),
    "rpc.app.users.matches_summary": Op(response=schemas.UserMatchesSummary),
    "rpc.app.users.heroes": Op(response=Paginated[schemas.HeroWithUserStats]),
    "rpc.app.users.teammates": Op(response=Paginated[schemas.UserBestTeammate]),
    # ── achievements (bespoke) ─────────────────────────────────────────────
    "rpc.app.achievements.user": Op(response=schemas.UserAchievementRead, response_array=True),
    "rpc.app.achievements.users": Op(response=Paginated[schemas.AchievementEarned]),
    # ── workspaces ─────────────────────────────────────────────────────────
    "rpc.app.workspaces.get": Op(response=schemas.WorkspaceRead),
    "rpc.app.workspaces.list": Op(response=schemas.WorkspaceRead, response_array=True),
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
    "rpc.app.users.discord_add": Op(request=DiscordIdentityCreate, response=schemas.UserDiscordRead),
    "rpc.app.users.discord_update": Op(request=DiscordIdentityUpdate, response=schemas.UserDiscordRead),
    "rpc.app.users.battletag_add": Op(request=BattleTagIdentityCreate, response=schemas.UserBattleTagRead),
    "rpc.app.users.battletag_update": Op(request=BattleTagIdentityUpdate, response=schemas.UserBattleTagRead),
    "rpc.app.users.twitch_add": Op(request=TwitchIdentityCreate, response=schemas.UserTwitchRead),
    "rpc.app.users.twitch_update": Op(request=TwitchIdentityUpdate, response=schemas.UserTwitchRead),
    "rpc.app.users.avatar_delete": Op(response=schemas.UserRead),
    "rpc.app.users.avatar_upload": Op(response=schemas.UserRead),
}
