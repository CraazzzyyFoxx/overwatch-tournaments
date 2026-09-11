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
    "rpc.app.statistics.tournament_readiness": {
        "summary": "Tournament readiness checklist",
        "description": (
            "Returns the living readiness checklist for one tournament, telling its organisers what is"
            " still missing before it can run: schedule/grid/stage-slot configuration, bracket and"
            " encounter log coverage, and the registration, pool, balance and draft state. Requires an"
            " active user with tournament.read or team.read on the tournament's own workspace, and each"
            " group of fields is masked to null when the caller lacks the permission that gates it, so"
            " a partial reader sees no-access rather than zeros. 403 without either permission, 404 if"
            " the tournament is unknown; hidden tournaments of the caller's own workspace are visible."
        ),
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
    "rpc.app.users.tournament_encounters": {
        "summary": "User tournament encounters",
        "description": "Returns a player's encounters (with per-match stats) within one tournament — the lazy detail behind the Tournaments-tab dossier, fetched only for the tournament currently open in the UI (public).",
    },
    "rpc.app.users.tournament_leaderboard": {
        "summary": "Tournament stat leaderboard",
        "description": "Returns every player in a tournament ranked by a single stat — the full ranked list behind a user's per-stat rank/total on the tournament-stats page. Inverse stats like Deaths rank ascending. The `stat` must be one of the ranked tournament stats (public).",
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
        "description": (
            "Lists workspaces (public, optional auth, unpaginated). `scope=public` (the default) is the"
            " home-page directory and is byte-identical for every caller, superusers included: hidden"
            " and `unverified` workspaces never appear. `scope=admin` is the management list -- every"
            " workspace for a superuser, otherwise only the caller's own memberships at any tier."
            " `scope=all` is that unioned with the public directory (the workspace switcher). Any other"
            " value is a 422."
        ),
    },
    "rpc.app.workspaces.by_host": {
        "summary": "Resolve workspace by host",
        "description": (
            "Resolves a request host to its workspace ({workspace_id, slug}) -- the entry point to"
            " multitenancy, called by the edge before anything else knows which tenant it is serving."
            " A host in the platform zone matches on subdomain; any other host matches only a VERIFIED"
            " custom domain. Public, and fail-closed: a missing, malformed, unknown or"
            " not-yet-verified host returns null data rather than an error."
        ),
    },
    "rpc.app.workspaces.get": {
        "summary": "Get workspace",
        "description": "Returns a single workspace by id (public), 404 if not found.",
    },
    "rpc.app.workspaces.create": {
        "summary": "Create workspace",
        "description": "Creates a workspace, provisions system roles, stamps and adds the creator as owner, and busts the RBAC cache. Open to any ACTIVE authenticated user holding the allow-by-default `workspace.self_create` capability — deny that permission for an account (negative RBAC, global scope) to revoke self-service creation from it (403). Then capped per account by `workspace_creation.max_owned_per_user`, counted over `Workspace.owner_id` (403 `workspace_create_limit_reached`); platform slugs are unclaimable (400 `slug_reserved`), 400 on a duplicate slug, and the new workspace is born `unverified`.",
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
    # ── workspace custom domain (white-label Phase 2) ───────────────────────────────
    "rpc.app.workspaces.set_custom_domain": {
        "summary": "Set workspace custom domain",
        "description": "Normalizes and stores a custom domain plus a fresh DNS TXT verification token, resetting verification; requires workspace.update, 404 if workspace missing, 400 on an invalid domain.",
    },
    "rpc.app.workspaces.verify_custom_domain": {
        "summary": "Verify workspace custom domain",
        "description": "Checks the `_owt-verify.<domain>` DNS TXT record against the stored token and stamps verified_at on a match; requires workspace.update, 404 if workspace missing, 400 if no domain is set or the record doesn't match yet.",
    },
    "rpc.app.workspaces.clear_custom_domain": {
        "summary": "Clear workspace custom domain",
        "description": "Removes the custom domain, its verification token, and verified_at; requires workspace.update, 404 if workspace missing.",
    },
    "rpc.app.workspaces.discord_guild_verify": {
        "summary": "Verify and bind a Discord guild",
        "description": "Proves the caller administers the given Discord guild (via identity-service, owner or MANAGE_GUILD) and binds it to the workspace, stamping verified_at/verified_by; requires workspace.update, 404 if workspace missing, 403 if the caller does not administer the guild, 409 if another workspace already claims it, 503 if identity-service is unreachable.",
    },
    "rpc.app.workspaces.discord_guild_clear": {
        "summary": "Unbind a Discord guild",
        "description": "Clears the workspace's Discord guild claim (guild id, verified_at, verified_by). Requires workspace.update, not Discord administration -- so an organiser can leave a server they were kicked from. 404 if workspace missing. Idempotent when nothing is bound.",
    },
    "rpc.app.workspaces.my_discord_guilds": {
        "summary": "List my administered Discord guilds",
        "description": "Returns the Discord guilds the caller owns or can manage (via identity-service, the `guilds` OAuth scope), for picking one to verify; requires an active authenticated user, 503 if identity-service is unreachable.",
    },
    "rpc.app.workspaces.verification_set": {
        "summary": "Set workspace verification status",
        "description": "Moves a workspace between the `unverified`/`verified`/`trusted` trust tiers — the only way a self-service workspace is unblocked for GPU compute, inline achievement recompute and the public directory; superuser-only (a workspace owner may not self-certify), audited on every call including a no-op set, 404 if workspace missing, 422 on an unknown status.",
    },
    "rpc.app.workspaces.owner_get": {
        "summary": "Get the workspace owner",
        "description": "Resolves `Workspace.owner_id` — the account accountable for the workspace and counted against the per-account create cap — to its username, email and avatar; requires workspace.update (the public workspace model deliberately publishes no owner), returns null data when no owner is stamped, 404 if workspace missing.",
    },
    "rpc.app.workspaces.owner_set": {
        "summary": "Assign or clear the workspace owner",
        "description": "Stamps `Workspace.owner_id` with the given auth account, or clears it when `auth_user_id` is null, and returns the resolved owner. Superuser-only — stricter than the `workspace.update` gate on the matching read, because owner_id is what the per-account create cap is counted over. RBAC roles are untouched (the stamp and the `owner` role are decoupled), the per-account cap is not re-checked (a superuser assignment is the override for it), every call is audited including a no-op, 404 if the workspace or the target account is missing.",
    },
    "rpc.app.workspaces.owner_transfer": {
        "summary": "Transfer workspace ownership",
        "description": "Hands the workspace over: stamps `Workspace.owner_id` with the recipient AND moves the RBAC `owner` role to them, adding them to the workspace if they are not a member yet. Open to the workspace's current owner as well as superusers — `workspace.update` alone is not enough, a co-administrator may not give away a workspace they do not answer for. The outgoing owner keeps their membership and every other role (`member` steps in if `owner` was their only one); the recipient is granted `owner` before the outgoing owner loses it, so the workspace is never ownerless. The recipient's `max_owned_per_user` cap is enforced unless the actor is a superuser (403 `workspace_owner_limit_reached`), because create-then-transfer would otherwise loop past it. Audited, busts both accounts' RBAC cache, 404 if the workspace or the recipient is missing, 403 for anyone but the owner or a superuser.",
    },
    # ── workspace discord entities ──────────────────────────────────────────────────
    "rpc.app.workspaces.discord_roles": {
        "summary": "List workspace Discord roles",
        "description": "Returns roles of the workspace's linked Discord server with names, colors, and positions from discord.py cache.",
    },
    "rpc.app.workspaces.discord_channels": {
        "summary": "List workspace Discord channels",
        "description": "Returns text channels of the workspace's linked Discord server with names and categories.",
    },
    "rpc.app.workspaces.discord_guild": {
        "summary": "Workspace Discord server status",
        "description": "Returns connection status, server name, icon URL, member count, and Discord owner of the workspace's linked Discord server.",
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
        "description": "Returns a paginated admin list of heroes (superuser only).",
    },
    "rpc.app.heroes.admin_create": {
        "summary": "Create hero",
        "description": "Creates a hero (superuser only).",
    },
    "rpc.app.heroes.admin_update": {
        "summary": "Update hero",
        "description": "Updates a hero by id (superuser only).",
    },
    "rpc.app.heroes.admin_delete": {
        "summary": "Delete hero",
        "description": "Deletes a hero by id (superuser only), returns 204.",
    },
    # ── metadata admin: maps ────────────────────────────────────────────────────────────
    "rpc.app.maps.admin_list": {
        "summary": "Admin list maps",
        "description": "Returns a paginated admin list of maps (superuser only).",
    },
    "rpc.app.maps.admin_create": {
        "summary": "Create map",
        "description": "Creates a map (superuser only).",
    },
    "rpc.app.maps.admin_update": {
        "summary": "Update map",
        "description": "Updates a map by id (superuser only).",
    },
    "rpc.app.maps.admin_delete": {
        "summary": "Delete map",
        "description": "Deletes a map by id (superuser only), returns 204.",
    },
    # ── metadata admin: gamemodes ─────────────────────────────────────────────────────────
    "rpc.app.gamemodes.admin_list": {
        "summary": "Admin list gamemodes",
        "description": "Returns a paginated admin list of gamemodes (superuser only).",
    },
    "rpc.app.gamemodes.admin_create": {
        "summary": "Create gamemode",
        "description": "Creates a gamemode (superuser only).",
    },
    "rpc.app.gamemodes.admin_update": {
        "summary": "Update gamemode",
        "description": "Updates a gamemode by id (superuser only).",
    },
    "rpc.app.gamemodes.admin_delete": {
        "summary": "Delete gamemode",
        "description": "Deletes a gamemode by id (superuser only), returns 204.",
    },
    # ── metadata admin: catalog alias-miss queue ──────────────────────────────────────────
    "rpc.app.catalog_aliases.misses_list": {
        "summary": "List catalog alias misses",
        "description": "Returns a paginated queue of hero/map/gamemode names from match logs that no alias resolved, ordered by occurrences then recency; open misses only unless include_resolved=true (superuser only).",
    },
    "rpc.app.catalog_aliases.attach": {
        "summary": "Attach a catalog alias",
        "description": "Adds the raw name to the target entity's aliases and closes the matching miss in one transaction; 404 if the entity is missing (superuser only).",
    },
    "rpc.app.catalog_aliases.dismiss": {
        "summary": "Dismiss a catalog alias miss",
        "description": "Marks an alias miss resolved without attaching it; the row reopens if the same name reappears in a log. 404 if the miss is missing (superuser only).",
    },
    # ── platform audit log ────────────────────────────────────────────────────────────────
    "rpc.app.audit_list": {
        "summary": "List audit log entries",
        "description": (
            "Returns a paginated slice of the platform audit log, newest first (created_at then id, both "
            "descending). workspace_id is required for everyone but a superuser and is enforced as a hard "
            "scope: entity_type/entity_id and actor_user_id narrow within it and never reach a row outside "
            "it. A superuser may omit workspace_id to see every workspace plus the platform-level rows that "
            "belong to none. Requires audit.read in the requested workspace."
        ),
    },
    # ── users admin (CRUD) ───────────────────────────────────────────────────────────────
    "rpc.app.users.admin_list": {
        "summary": "Admin list users",
        "description": "Returns a paginated admin list of players. Requires user.read: globally for the platform-wide registry, or in the workspace named by workspace_id, in which case the page is filtered to that workspace's roster.",
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
    # ── user self-service (own player, capability account.social) ───────────────────────────────────
    "rpc.app.users.me_social_list": {
        "summary": "List my social accounts",
        "description": (
            "Returns the caller's own player with its linked social accounts -- which handles are"
            " connected, which one is primary, and each account's public-profile visibility. Accounts"
            " are added through the identity-service OAuth link flow, never here. Requires the"
            " account.social capability; a caller with no linked player gets an empty list rather than"
            " a 404."
        ),
    },
    "rpc.app.users.me_social_set_primary": {
        "summary": "Set my primary social account",
        "description": (
            "Promotes one of the caller's own social accounts to primary -- the handle shown first on"
            " their public profile -- and returns the updated player. OAuth-verified accounts only"
            " (400 otherwise), because an unverified handle as primary would put an unproven identity"
            " on a public profile. Requires the account.social capability and a linked player; 404 for"
            " an account id the caller does not own."
        ),
    },
    "rpc.app.users.me_social_set_visibility": {
        "summary": "Set my social account visibility",
        "description": (
            "Sets whether one of the caller's own social accounts is shown to anyone on their public"
            " profile, and returns the updated player. Global scope only: this is the self-service"
            " hide switch, not the per-workspace admin override, and hiding never deletes the account"
            " or its OAuth link. Requires the account.social capability and a linked player; 404 for an"
            " account id the caller does not own."
        ),
    },
    "rpc.app.users.me_set_stream_visibility": {
        "summary": "Set my stream visibility",
        "description": (
            "Sets whether the caller's own live stream may be surfaced on tournament pages and returns"
            " their updated player. A false value is a veto: it outranks the per-tournament stream-POV"
            " opt-in and the Twitch account's public visibility, and takes effect immediately rather"
            " than at the next poll tick. Independent of social-account visibility, so the handle stays"
            " on the public profile. Requires a linked player (404 otherwise) and the account.social"
            " capability."
        ),
    },
    # ── favorite players (own account, no account.social capability needed) ─────────────────────────
    "rpc.app.users.me_favorites_list": {
        "summary": "List my favorite players",
        "description": (
            "Returns the caller's own favorited players (id + name), newest favorite first. Scoped to"
            " the caller's auth account, not a linked player, so it works even without one."
        ),
    },
    "rpc.app.users.me_favorite_add": {
        "summary": "Favorite a player",
        "description": (
            "Bookmarks a player for the caller's own account. Idempotent (favoriting an"
            " already-favorited player is a no-op), 404s if the player id does not exist."
        ),
    },
    "rpc.app.users.me_favorite_remove": {
        "summary": "Unfavorite a player",
        "description": (
            "Removes a player from the caller's own favorites, returns 204. Idempotent (unfavoriting a"
            " player that isn't favorited is a no-op, not an error)."
        ),
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
    # ── notification inbox + announcement banner ────────────────────────────────────────────────────
    "rpc.app.notifications_list": {
        "summary": "List the caller's notifications",
        "description": (
            "Returns one page of the caller's inbox newest first, plus the unread badge count and an"
            " opaque next_cursor (null on the last page). The audience is computed from the"
            " authenticated identity alone — personal rows, rows for the workspaces the caller belongs"
            " to, and platform-wide announcements — so there is no recipient parameter to pass. Expired"
            " and not-yet-published rows are excluded. System kinds carry no text: the row is kind +"
            " payload snapshot and the client renders it. 422 on a malformed cursor."
        ),
    },
    "rpc.app.notifications_mark_read": {
        "summary": "Mark notifications read",
        "description": (
            "Inserts read marks for the given ids and returns how many actually landed together with the"
            " refreshed unread count. An omitted or null `ids` marks the whole visible inbox (the"
            ' "mark all read" button). Ids outside the caller\'s audience are dropped silently rather'
            " than rejected, so the endpoint cannot be used to probe whether another user's"
            " notification exists; a repeat call marks nothing and is not an error."
        ),
    },
    "rpc.app.notifications_delete": {
        "summary": "Delete notifications from the caller's inbox",
        "description": (
            "Removes rows from this caller's inbox and returns how many left it together with the"
            " refreshed unread count. An omitted or null `ids` targets the whole visible inbox, and"
            ' `only_read: true` narrows that to rows already marked read (the "clear read" button).'
            " The deletion is per viewer: the underlying row survives, so one reader dismissing a"
            " platform-wide announcement does not take it out of anybody else's inbox. Ids outside the"
            " caller's audience are dropped silently rather than rejected, and a repeat call deletes"
            " nothing and is not an error."
        ),
    },
    # ── notifications admin (workspace-scoped operator screen) ──────────────────────────────────────
    "rpc.app.notification_admin_list": {
        "summary": "List the notifications a workspace produced",
        "description": (
            "Returns one keyset page of the notifications this workspace's own activity produced"
            " (`source_workspace_id`), newest first, expired ones included — the operator view exists to"
            " show what has already been retired, which the inbox's time window hides. Requires"
            " notification.read in the workspace named by `workspace_id`; announcements are not listed"
            " here, they have their own CRUD. 422 on an unknown `kind` or a malformed cursor."
        ),
    },
    "rpc.app.notification_admin_retire": {
        "summary": "Retire notifications a workspace produced",
        "description": (
            "Expires the selected rows as of now — taking them out of every recipient's inbox and badge"
            " count — and audits the batch once. `ids` and `kind` are filters over the same scoped"
            " statement and may be combined; naming neither is a 422 rather than a tenant-wide wipe."
            " Requires notification.delete in `workspace_id`. The rows and their read marks are kept,"
            " like an announcement retire; already-expired rows are skipped, so a repeat call answers 0."
        ),
    },
    "rpc.app.active_announcements": {
        "summary": "Active announcements for the banner",
        "description": (
            "Returns the currently-published platform-wide announcements for the site banner, newest"
            " first. Anonymous callers are welcome and get every global announcement inside its"
            " publish/expiry window; for an authenticated viewer the ones already dismissed are"
            " filtered out, which is why the route forwards identity when it is present."
        ),
    },
    # ── announcements admin (operator CRUD) ─────────────────────────────────────────────────────────
    "rpc.app.announcement_list": {
        "summary": "List announcements",
        "description": (
            "Returns one scope's announcements newest first, expired ones included — the operator view"
            " exists to show what is scheduled and what has been retired, which the banner's time window"
            " hides. `workspace_id` selects the workspace feed and requires announcement.read there;"
            " omitting it selects the platform-wide feed and is superuser-only, so the list can never"
            " read announcements the caller could not publish."
        ),
    },
    "rpc.app.announcement_create": {
        "summary": "Publish an announcement",
        "description": (
            "Publishes an announcement and audits it. A `workspace` one requires announcement.create in"
            " that workspace and at least one locale plus a default_locale among the filled ones; a"
            " `global` one renders to every visitor including anonymous ones and is therefore"
            " superuser-only and requires every supported locale (ru and en) — a workspace grant cannot"
            " reach the platform's voice. `user` is not an accepted audience: personal notifications are"
            " written by the flows that cause them, from server-resolved recipients. 422 on a locale or"
            " audience/workspace_id mismatch."
        ),
    },
    "rpc.app.announcement_update": {
        "summary": "Edit an announcement",
        "description": (
            "Partially edits the text and expiry of an already-published announcement and audits it."
            " `locales` replaces the whole map when present; audience and workspace_id are immutable,"
            " and the required principal is decided from the stored audience, never from the request."
            " Read marks are deliberately left alone — clearing them would re-show a banner to everyone"
            " who already dismissed it, for a corrected typo. 404 if the id is not an announcement."
        ),
    },
    "rpc.app.announcement_delete": {
        "summary": "Retire an announcement",
        "description": (
            "Expires the announcement as of now and audits it, answering 204. The row is kept rather"
            " than deleted: it is a notification row that people already have in their inbox, and the"
            " read marks pointing at it must stay meaningful. Authorized from the stored audience like"
            " the edit; 404 if the id is not an announcement."
        ),
    },
}
