"""Human-readable docs (summary + description) for app-service RPC subjects,
merged into the gateway's OpenAPI by the export script. Keyed by RPC subject
(generic-CRUD keys use "<subject>#<entity>"). Prose only.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    # ── generic CRUD read engine (rpc.app.read.{get,list}#<entity>) ────────────
    "rpc.app.read.get#hero": {
        "summary": "Get hero",
        "description": "Returns a single hero by id (public read via the shared CRUD engine), 404 if not found.",
    },
    "rpc.app.read.list#hero": {
        "summary": "List heroes",
        "description": "Returns a paginated, sortable, name/slug-searchable list of heroes (public read via the shared CRUD engine).",
    },
    "rpc.app.read.get#map": {
        "summary": "Get map",
        "description": "Returns a single map by id with optional entity expansion (public read via the shared CRUD engine), 404 if not found.",
    },
    "rpc.app.read.list#map": {
        "summary": "List maps",
        "description": "Returns a paginated, sortable, name-searchable list of maps (public read via the shared CRUD engine).",
    },
    "rpc.app.read.get#gamemode": {
        "summary": "Get gamemode",
        "description": "Returns a single gamemode by id with optional entity expansion (public read via the shared CRUD engine), 404 if not found.",
    },
    "rpc.app.read.list#gamemode": {
        "summary": "List gamemodes",
        "description": "Returns a paginated, sortable, name/slug-searchable list of gamemodes (public read via the shared CRUD engine).",
    },
    "rpc.app.read.get#achievement": {
        "summary": "Get achievement",
        "description": "Returns a single achievement rule by id with optional entity expansion (public read via the shared CRUD engine), 404 if not found.",
    },
    "rpc.app.read.list#achievement": {
        "summary": "List achievements",
        "description": "Returns a paginated, sortable list of achievements optionally filtered by workspace (public read via the shared CRUD engine).",
    },
    # ── lookups ────────────────────────────────────────────────────────────────
    "rpc.app.heroes.lookup": {
        "summary": "Hero lookup",
        "description": "Returns all heroes as id/name lookup items ordered by name (public, no pagination).",
    },
    "rpc.app.maps.lookup": {
        "summary": "Map lookup",
        "description": "Returns all maps as id/name lookup items ordered by name (public, no pagination).",
    },
    "rpc.app.gamemodes.lookup": {
        "summary": "Gamemode lookup",
        "description": "Returns all gamemodes as id/name lookup items ordered by name (public, no pagination).",
    },
    # ── heroes (bespoke) ─────────────────────────────────────────────────────────
    "rpc.app.heroes.playtime": {
        "summary": "Hero playtime stats",
        "description": "Returns paginated aggregated hero-playtime statistics, optionally scoped to a workspace (public).",
    },
    "rpc.app.heroes.leaderboard": {
        "summary": "Hero leaderboard",
        "description": "Returns a paginated per-hero player leaderboard resolved against the workspace context and its division grid (public).",
    },
    # ── statistics ───────────────────────────────────────────────────────────────
    "rpc.app.statistics.dashboard": {
        "summary": "Dashboard stats",
        "description": "Returns aggregate dashboard statistics for the optional workspace (public).",
    },
    "rpc.app.statistics.champion": {
        "summary": "Most-champion players",
        "description": "Returns paginated, sortable players ranked by tournaments won, optionally workspace-scoped (public).",
    },
    "rpc.app.statistics.winrate": {
        "summary": "Top winrate players",
        "description": "Returns paginated, sortable players ranked by win rate, optionally workspace-scoped (public).",
    },
    "rpc.app.statistics.won_maps": {
        "summary": "Top won-maps players",
        "description": "Returns paginated, sortable players ranked by maps won, optionally workspace-scoped (public).",
    },
    # ── users (bespoke reads) ──────────────────────────────────────────────────────
    "rpc.app.users.list": {
        "summary": "List users",
        "description": "Returns a paginated, sortable, name-searchable list of players (public).",
    },
    "rpc.app.users.get_profile": {
        "summary": "User profile",
        "description": "Returns a player's full profile resolved against the workspace context and division grid (public).",
    },
    "rpc.app.users.search": {
        "summary": "Search users",
        "description": "Returns players matching a free-text query across the requested identity fields (public).",
    },
    "rpc.app.users.overview": {
        "summary": "Users overview",
        "description": "Returns a paginated, workspace-normalized player overview table built from the workspace grid (public).",
    },
    "rpc.app.users.overview_stats": {
        "summary": "Users overview stats",
        "description": "Returns aggregate statistics for the players-overview table computed against the workspace grid (public).",
    },
    "rpc.app.users.overview_catalog": {
        "summary": "Users overview catalog",
        "description": "Returns the filter-catalog (facets) for the players-overview table from the workspace grid (public).",
    },
    "rpc.app.users.compare": {
        "summary": "Compare users",
        "description": "Returns a head-to-head comparison between the given user and others, resolved against the default division grid (public).",
    },
    "rpc.app.users.compare_heroes": {
        "summary": "Compare user heroes",
        "description": "Returns a per-hero head-to-head comparison for the given user against others using the default grid (public).",
    },
    "rpc.app.users.by_name": {
        "summary": "Get user by name",
        "description": "Resolves a player by BattleTag (name containing '#', dashes normalized) or by Discord name with optional entity expansion (public).",
    },
    "rpc.app.users.tournaments": {
        "summary": "User tournaments",
        "description": "Returns the tournaments a player participated in, scoped to the workspace context and grid (public).",
    },
    "rpc.app.users.tournament": {
        "summary": "User tournament stats",
        "description": "Returns a player's participation and stats for one tournament, resolved against that tournament's division grid (public).",
    },
    "rpc.app.users.maps": {
        "summary": "User maps",
        "description": "Returns a player's paginated, sortable per-map record (win/loss/draw/winrate), optionally workspace-scoped (public).",
    },
    "rpc.app.users.maps_summary": {
        "summary": "User maps summary",
        "description": "Returns aggregate totals for a player's per-map record, optionally workspace-scoped (public).",
    },
    "rpc.app.users.encounters": {
        "summary": "User encounters",
        "description": "Returns a player's paginated encounters filterable by result, stage, MVP, log availability, and opponent (public).",
    },
    "rpc.app.users.matches_summary": {
        "summary": "User matches summary",
        "description": "Returns aggregate match totals for a player, optionally workspace-scoped (public).",
    },
    "rpc.app.users.heroes": {
        "summary": "User heroes",
        "description": "Returns a player's paginated per-hero stats for the requested stat names, optionally scoped to a tournament and workspace; rejects invalid stat values with 422 (public).",
    },
    "rpc.app.users.teammates": {
        "summary": "User best teammates",
        "description": "Returns a player's paginated, sortable best teammates by winrate and shared tournaments, optionally workspace-scoped (public).",
    },
    # ── achievements (bespoke) ─────────────────────────────────────────────────────
    "rpc.app.achievements.user": {
        "summary": "User achievements",
        "description": "Returns a player's earned (and optionally locked) achievements, scoped by tournament or without-tournament and workspace; rejects combining tournament_id with without_tournament=true (public).",
    },
    "rpc.app.achievements.users": {
        "summary": "Achievement earners",
        "description": "Returns a paginated list of players who earned a given achievement (public).",
    },
    # ── workspaces (reads + writes + members) ──────────────────────────────────────
    "rpc.app.workspaces.list": {
        "summary": "List workspaces",
        "description": "Returns all workspaces (public, unpaginated).",
    },
    "rpc.app.workspaces.get": {
        "summary": "Get workspace",
        "description": "Returns a single workspace by id (public), 404 if not found.",
    },
    "rpc.app.workspaces.create": {
        "summary": "Create workspace",
        "description": "Creates a workspace (superuser only), provisions system roles, adds the creator as owner, and busts the RBAC cache; 400 on duplicate slug.",
    },
    "rpc.app.admin.update#workspace": {
        "summary": "Update workspace",
        "description": "Updates a workspace via the shared CRUD engine with workspace-scoped 'workspace.update' permission, 404 if not found.",
    },
    "rpc.app.admin.delete#workspace": {
        "summary": "Delete workspace",
        "description": "Deletes a workspace via the shared CRUD engine with workspace-scoped 'workspace.delete' permission; returns 204, 404 if not found.",
    },
    "rpc.app.workspaces.members_list": {
        "summary": "List workspace members",
        "description": "Paginated, searchable (username/email) list of a workspace's auth-linked members enriched with auth-user info and RBAC roles; requires workspace_member.read, 404 if workspace missing.",
    },
    "rpc.app.workspaces.members_autofill_roles": {
        "summary": "Autofill member roles",
        "description": "Grants the baseline 'member' role to every auth-linked member of the workspace that currently has no role; idempotent. Requires workspace_member.update, returns the count assigned.",
    },
    "rpc.app.workspaces.member_add": {
        "summary": "Add workspace member",
        "description": "Adds an auth user to a workspace with resolved role ids and busts the member's RBAC cache; requires workspace_member.create, 400 if already a member.",
    },
    "rpc.app.workspaces.member_update": {
        "summary": "Update workspace member",
        "description": "Updates a member's workspace roles and busts their RBAC cache; requires workspace_member.update, 404 if member missing.",
    },
    "rpc.app.workspaces.member_remove": {
        "summary": "Remove workspace member",
        "description": "Removes a member from a workspace and busts their RBAC cache; requires workspace_member.delete, refuses to remove the last owner, returns 204.",
    },
    # ── workspace icon (binary) ────────────────────────────────────────────────────
    "rpc.app.workspaces.icon_upload": {
        "summary": "Upload workspace icon",
        "description": "Uploads a workspace icon to S3 and stores its URL; requires workspace.update, 404 if workspace missing.",
    },
    "rpc.app.workspaces.icon_delete": {
        "summary": "Delete workspace icon",
        "description": "Removes a workspace's icon from S3 and clears its URL; requires workspace.update, 404 if workspace missing.",
    },
    # ── assets (binary, superuser) ───────────────────────────────────────────────────
    "rpc.app.assets.upload": {
        "summary": "Upload asset",
        "description": "Uploads an achievements/divisions asset to S3 (superuser only), optionally workspace-scoped, returning its key and public URL; 422 on invalid asset_type.",
    },
    "rpc.app.assets.delete": {
        "summary": "Delete asset",
        "description": "Deletes an achievements/divisions asset from S3 by slug prefix (superuser only); 422 on invalid asset_type, 404 if nothing deleted.",
    },
    # ── match log (binary download) ──────────────────────────────────────────────────
    "rpc.app.matches.log": {
        "summary": "Download match log",
        "description": "Returns the raw match-log file bytes for a match (base64 from the worker, decoded by the gateway); 404 if the match or log is missing.",
    },
    # ── metadata admin: heroes ─────────────────────────────────────────────────────────
    "rpc.app.heroes.admin_list": {
        "summary": "Admin list heroes",
        "description": "Returns a paginated admin list of heroes; requires the global hero.read permission.",
    },
    "rpc.app.heroes.admin_create": {
        "summary": "Create hero",
        "description": "Creates a hero; requires the global hero.create permission.",
    },
    "rpc.app.heroes.admin_update": {
        "summary": "Update hero",
        "description": "Updates a hero by id; requires the global hero.update permission.",
    },
    "rpc.app.heroes.admin_delete": {
        "summary": "Delete hero",
        "description": "Deletes a hero by id; requires the global hero.delete permission, returns 204.",
    },
    # ── metadata admin: maps ────────────────────────────────────────────────────────────
    "rpc.app.maps.admin_list": {
        "summary": "Admin list maps",
        "description": "Returns a paginated admin list of maps; requires the global map.read permission.",
    },
    "rpc.app.maps.admin_create": {
        "summary": "Create map",
        "description": "Creates a map; requires the global map.create permission.",
    },
    "rpc.app.maps.admin_update": {
        "summary": "Update map",
        "description": "Updates a map by id; requires the global map.update permission.",
    },
    "rpc.app.maps.admin_delete": {
        "summary": "Delete map",
        "description": "Deletes a map by id; requires the global map.delete permission, returns 204.",
    },
    # ── metadata admin: gamemodes ─────────────────────────────────────────────────────────
    "rpc.app.gamemodes.admin_list": {
        "summary": "Admin list gamemodes",
        "description": "Returns a paginated admin list of gamemodes; requires the global gamemode.read permission.",
    },
    "rpc.app.gamemodes.admin_create": {
        "summary": "Create gamemode",
        "description": "Creates a gamemode; requires the global gamemode.create permission.",
    },
    "rpc.app.gamemodes.admin_update": {
        "summary": "Update gamemode",
        "description": "Updates a gamemode by id; requires the global gamemode.update permission.",
    },
    "rpc.app.gamemodes.admin_delete": {
        "summary": "Delete gamemode",
        "description": "Deletes a gamemode by id; requires the global gamemode.delete permission, returns 204.",
    },
    # ── users admin (CRUD) ───────────────────────────────────────────────────────────────
    "rpc.app.users.admin_list": {
        "summary": "Admin list users",
        "description": "Returns a paginated admin list of users; requires the global user.read permission.",
    },
    "rpc.app.users.admin_create": {
        "summary": "Create user",
        "description": "Creates a player and returns it with discord/battle_tag/twitch identities; requires the global user.create permission.",
    },
    "rpc.app.users.admin_update": {
        "summary": "Update user",
        "description": "Updates a player by id and returns it with its identities; requires the global user.update permission.",
    },
    "rpc.app.users.admin_delete": {
        "summary": "Delete user",
        "description": "Deletes a player by id; requires the global user.delete permission, returns 204.",
    },
    # ── user profile merge (superuser) ─────────────────────────────────────────────────────
    "rpc.app.users.merge_preview": {
        "summary": "Preview user merge",
        "description": "Previews merging one player profile into another without applying changes (superuser only).",
    },
    "rpc.app.users.merge_execute": {
        "summary": "Execute user merge",
        "description": "Merges one player profile into another, stamping the operator's auth-user id (superuser only).",
    },
    # ── user identities: discord ───────────────────────────────────────────────────────────
    "rpc.app.users.discord_add": {
        "summary": "Add Discord identity",
        "description": "Adds a Discord identity to a player; requires the global user.update permission.",
    },
    "rpc.app.users.discord_update": {
        "summary": "Update Discord identity",
        "description": "Updates a player's Discord identity by identity id; requires the global user.update permission.",
    },
    "rpc.app.users.discord_delete": {
        "summary": "Delete Discord identity",
        "description": "Removes a player's Discord identity by identity id; requires the global user.delete permission, returns 204.",
    },
    # ── user identities: battletag ────────────────────────────────────────────────────────────
    "rpc.app.users.battletag_add": {
        "summary": "Add BattleTag identity",
        "description": "Adds a BattleTag identity to a player; requires the global user.update permission.",
    },
    "rpc.app.users.battletag_update": {
        "summary": "Update BattleTag identity",
        "description": "Updates a player's BattleTag identity by identity id; requires the global user.update permission.",
    },
    "rpc.app.users.battletag_delete": {
        "summary": "Delete BattleTag identity",
        "description": "Removes a player's BattleTag identity by identity id; requires the global user.delete permission, returns 204.",
    },
    # ── user identities: twitch ────────────────────────────────────────────────────────────────
    "rpc.app.users.twitch_add": {
        "summary": "Add Twitch identity",
        "description": "Adds a Twitch identity to a player; requires the global user.update permission.",
    },
    "rpc.app.users.twitch_update": {
        "summary": "Update Twitch identity",
        "description": "Updates a player's Twitch identity by identity id; requires the global user.update permission.",
    },
    "rpc.app.users.twitch_delete": {
        "summary": "Delete Twitch identity",
        "description": "Removes a player's Twitch identity by identity id; requires the global user.delete permission, returns 204.",
    },
    # ── user avatar (binary upload + delete) ────────────────────────────────────────────────────────
    "rpc.app.users.avatar_upload": {
        "summary": "Upload user avatar",
        "description": "Uploads a player's avatar to S3 and stores its URL; requires the global user.update permission.",
    },
    "rpc.app.users.avatar_delete": {
        "summary": "Delete user avatar",
        "description": "Removes a player's avatar from S3 and clears its URL; requires the global user.update permission.",
    },
    # ── user bulk import (binary CSV / Google Sheets) ──────────────────────────────────────────────────
    "rpc.app.users.csv_import": {
        "summary": "Bulk import users",
        "description": "Bulk-creates players from an uploaded CSV file or a Google Sheets URL using the given row/delimiter/flag params; requires the global admin role.",
    },
}
