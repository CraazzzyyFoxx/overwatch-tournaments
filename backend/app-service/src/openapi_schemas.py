"""OpenAPI request/response model map for app-service RPC subjects.

Schemas-only module (no flows/DB) consumed by the export script — see
``shared.rpc.openapi``. Models mirror the return annotations of the flows each
handler calls (src/rpc/*.py + src/services/*/service.py + the CRUD registries).

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

# Sort-field whitelists mirror the read handlers' Literal constraints (used to
# build the generic query-param aliases below). Drift only affects the `sort`
# enum shown in docs.
_HERO_SORT = typing.Literal["id", "name", "slug", "similarity:name", "similarity:slug"]
_MAP_SORT = typing.Literal["id", "gamemode_id", "name", "similarity:name"]
_GAMEMODE_SORT = typing.Literal["id", "name", "slug", "similarity:name", "similarity:slug"]
_ACH_SORT = typing.Literal["id", "name", "slug", "rarity", "similarity:name", "similarity:slug"]
_USER_SORT = typing.Literal["id", "name", "similarity:name"]
_STAT_SORT = typing.Literal["id", "name", "value"]
_ENC_SORT = typing.Literal["id", "name", "home_team_id", "away_team_id", "closeness", "round", "played_at"]
_MATE_SORT = typing.Literal["id", "name", "winrate", "tournaments"]

# Reusable ad-hoc query params (handlers read these via c.q/c.q1, no query model).
_ENTITIES = QueryParam("entities", array=True)
_WS = QueryParam("workspace_id", "integer")
_TID = QueryParam("tournament_id", "integer")

OPERATIONS: dict[str, Op] = {
    # ── generic CRUD read engine (rpc.app.read.{get,list}#<entity>) ────────
    "rpc.app.read.get#hero": Op(response=schemas.HeroRead),
    "rpc.app.read.list#hero": Op(
        response=Paginated[schemas.HeroRead], query=PaginationSortSearchQueryParams[_HERO_SORT]
    ),
    "rpc.app.read.get#map": Op(response=schemas.MapRead),
    "rpc.app.read.list#map": Op(response=Paginated[schemas.MapRead], query=PaginationSortSearchQueryParams[_MAP_SORT]),
    "rpc.app.read.get#gamemode": Op(response=schemas.GamemodeRead),
    "rpc.app.read.list#gamemode": Op(
        response=Paginated[schemas.GamemodeRead], query=PaginationSortSearchQueryParams[_GAMEMODE_SORT]
    ),
    "rpc.app.read.get#achievement": Op(response=schemas.AchievementRead),
    "rpc.app.read.list#achievement": Op(
        response=Paginated[schemas.AchievementRead], query=PaginationSortQueryParams[_ACH_SORT]
    ),
    # ── lookups ────────────────────────────────────────────────────────────
    "rpc.app.heroes.lookup": Op(response=schemas.LookupItem, response_array=True),
    "rpc.app.maps.lookup": Op(response=schemas.LookupItem, response_array=True),
    "rpc.app.gamemodes.lookup": Op(response=schemas.LookupItem, response_array=True),
    # ── heroes (bespoke) ───────────────────────────────────────────────────
    "rpc.app.heroes.playtime": Op(
        response=Paginated[schemas.HeroPlaytime], query=schemas.HeroPlaytimeQueryPaginationParams
    ),
    "rpc.app.heroes.leaderboard": Op(
        response=Paginated[schemas.HeroLeaderboardEntry], query=schemas.HeroLeaderboardQueryParams
    ),
    # ── statistics ─────────────────────────────────────────────────────────
    "rpc.app.statistics.dashboard": Op(response=schemas.DashboardStats),
    "rpc.app.statistics.champion": Op(
        response=Paginated[schemas.PlayerStatistics], query=PaginationSortQueryParams[_STAT_SORT]
    ),
    "rpc.app.statistics.winrate": Op(
        response=Paginated[schemas.PlayerStatistics], query=PaginationSortQueryParams[_STAT_SORT]
    ),
    "rpc.app.statistics.won_maps": Op(
        response=Paginated[schemas.PlayerStatistics], query=PaginationSortQueryParams[_STAT_SORT]
    ),
    "rpc.app.statistics.tournament_readiness": Op(response=schemas.TournamentReadiness),
    # ── users (bespoke reads) ──────────────────────────────────────────────
    "rpc.app.users.get_profile": Op(response=schemas.UserProfile),
    "rpc.app.users.search": Op(
        response=schemas.UserSearch,
        response_array=True,
        query_params=(QueryParam("query"), QueryParam("fields", array=True)),
    ),
    "rpc.app.users.overview": Op(response=Paginated[schemas.UserOverviewRow], query=schemas.UserOverviewQueryParams),
    "rpc.app.users.overview_stats": Op(response=schemas.UserOverviewStats, query=schemas.UserOverviewStatsQueryParams),
    "rpc.app.users.overview_catalog": Op(response=schemas.UserCatalogResponse, query=schemas.UserCatalogQueryParams),
    "rpc.app.users.compare": Op(response=schemas.UserCompareResponse, query=schemas.UserCompareQueryParams),
    "rpc.app.users.compare_heroes": Op(
        response=schemas.UserHeroCompareResponse, query=schemas.UserHeroCompareQueryParams
    ),
    "rpc.app.users.by_name": Op(response=schemas.UserRead),
    "rpc.app.users.tournaments": Op(response=schemas.UserTournament, response_array=True),
    "rpc.app.users.tournament": Op(response=schemas.UserTournamentWithStats),
    "rpc.app.users.tournament_encounters": Op(response=schemas.EncounterReadWithUserStats, response_array=True),
    "rpc.app.users.tournament_leaderboard": Op(response=schemas.LobbyLeaderboard, query_params=(QueryParam("stat"),)),
    "rpc.app.users.maps": Op(response=Paginated[schemas.UserMap], query=schemas.UserMapsSearchQueryParams),
    "rpc.app.users.maps_summary": Op(response=schemas.UserMapsSummary, query=schemas.UserMapsSearchQueryParams),
    "rpc.app.users.encounters": Op(
        response=Paginated[schemas.EncounterReadWithUserStats],
        query=PaginationSortQueryParams[_ENC_SORT],
        query_params=(
            QueryParam("result"),
            QueryParam("stage"),
            QueryParam("mvp1", "boolean"),
            QueryParam("has_logs", "boolean"),
            QueryParam("opponent"),
        ),
    ),
    "rpc.app.users.matches_summary": Op(response=schemas.UserMatchesSummary),
    "rpc.app.users.heroes": Op(
        response=Paginated[schemas.HeroWithUserStats],
        query=PaginationQueryParams,
        query_params=(QueryParam("stats", array=True), _TID, _WS),
    ),
    "rpc.app.users.teammates": Op(
        response=Paginated[schemas.UserBestTeammate], query=PaginationSortQueryParams[_MATE_SORT]
    ),
    # ── achievements (bespoke) ─────────────────────────────────────────────
    "rpc.app.achievements.user": Op(
        response=schemas.UserAchievementRead,
        response_array=True,
        query_params=(
            _TID,
            QueryParam("without_tournament", "boolean"),
            _ENTITIES,
            _WS,
            QueryParam("include_locked", "boolean"),
        ),
    ),
    "rpc.app.achievements.users": Op(response=Paginated[schemas.AchievementEarned], query=PaginationQueryParams),
    # ── workspaces ─────────────────────────────────────────────────────────
    "rpc.app.workspaces.get": Op(response=schemas.WorkspaceRead),
    "rpc.app.workspaces.list": Op(response=schemas.WorkspaceRead, response_array=True),
    # by_host answers with an ad-hoc {workspace_id, slug} (or null); only the
    # host query param is declared -- see the module docstring's convention.
    "rpc.app.workspaces.by_host": Op(query_params=(QueryParam("host"),)),
    "rpc.app.workspaces.icon_upload": Op(response=schemas.WorkspaceRead),
    "rpc.app.workspaces.icon_delete": Op(response=schemas.WorkspaceRead),
    "rpc.app.workspaces.create": Op(request=schemas.WorkspaceCreate, response=schemas.WorkspaceRead),
    "rpc.app.admin.update#workspace": Op(request=schemas.WorkspaceUpdate, response=schemas.WorkspaceRead),
    "rpc.app.workspaces.members_list": Op(
        response=Paginated[schemas.WorkspaceMemberRead],
        query_params=(
            QueryParam("page", "integer"),
            QueryParam("per_page", "integer"),
            QueryParam("search"),
            QueryParam("role_id", "integer"),
            QueryParam("sort"),
            QueryParam("order"),
        ),
    ),
    "rpc.app.workspaces.members_autofill_roles": Op(response=schemas.WorkspaceMemberAutofillResult),
    "rpc.app.workspaces.member_add": Op(request=schemas.WorkspaceMemberCreate, response=schemas.WorkspaceMemberRead),
    "rpc.app.workspaces.member_update": Op(request=schemas.WorkspaceMemberUpdate, response=schemas.WorkspaceMemberRead),
    "rpc.app.workspaces.set_custom_domain": Op(
        request=schemas.WorkspaceCustomDomainSet, response=schemas.WorkspaceRead
    ),
    "rpc.app.workspaces.verify_custom_domain": Op(response=schemas.WorkspaceRead),
    "rpc.app.workspaces.clear_custom_domain": Op(response=schemas.WorkspaceRead),
    "rpc.app.workspaces.discord_guild_verify": Op(
        request=schemas.WorkspaceDiscordGuildVerify, response=schemas.WorkspaceRead
    ),
    "rpc.app.workspaces.discord_guild_clear": Op(response=schemas.WorkspaceRead),
    "rpc.app.workspaces.my_discord_guilds": Op(response=schemas.WorkspaceDiscordGuildsRead),
    "rpc.app.workspaces.verification_set": Op(request=schemas.WorkspaceVerificationSet, response=schemas.WorkspaceRead),
    "rpc.app.workspaces.owner_get": Op(response=schemas.WorkspaceOwnerRead),
    "rpc.app.workspaces.owner_set": Op(request=schemas.WorkspaceOwnerSet, response=schemas.WorkspaceOwnerRead),
    "rpc.app.workspaces.owner_transfer": Op(
        request=schemas.WorkspaceOwnerTransfer, response=schemas.WorkspaceOwnerRead
    ),
    # ── metadata admin (hero/map/gamemode) ─────────────────────────────────
    "rpc.app.heroes.admin_create": Op(request=schemas.HeroCreate, response=schemas.HeroRead),
    "rpc.app.heroes.admin_update": Op(request=schemas.HeroUpdate, response=schemas.HeroRead),
    "rpc.app.maps.admin_create": Op(request=schemas.MapCreate, response=schemas.MapRead),
    "rpc.app.maps.admin_update": Op(request=schemas.MapUpdate, response=schemas.MapRead),
    "rpc.app.gamemodes.admin_create": Op(request=schemas.GamemodeCreate, response=schemas.GamemodeRead),
    "rpc.app.gamemodes.admin_update": Op(request=schemas.GamemodeUpdate, response=schemas.GamemodeRead),
    # ── metadata admin: catalog alias-miss queue ───────────────────────────
    "rpc.app.catalog_aliases.misses_list": Op(
        response=Paginated[schemas.CatalogAliasMissRead], query=schemas.CatalogAliasMissListQueryParams
    ),
    "rpc.app.catalog_aliases.attach": Op(request=schemas.CatalogAliasAttach),
    "rpc.app.catalog_aliases.dismiss": Op(),
    # ── platform audit log ─────────────────────────────────────────────────
    "rpc.app.audit_list": Op(response=Paginated[schemas.AuditLogRead], query=schemas.AuditLogListQueryParams),
    # ── users admin (CRUD + identities + merge) ────────────────────────────
    "rpc.app.users.admin_create": Op(request=schemas.UserCreate, response=schemas.UserRead),
    "rpc.app.users.admin_update": Op(request=schemas.UserAdminUpdate, response=schemas.UserRead),
    "rpc.app.users.merge_preview": Op(
        request=schemas.UserMergePreviewRequest, response=schemas.UserMergePreviewResponse
    ),
    "rpc.app.users.merge_execute": Op(
        request=schemas.UserMergeExecuteRequest, response=schemas.UserMergeExecuteResponse
    ),
    "rpc.app.users.social_add": Op(request=schemas.SocialAccountCreate, response=schemas.UserRead),
    "rpc.app.users.social_update": Op(request=schemas.SocialAccountUpdate, response=schemas.UserRead),
    "rpc.app.users.social_verify": Op(response=schemas.UserRead),
    "rpc.app.users.social_delete": Op(response=schemas.UserRead),
    "rpc.app.users.social_set_primary": Op(response=schemas.UserRead),
    "rpc.app.users.social_set_visibility": Op(request=schemas.SocialVisibilityUpdate, response=schemas.UserRead),
    # ── users self-service (capability ``account.social``) ──────────────────
    "rpc.app.users.me_social_list": Op(response=schemas.UserRead),
    "rpc.app.users.me_social_set_primary": Op(response=schemas.UserRead),
    # Request body is the ad-hoc {"visible": bool} the handler reads via
    # c.payload -- deliberately NOT SocialVisibilityUpdate, whose workspace_id
    # this self-service handler ignores (visibility here is always global).
    "rpc.app.users.me_social_set_visibility": Op(response=schemas.UserRead),
    "rpc.app.users.me_set_stream_visibility": Op(request=schemas.StreamVisibilityUpdate, response=schemas.UserRead),
    # Ad-hoc dict / 204 responses (me_favorite_add returns {"ok": True},
    # me_favorite_remove returns 204/None) are intentionally omitted -- see the
    # module docstring's "Endpoints returning ad-hoc dicts / None" convention.
    "rpc.app.users.me_favorites_list": Op(response=schemas.LookupItem, response_array=True),
    "rpc.app.users.avatar_delete": Op(response=schemas.UserRead),
    "rpc.app.users.avatar_upload": Op(response=schemas.UserRead),
    # ── notification inbox + announcement banner ───────────────────────────
    # ``cursor``/``limit`` are read ad-hoc via c.q1, so they are declared here
    # rather than through a query model.
    "rpc.app.notifications_list": Op(
        response=schemas.NotificationInboxRead,
        query_params=(
            QueryParam("cursor", description="Opaque continuation from the previous page's next_cursor."),
            QueryParam("limit", "integer", description="Page size (default 20, capped server-side)."),
        ),
    ),
    "rpc.app.notifications_mark_read": Op(
        request=schemas.NotificationMarkRead, response=schemas.NotificationMarkReadResult
    ),
    "rpc.app.notifications_delete": Op(request=schemas.NotificationDelete, response=schemas.NotificationDeleteResult),
    # ── notifications admin (workspace-scoped operator screen) ─────────────
    "rpc.app.notification_admin_list": Op(
        response=schemas.NotificationAdminPage,
        query_params=(
            _WS,
            QueryParam("kind", description="One notification kind; omitted lists every kind."),
            QueryParam("cursor", description="Opaque continuation from the previous page's next_cursor."),
            QueryParam("limit", "integer", description="Page size (default 50, capped at 200)."),
        ),
    ),
    "rpc.app.notification_admin_retire": Op(
        request=schemas.NotificationRetire, response=schemas.NotificationRetireResult
    ),
    "rpc.app.active_announcements": Op(response=schemas.NotificationItem, response_array=True),
    # ── announcements admin (operator CRUD) ────────────────────────────────
    "rpc.app.announcement_list": Op(
        response=schemas.NotificationItem,
        response_array=True,
        query_params=(
            _WS,
            QueryParam("limit", "integer", description="Page size (default 50, capped at 200)."),
        ),
    ),
    "rpc.app.announcement_create": Op(request=schemas.AnnouncementCreate, response=schemas.NotificationItem),
    "rpc.app.announcement_update": Op(request=schemas.AnnouncementUpdate, response=schemas.NotificationItem),
    # delete answers 204 with no body (the gateway drops the envelope) -- same
    # convention as the other 204 subjects above.
    "rpc.app.announcement_delete": Op(),
}
