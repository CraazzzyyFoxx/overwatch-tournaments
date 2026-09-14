"""Human-readable docs (summary + description) for app-service RPC subjects,
merged into the gateway's OpenAPI by the export script. Keyed by RPC subject
(generic-CRUD keys use "<subject>#<entity>"). Prose only.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    # ── generic CRUD read engine (rpc.app.read.{get,list}#<entity>) ────────────
    "rpc.app.read.get#hero": {
        "summary": "Get hero",
        "description": "Permission: public; no authentication required. Returns a single hero by id via the shared CRUD read engine, 404 if not found.",
    },
    "rpc.app.read.list#hero": {
        "summary": "List heroes",
        "description": "Permission: public; no authentication required. Returns a paginated, sortable, name/slug-searchable list of heroes via the shared CRUD read engine.",
    },
    "rpc.app.read.get#map": {
        "summary": "Get map",
        "description": "Permission: public; no authentication required. Returns a single map by id with optional entity expansion via the shared CRUD read engine, 404 if not found.",
    },
    "rpc.app.read.list#map": {
        "summary": "List maps",
        "description": "Permission: public; no authentication required. Returns a paginated, sortable, name-searchable list of maps via the shared CRUD read engine.",
    },
    "rpc.app.read.get#gamemode": {
        "summary": "Get gamemode",
        "description": "Permission: public; no authentication required. Returns a single gamemode by id with optional entity expansion via the shared CRUD read engine, 404 if not found.",
    },
    "rpc.app.read.list#gamemode": {
        "summary": "List gamemodes",
        "description": "Permission: public; no authentication required. Returns a paginated, sortable, name/slug-searchable list of gamemodes via the shared CRUD read engine.",
    },
    "rpc.app.read.get#achievement": {
        "summary": "Get achievement",
        "description": "Permission: public; no authentication required. Returns a single achievement rule by id with optional entity expansion via the shared CRUD read engine, 404 if not found.",
    },
    "rpc.app.read.list#achievement": {
        "summary": "List achievements",
        "description": "Permission: public; no authentication required. Returns a paginated, sortable list of achievements optionally filtered by workspace via the shared CRUD read engine.",
    },
    # ── lookups ────────────────────────────────────────────────────────────────
    "rpc.app.heroes.lookup": {
        "summary": "Hero lookup",
        "description": "Permission: public; no authentication required. Returns all heroes as id/name lookup items ordered by name (no pagination).",
    },
    "rpc.app.maps.lookup": {
        "summary": "Map lookup",
        "description": "Permission: public; no authentication required. Returns all maps as id/name lookup items ordered by name (no pagination).",
    },
    "rpc.app.gamemodes.lookup": {
        "summary": "Gamemode lookup",
        "description": "Permission: public; no authentication required. Returns all gamemodes as id/name lookup items ordered by name (no pagination).",
    },
    # ── heroes (bespoke) ─────────────────────────────────────────────────────────
    "rpc.app.heroes.playtime": {
        "summary": "Hero playtime stats",
        "description": "Permission: public; no authentication required, though a hidden tournament 404s unless the optional identity may view it. Returns paginated aggregated hero-playtime statistics, optionally scoped to a workspace.",
    },
    "rpc.app.heroes.leaderboard": {
        "summary": "Hero leaderboard",
        "description": "Permission: public; no authentication required, though a hidden tournament 404s unless the optional identity may view it. Returns a paginated per-hero player leaderboard resolved against the workspace context and its division grid.",
    },
    # ── statistics ───────────────────────────────────────────────────────────────
    "rpc.app.statistics.dashboard": {
        "summary": "Dashboard stats",
        "description": "Permission: public; no authentication required. Returns aggregate dashboard statistics for the optional workspace.",
    },
    "rpc.app.statistics.champion": {
        "summary": "Most-champion players",
        "description": "Permission: public; no authentication required. Returns paginated, sortable players ranked by tournaments won, optionally workspace-scoped.",
    },
    "rpc.app.statistics.winrate": {
        "summary": "Top winrate players",
        "description": "Permission: public; no authentication required. Returns paginated, sortable players ranked by win rate, optionally workspace-scoped.",
    },
    "rpc.app.statistics.won_maps": {
        "summary": "Top won-maps players",
        "description": "Permission: public; no authentication required. Returns paginated, sortable players ranked by maps won, optionally workspace-scoped.",
    },
    "rpc.app.statistics.tournament_readiness": {
        "summary": "Tournament readiness checklist",
        "description": (
            "Permission: workspace `tournament.read` or `team.read` on the tournament's own workspace. Returns the"
            " living readiness checklist for one tournament, telling its organisers what is still missing before it can"
            " run: schedule/grid/stage-slot configuration, bracket and encounter log coverage, and the registration,"
            " pool, balance and draft state. Each group of fields is masked to null when the caller lacks the permission"
            " that gates it, so a partial reader sees no-access rather than zeros. 403 without either permission, 404 if"
            " the tournament is unknown; hidden tournaments of the caller's own workspace are visible."
        ),
    },
    # ── users (bespoke reads) ──────────────────────────────────────────────────────
    "rpc.app.users.list": {
        "summary": "List users",
        "description": "Permission: public; no authentication required. Returns a paginated, sortable, name-searchable list of players.",
    },
    "rpc.app.users.get_profile": {
        "summary": "User profile",
        "description": "Permission: public; no authentication required. Returns a player's full profile resolved against the workspace context and division grid.",
    },
    "rpc.app.users.search": {
        "summary": "Search users",
        "description": "Permission: public; no authentication required. Returns players matching a free-text query across the requested identity fields.",
    },
    "rpc.app.users.overview": {
        "summary": "Users overview",
        "description": "Permission: public; no authentication required. Returns a paginated, workspace-normalized player overview table built from the workspace grid.",
    },
    "rpc.app.users.overview_stats": {
        "summary": "Users overview stats",
        "description": "Permission: public; no authentication required. Returns aggregate statistics for the players-overview table computed against the workspace grid.",
    },
    "rpc.app.users.overview_catalog": {
        "summary": "Users overview catalog",
        "description": "Permission: public; no authentication required. Returns the filter-catalog (facets) for the players-overview table from the workspace grid.",
    },
    "rpc.app.users.compare": {
        "summary": "Compare users",
        "description": "Permission: public; no authentication required, though a hidden tournament 404s unless the optional identity may view it. Returns a head-to-head comparison between the given user and others, resolved against the default division grid.",
    },
    "rpc.app.users.compare_heroes": {
        "summary": "Compare user heroes",
        "description": "Permission: public; no authentication required, though a hidden tournament 404s unless the optional identity may view it. Returns a per-hero head-to-head comparison for the given user against others using the default grid.",
    },
    "rpc.app.users.by_name": {
        "summary": "Get user by name",
        "description": "Permission: public; no authentication required. Resolves a player by BattleTag (name containing '#', dashes normalized) or by Discord name with optional entity expansion.",
    },
    "rpc.app.users.tournaments": {
        "summary": "User tournaments",
        "description": "Permission: public; no authentication required. Returns the tournaments a player participated in, scoped to the workspace context and grid.",
    },
    "rpc.app.users.tournament": {
        "summary": "User tournament stats",
        "description": "Permission: public; no authentication required, though a hidden tournament 404s unless the optional identity may view it. Returns a player's participation and stats for one tournament, resolved against that tournament's division grid.",
    },
    "rpc.app.users.tournament_encounters": {
        "summary": "User tournament encounters",
        "description": "Permission: public; no authentication required, though a hidden tournament 404s unless the optional identity may view it. Returns a player's encounters (with per-match stats) within one tournament — the lazy detail behind the Tournaments-tab dossier, fetched only for the tournament currently open in the UI.",
    },
    "rpc.app.users.tournament_leaderboard": {
        "summary": "Tournament stat leaderboard",
        "description": "Permission: public; no authentication required, though a hidden tournament 404s unless the optional identity may view it. Returns every player in a tournament ranked by a single stat — the full ranked list behind a user's per-stat rank/total on the tournament-stats page. Inverse stats like Deaths rank ascending. The `stat` must be one of the ranked tournament stats.",
    },
    "rpc.app.users.maps": {
        "summary": "User maps",
        "description": "Permission: public; no authentication required, though a hidden tournament 404s unless the optional identity may view it. Returns a player's paginated, sortable per-map record (win/loss/draw/winrate), optionally workspace-scoped.",
    },
    "rpc.app.users.maps_summary": {
        "summary": "User maps summary",
        "description": "Permission: public; no authentication required, though a hidden tournament 404s unless the optional identity may view it. Returns aggregate totals for a player's per-map record, optionally workspace-scoped.",
    },
    "rpc.app.users.encounters": {
        "summary": "User encounters",
        "description": "Permission: public; no authentication required. Returns a player's paginated encounters filterable by result, stage, MVP, log availability, and opponent.",
    },
    "rpc.app.users.matches_summary": {
        "summary": "User matches summary",
        "description": "Permission: public; no authentication required. Returns aggregate match totals for a player, optionally workspace-scoped.",
    },
    "rpc.app.users.heroes": {
        "summary": "User heroes",
        "description": "Permission: public; no authentication required, though a hidden tournament 404s unless the optional identity may view it. Returns a player's paginated per-hero stats for the requested stat names, optionally scoped to a tournament and workspace; rejects invalid stat values with 422.",
    },
    "rpc.app.users.teammates": {
        "summary": "User best teammates",
        "description": "Permission: public; no authentication required. Returns a player's paginated, sortable best teammates by winrate and shared tournaments, optionally workspace-scoped.",
    },
    # ── achievements (bespoke) ─────────────────────────────────────────────────────
    "rpc.app.achievements.user": {
        "summary": "User achievements",
        "description": "Permission: public; no authentication required, though a hidden tournament 404s unless the optional identity may view it. Returns a player's earned (and optionally locked) achievements, scoped by tournament or without-tournament and workspace; rejects combining tournament_id with without_tournament=true.",
    },
    "rpc.app.achievements.users": {
        "summary": "Achievement earners",
        "description": "Permission: public; no authentication required. Returns a paginated list of players who earned a given achievement.",
    },
    # ── workspaces (reads + writes + members) ──────────────────────────────────────
    "rpc.app.workspaces.list": {
        "summary": "List workspaces",
        "description": (
            "Permission: public; no authentication required — an optional identity only widens `scope=admin`/`all`."
            " Lists workspaces (unpaginated). `scope=public` (the default) is the home-page directory and is"
            " byte-identical for every caller, superusers included: hidden and `unverified` workspaces never appear."
            " `scope=admin` is the management list -- every workspace for a superuser, otherwise only the caller's own"
            " memberships at any tier. `scope=all` is that unioned with the public directory (the workspace switcher)."
            " Any other value is a 422."
        ),
    },
    "rpc.app.workspaces.by_host": {
        "summary": "Resolve workspace by host",
        "description": (
            "Permission: public; no authentication required. Resolves a request host to its workspace ({workspace_id,"
            " slug}) -- the entry point to multitenancy, called by the edge before anything else knows which tenant it"
            " is serving. A host in the platform zone matches on subdomain; any other host matches only a VERIFIED"
            " custom domain. Fail-closed: a missing, malformed, unknown or not-yet-verified host returns null data"
            " rather than an error."
        ),
    },
    "rpc.app.workspaces.get": {
        "summary": "Get workspace",
        "description": "Permission: public; no authentication required. Returns a single workspace by id, 404 if not found.",
    },
    "rpc.app.workspaces.create": {
        "summary": "Create workspace",
        "description": "Permission: authenticated (active) user holding the allow-by-default global `workspace.self_create` capability. Creates a workspace, provisions system roles, stamps and adds the creator as owner, and busts the RBAC cache. Deny that capability for an account (negative RBAC, global scope) to revoke self-service creation from it (403). Then capped per account by `workspace_creation.max_owned_per_user`, counted over `Workspace.owner_id` (403 `workspace_create_limit_reached`); platform slugs are unclaimable (400 `slug_reserved`), 400 on a duplicate slug, and the new workspace is born `unverified`.",
    },
    "rpc.app.admin.update#workspace": {
        "summary": "Update workspace",
        "description": "Permission: workspace `workspace.update`. Updates a workspace via the shared CRUD engine, 404 if not found.",
    },
    "rpc.app.admin.delete#workspace": {
        "summary": "Delete workspace",
        "description": "Permission: workspace `workspace.delete`. Deletes a workspace via the shared CRUD engine; returns 204, 404 if not found.",
    },
    "rpc.app.workspaces.members_list": {
        "summary": "List workspace members",
        "description": "Permission: workspace `workspace_member.read`. Paginated, searchable (username/email) list of a workspace's auth-linked members enriched with auth-user info and RBAC roles; 404 if workspace missing.",
    },
    "rpc.app.workspaces.members_autofill_roles": {
        "summary": "Autofill member roles",
        "description": "Permission: workspace `workspace_member.update`. Grants the baseline 'member' role to every auth-linked member of the workspace that currently has no role; idempotent, returns the count assigned.",
    },
    "rpc.app.workspaces.member_add": {
        "summary": "Add workspace member",
        "description": "Permission: workspace `workspace_member.create`. Adds an auth user to a workspace with resolved role ids and busts the member's RBAC cache; 400 if already a member.",
    },
    "rpc.app.workspaces.member_update": {
        "summary": "Update workspace member",
        "description": "Permission: workspace `workspace_member.update`. Updates a member's workspace roles and busts their RBAC cache; 404 if member missing.",
    },
    "rpc.app.workspaces.member_remove": {
        "summary": "Remove workspace member",
        "description": "Permission: workspace `workspace_member.delete`. Removes a member from a workspace and busts their RBAC cache; refuses to remove the last owner, returns 204.",
    },
    # ── workspace custom domain (white-label Phase 2) ───────────────────────────────
    "rpc.app.workspaces.set_custom_domain": {
        "summary": "Set workspace custom domain",
        "description": "Permission: workspace `workspace.update`. Normalizes and stores a custom domain plus a fresh DNS TXT verification token, resetting verification; 404 if workspace missing, 400 on an invalid domain.",
    },
    "rpc.app.workspaces.verify_custom_domain": {
        "summary": "Verify workspace custom domain",
        "description": "Permission: workspace `workspace.update`. Checks the `_owt-verify.<domain>` DNS TXT record against the stored token and stamps verified_at on a match; 404 if workspace missing, 400 if no domain is set or the record doesn't match yet.",
    },
    "rpc.app.workspaces.clear_custom_domain": {
        "summary": "Clear workspace custom domain",
        "description": "Permission: workspace `workspace.update`. Removes the custom domain, its verification token, and verified_at; 404 if workspace missing.",
    },
    "rpc.app.workspaces.discord_guild_verify": {
        "summary": "Verify and bind a Discord guild",
        "description": "Permission: workspace `workspace.update`, and the caller must additionally administer the Discord guild (owner or MANAGE_GUILD, proven through identity-service). Binds the guild to the workspace, stamping verified_at/verified_by; 404 if workspace missing, 403 if the caller does not administer the guild, 409 if another workspace already claims it, 503 if identity-service is unreachable.",
    },
    "rpc.app.workspaces.discord_guild_clear": {
        "summary": "Unbind a Discord guild",
        "description": "Permission: workspace `workspace.update`, deliberately not Discord administration -- so an organiser can leave a server they were kicked from. Clears the workspace's Discord guild claim (guild id, verified_at, verified_by). 404 if workspace missing. Idempotent when nothing is bound.",
    },
    "rpc.app.workspaces.my_discord_guilds": {
        "summary": "List my administered Discord guilds",
        "description": "Permission: authenticated (active) user; self-service — the caller's own Discord guilds only. Returns the Discord guilds the caller owns or can manage (via identity-service, the `guilds` OAuth scope), for picking one to verify; 503 if identity-service is unreachable.",
    },
    "rpc.app.workspaces.verification_set": {
        "summary": "Set workspace verification status",
        "description": "Permission: superuser only (a workspace owner may not self-certify). Moves a workspace between the `unverified`/`verified`/`trusted` trust tiers — the only way a self-service workspace is unblocked for GPU compute, inline achievement recompute and the public directory; audited on every call including a no-op set, 404 if workspace missing, 422 on an unknown status.",
    },
    "rpc.app.workspaces.owner_get": {
        "summary": "Get the workspace owner",
        "description": "Permission: workspace `workspace.update` (the public workspace model deliberately publishes no owner). Resolves `Workspace.owner_id` — the account accountable for the workspace and counted against the per-account create cap — to its username, email and avatar; returns null data when no owner is stamped, 404 if workspace missing.",
    },
    "rpc.app.workspaces.owner_set": {
        "summary": "Assign or clear the workspace owner",
        "description": "Permission: superuser only — stricter than the `workspace.update` gate on the matching read, because owner_id is what the per-account create cap is counted over. Stamps `Workspace.owner_id` with the given auth account, or clears it when `auth_user_id` is null, and returns the resolved owner. RBAC roles are untouched (the stamp and the `owner` role are decoupled), the per-account cap is not re-checked (a superuser assignment is the override for it), every call is audited including a no-op, 404 if the workspace or the target account is missing.",
    },
    "rpc.app.workspaces.owner_transfer": {
        "summary": "Transfer workspace ownership",
        "description": "Permission: the workspace's current `owner_id` or a superuser — `workspace.update` alone is not enough, a co-administrator may not give away a workspace they do not answer for. Hands the workspace over: stamps `Workspace.owner_id` with the recipient AND moves the RBAC `owner` role to them, adding them to the workspace if they are not a member yet. The outgoing owner keeps their membership and every other role (`member` steps in if `owner` was their only one); the recipient is granted `owner` before the outgoing owner loses it, so the workspace is never ownerless. The recipient's `max_owned_per_user` cap is enforced unless the actor is a superuser (403 `workspace_owner_limit_reached`), because create-then-transfer would otherwise loop past it. Audited, busts both accounts' RBAC cache, 404 if the workspace or the recipient is missing, 403 for anyone but the owner or a superuser.",
    },
    # ── workspace discord entities ──────────────────────────────────────────────────
    "rpc.app.workspaces.discord_roles": {
        "summary": "List workspace Discord roles",
        "description": "Permission: workspace `workspace.update`. Returns roles of the workspace's linked Discord server with names, colors, and positions from discord.py cache.",
    },
    "rpc.app.workspaces.discord_channels": {
        "summary": "List workspace Discord channels",
        "description": "Permission: workspace `workspace.update`. Returns text channels of the workspace's linked Discord server with names and categories.",
    },
    "rpc.app.workspaces.discord_guild": {
        "summary": "Workspace Discord server status",
        "description": "Permission: workspace `workspace.update`. Returns connection status, server name, icon URL, member count, and Discord owner of the workspace's linked Discord server.",
    },
    # ── workspace icon (binary) ────────────────────────────────────────────────────
    "rpc.app.workspaces.icon_upload": {
        "summary": "Upload workspace icon",
        "description": "Permission: workspace `workspace.update`. Uploads a workspace icon to S3 and stores its URL; 404 if workspace missing.",
    },
    "rpc.app.workspaces.icon_delete": {
        "summary": "Delete workspace icon",
        "description": "Permission: workspace `workspace.update`. Removes a workspace's icon from S3 and clears its URL; 404 if workspace missing.",
    },
    # ── assets (binary, workspace-scoped) ────────────────────────────────────────────
    "rpc.app.assets.upload": {
        "summary": "Upload asset",
        "description": "Permission: workspace `asset.create` in the given workspace, or superuser when no `workspace_id` is given. Uploads an achievements/divisions asset to S3, returning its key and public URL; 422 on invalid asset_type.",
    },
    "rpc.app.assets.delete": {
        "summary": "Delete asset",
        "description": "Permission: workspace `asset.delete` in the given workspace, or superuser when no `workspace_id` is given. Deletes an achievements/divisions asset from S3 by slug prefix; 422 on invalid asset_type, 404 if nothing deleted.",
    },
    # ── match log (binary download) ──────────────────────────────────────────────────
    "rpc.app.matches.log": {
        "summary": "Download match log",
        "description": "Permission: any authenticated user — the gateway route requires a session and the handler performs no further permission or ownership check. Returns the raw match-log file bytes for a match (base64 from the worker, decoded by the gateway); 404 if the match or log is missing.",
    },
    # ── metadata admin: heroes ─────────────────────────────────────────────────────────
    "rpc.app.heroes.admin_list": {
        "summary": "Admin list heroes",
        "description": "Permission: superuser only. Returns a paginated admin list of heroes.",
    },
    "rpc.app.heroes.admin_create": {
        "summary": "Create hero",
        "description": "Permission: superuser only. Creates a hero.",
    },
    "rpc.app.heroes.admin_update": {
        "summary": "Update hero",
        "description": "Permission: superuser only. Updates a hero by id.",
    },
    "rpc.app.heroes.admin_delete": {
        "summary": "Delete hero",
        "description": "Permission: superuser only. Deletes a hero by id, returns 204.",
    },
    # ── metadata admin: maps ────────────────────────────────────────────────────────────
    "rpc.app.maps.admin_list": {
        "summary": "Admin list maps",
        "description": "Permission: superuser only. Returns a paginated admin list of maps.",
    },
    "rpc.app.maps.admin_create": {
        "summary": "Create map",
        "description": "Permission: superuser only. Creates a map.",
    },
    "rpc.app.maps.admin_update": {
        "summary": "Update map",
        "description": "Permission: superuser only. Updates a map by id.",
    },
    "rpc.app.maps.admin_delete": {
        "summary": "Delete map",
        "description": "Permission: superuser only. Deletes a map by id, returns 204.",
    },
    # ── metadata admin: gamemodes ─────────────────────────────────────────────────────────
    "rpc.app.gamemodes.admin_list": {
        "summary": "Admin list gamemodes",
        "description": "Permission: superuser only. Returns a paginated admin list of gamemodes.",
    },
    "rpc.app.gamemodes.admin_create": {
        "summary": "Create gamemode",
        "description": "Permission: superuser only. Creates a gamemode.",
    },
    "rpc.app.gamemodes.admin_update": {
        "summary": "Update gamemode",
        "description": "Permission: superuser only. Updates a gamemode by id.",
    },
    "rpc.app.gamemodes.admin_delete": {
        "summary": "Delete gamemode",
        "description": "Permission: superuser only. Deletes a gamemode by id, returns 204.",
    },
    # ── metadata admin: catalog alias-miss queue ──────────────────────────────────────────
    "rpc.app.catalog_aliases.misses_list": {
        "summary": "List catalog alias misses",
        "description": "Permission: superuser only. Returns a paginated queue of hero/map/gamemode names from match logs that no alias resolved, ordered by occurrences then recency; open misses only unless include_resolved=true.",
    },
    "rpc.app.catalog_aliases.attach": {
        "summary": "Attach a catalog alias",
        "description": "Permission: superuser only. Adds the raw name to the target entity's aliases and closes the matching miss in one transaction; 404 if the entity is missing.",
    },
    "rpc.app.catalog_aliases.dismiss": {
        "summary": "Dismiss a catalog alias miss",
        "description": "Permission: superuser only. Marks an alias miss resolved without attaching it; the row reopens if the same name reappears in a log. 404 if the miss is missing.",
    },
    # ── platform audit log ────────────────────────────────────────────────────────────────
    "rpc.app.audit_list": {
        "summary": "List audit log entries",
        "description": (
            "Permission: workspace `audit.read` in the requested workspace, or superuser to read every workspace at"
            " once. Returns a paginated slice of the platform audit log, newest first (created_at then id, both"
            " descending). workspace_id is required for everyone but a superuser and is enforced as a hard scope:"
            " entity_type/entity_id and actor_user_id narrow within it and never reach a row outside it. A superuser may"
            " omit workspace_id to see every workspace plus the platform-level rows that belong to none."
        ),
    },
    # ── users admin (CRUD) ───────────────────────────────────────────────────────────────
    "rpc.app.users.admin_list": {
        "summary": "Admin list users",
        "description": "Permission: global `user.read`, or workspace `user.read` in the workspace named by `workspace_id`. Returns a paginated admin list of players; with `workspace_id` the page is filtered to that workspace's roster.",
    },
    "rpc.app.users.admin_create": {
        "summary": "Create user",
        "description": "Permission: global `user.create`. Creates a player and returns it with discord/battle_tag/twitch identities.",
    },
    "rpc.app.users.admin_update": {
        "summary": "Update user",
        "description": "Permission: global `user.update`. Updates a player by id and returns it with its identities.",
    },
    "rpc.app.users.admin_delete": {
        "summary": "Delete user",
        "description": "Permission: global `user.delete`. Deletes a player by id, returns 204.",
    },
    # ── user profile merge (superuser) ─────────────────────────────────────────────────────
    "rpc.app.users.merge_preview": {
        "summary": "Preview user merge",
        "description": "Permission: superuser only. Previews merging one player profile into another without applying changes.",
    },
    "rpc.app.users.merge_execute": {
        "summary": "Execute user merge",
        "description": "Permission: superuser only. Merges one player profile into another, stamping the operator's auth-user id.",
    },
    # ── social identities (admin) ──────────────────────────────────────────────────────────
    "rpc.app.users.social_add": {
        "description": "Permission: superuser only. Adds a social account (provider + username) to a player and returns the refreshed player.",
    },
    "rpc.app.users.social_update": {
        "description": "Permission: superuser only. Updates the username/url of one of a player's social accounts by account id and returns the refreshed player.",
    },
    "rpc.app.users.social_verify": {
        "description": "Permission: superuser only. Marks an OAuth-eligible social account verified when the automatic sync missed a real OAuth connection that proves it, and returns the refreshed player.",
    },
    "rpc.app.users.social_delete": {
        "description": "Permission: superuser only. Removes one of a player's social accounts by account id and returns the refreshed player.",
    },
    "rpc.app.users.social_set_primary": {
        "description": "Permission: superuser only. Promotes one of a player's social accounts to primary and returns the refreshed player.",
    },
    "rpc.app.users.social_set_visibility": {
        "description": "Permission: global `user.read` for the global switch, or workspace `user.read` in the workspace the payload names — the scope being changed is the scope being authorized. Toggles whether a player's social account is displayed in that scope and returns the refreshed player.",
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
            "Permission: authenticated (active) user with the allow-by-default `account.social` capability;"
            " self-service — the caller acts on their own account only. Returns the caller's own player with its linked"
            " social accounts -- which handles are connected, which one is primary, and each account's public-profile"
            " visibility. Accounts are added through the identity-service OAuth link flow, never here; a caller with no"
            " linked player gets an empty list rather than a 404."
        ),
    },
    "rpc.app.users.me_social_set_primary": {
        "summary": "Set my primary social account",
        "description": (
            "Permission: authenticated (active) user with the allow-by-default `account.social` capability;"
            " self-service — the caller acts on their own account only. Promotes one of the caller's own social accounts"
            " to primary -- the handle shown first on their public profile -- and returns the updated player."
            " OAuth-verified accounts only (400 otherwise), because an unverified handle as primary would put an"
            " unproven identity on a public profile. Requires a linked player; 404 for an account id the caller does not"
            " own."
        ),
    },
    "rpc.app.users.me_social_set_visibility": {
        "summary": "Set my social account visibility",
        "description": (
            "Permission: authenticated (active) user with the allow-by-default `account.social` capability;"
            " self-service — the caller acts on their own account only. Sets whether one of the caller's own social"
            " accounts is shown to anyone on their public profile, and returns the updated player. Global scope only:"
            " this is the self-service hide switch, not the per-workspace admin override, and hiding never deletes the"
            " account or its OAuth link. Requires a linked player; 404 for an account id the caller does not own."
        ),
    },
    "rpc.app.users.me_set_stream_visibility": {
        "summary": "Set my stream visibility",
        "description": (
            "Permission: authenticated (active) user with the allow-by-default `account.social` capability;"
            " self-service — the caller acts on their own account only. Sets whether the caller's own live stream may be"
            " surfaced on tournament pages and returns their updated player. A false value is a veto: it outranks the"
            " per-tournament stream-POV opt-in and the Twitch account's public visibility, and takes effect immediately"
            " rather than at the next poll tick. Independent of social-account visibility, so the handle stays on the"
            " public profile. Requires a linked player (404 otherwise)."
        ),
    },
    # ── favorite players (own account, same account.social capability gate) ─────────────────────────
    "rpc.app.users.me_favorites_list": {
        "summary": "List my favorite players",
        "description": (
            "Permission: authenticated (active) user with the allow-by-default `account.social` capability;"
            " self-service — the caller acts on their own account only. Returns the caller's own favorited players (id +"
            " name), newest favorite first. Scoped to the caller's auth account, not a linked player, so it works even"
            " without one."
        ),
    },
    "rpc.app.users.me_favorite_add": {
        "summary": "Favorite a player",
        "description": (
            "Permission: authenticated (active) user with the allow-by-default `account.social` capability;"
            " self-service — the caller acts on their own account only. Bookmarks a player for the caller's own account."
            " Idempotent (favoriting an already-favorited player is a no-op), 404s if the player id does not exist."
        ),
    },
    "rpc.app.users.me_favorite_remove": {
        "summary": "Unfavorite a player",
        "description": (
            "Permission: authenticated (active) user with the allow-by-default `account.social` capability;"
            " self-service — the caller acts on their own account only. Removes a player from the caller's own"
            " favorites, returns 204. Idempotent (unfavoriting a player that isn't favorited is a no-op, not an error)."
        ),
    },
    # ── user avatar (binary upload + delete) ────────────────────────────────────────────────────────
    "rpc.app.users.avatar_upload": {
        "summary": "Upload user avatar",
        "description": "Permission: global `user.update`. Uploads a player's avatar to S3 and stores its URL.",
    },
    "rpc.app.users.avatar_delete": {
        "summary": "Delete user avatar",
        "description": "Permission: global `user.update`. Removes a player's avatar from S3 and clears its URL.",
    },
    # ── notification inbox + announcement banner ────────────────────────────────────────────────────
    "rpc.app.notifications_list": {
        "summary": "List the caller's notifications",
        "description": (
            "Permission: authenticated (active) user; self-service — the caller's own inbox only. Returns one page of"
            " the caller's inbox newest first, plus the unread badge count and an opaque next_cursor (null on the last"
            " page). The audience is computed from the authenticated identity alone — personal rows, rows for the"
            " workspaces the caller belongs to, and platform-wide announcements — so there is no recipient parameter to"
            " pass. Expired and not-yet-published rows are excluded. System kinds carry no text: the row is kind +"
            " payload snapshot and the client renders it. 422 on a malformed cursor."
        ),
    },
    "rpc.app.notifications_mark_read": {
        "summary": "Mark notifications read",
        "description": (
            "Permission: authenticated (active) user; self-service — the caller's own inbox only. Inserts read marks"
            " for the given ids and returns how many actually landed together with the refreshed unread count. An"
            ' omitted or null `ids` marks the whole visible inbox (the "mark all read" button). Ids outside the caller\'s'
            " audience are dropped silently rather than rejected, so the endpoint cannot be used to probe whether"
            " another user's notification exists; a repeat call marks nothing and is not an error."
        ),
    },
    "rpc.app.notifications_delete": {
        "summary": "Delete notifications from the caller's inbox",
        "description": (
            "Permission: authenticated (active) user; self-service — the caller's own inbox only. Removes rows from"
            " this caller's inbox and returns how many left it together with the refreshed unread count. An omitted or"
            " null `ids` targets the whole visible inbox, and `only_read: true` narrows that to rows already marked read"
            ' (the "clear read" button). The deletion is per viewer: the underlying row survives, so one reader'
            " dismissing a platform-wide announcement does not take it out of anybody else's inbox. Ids outside the"
            " caller's audience are dropped silently rather than rejected, and a repeat call deletes nothing and is not"
            " an error."
        ),
    },
    # ── notifications admin (workspace-scoped operator screen) ──────────────────────────────────────
    "rpc.app.notification_admin_list": {
        "summary": "List the notifications a workspace produced",
        "description": (
            "Permission: workspace `notification.read` in the workspace named by `workspace_id`. Returns one keyset"
            " page of the notifications this workspace's own activity produced (`source_workspace_id`), newest first,"
            " expired ones included — the operator view exists to show what has already been retired, which the inbox's"
            " time window hides. Announcements are not listed here, they have their own CRUD. 422 on an unknown `kind`"
            " or a malformed cursor."
        ),
    },
    "rpc.app.notification_admin_retire": {
        "summary": "Retire notifications a workspace produced",
        "description": (
            "Permission: workspace `notification.delete` in `workspace_id`. Expires the selected rows as of now —"
            " taking them out of every recipient's inbox and badge count — and audits the batch once. `ids` and `kind`"
            " are filters over the same scoped statement and may be combined; naming neither is a 422 rather than a"
            " tenant-wide wipe. The rows and their read marks are kept, like an announcement retire; already-expired"
            " rows are skipped, so a repeat call answers 0."
        ),
    },
    "rpc.app.active_announcements": {
        "summary": "Active announcements for the banner",
        "description": (
            "Permission: public; no authentication required — an optional identity only filters out already-dismissed"
            " rows. Returns the currently-published platform-wide announcements for the site banner, newest first."
            " Anonymous callers are welcome and get every global announcement inside its publish/expiry window; for an"
            " authenticated viewer the ones already dismissed are filtered out, which is why the route forwards identity"
            " when it is present."
        ),
    },
    # ── announcements admin (operator CRUD) ─────────────────────────────────────────────────────────
    "rpc.app.announcement_list": {
        "summary": "List announcements",
        "description": (
            "Permission: workspace `announcement.read` in `workspace_id`, or superuser for the platform-wide feed"
            " (`workspace_id` omitted). Returns one scope's announcements newest first, expired ones included — the"
            " operator view exists to show what is scheduled and what has been retired, which the banner's time window"
            " hides. The two scopes mirror the writes, so the list can never read announcements the caller could not"
            " publish."
        ),
    },
    "rpc.app.announcement_create": {
        "summary": "Publish an announcement",
        "description": (
            "Permission: workspace `announcement.create` in that workspace for a `workspace` announcement, superuser"
            " for a `global` one. Publishes an announcement and audits it. A `workspace` one needs at least one locale"
            " plus a default_locale among the filled ones; a `global` one renders to every visitor including anonymous"
            " ones and requires every supported locale (ru and en) — a workspace grant cannot reach the platform's"
            " voice. `user` is not an accepted audience: personal notifications are written by the flows that cause"
            " them, from server-resolved recipients. 422 on a locale or audience/workspace_id mismatch."
        ),
    },
    "rpc.app.announcement_update": {
        "summary": "Edit an announcement",
        "description": (
            "Permission: decided from the STORED audience, never the request — workspace `announcement.update` for a"
            " workspace announcement, superuser for a global one. Partially edits the text and expiry of an"
            " already-published announcement and audits it. `locales` replaces the whole map when present; audience and"
            " workspace_id are immutable. Read marks are deliberately left alone — clearing them would re-show a banner"
            " to everyone who already dismissed it, for a corrected typo. 404 if the id is not an announcement."
        ),
    },
    "rpc.app.announcement_delete": {
        "summary": "Retire an announcement",
        "description": (
            "Permission: decided from the stored audience like the edit — workspace `announcement.delete` for a"
            " workspace announcement, superuser for a global one. Expires the announcement as of now and audits it,"
            " answering 204. The row is kept rather than deleted: it is a notification row that people already have in"
            " their inbox, and the read marks pointing at it must stay meaningful. 404 if the id is not an announcement."
        ),
    },
}
