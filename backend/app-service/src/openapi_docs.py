"""Human-readable docs (summary + description) for app-service RPC subjects,
merged into the gateway's OpenAPI by the export script. Keyed by RPC subject
(generic-CRUD keys use "<subject>#<entity>"). Prose only.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    "rpc.app.workspaces.team_format_get": {
        "summary": "Get a workspace's default team format",
        "description": "Permission: workspace `workspace.update`. Returns the discipline's workspace default or module preset with its slot projection.",
    },
    "rpc.app.workspaces.team_format_put": {
        "summary": "Replace a workspace's default team format",
        "description": "Permission: workspace `workspace.update`. Sets the template for future tournaments and mixes; existing copies never change. Invalid formats return 422.",
    },
    # ── public native catalog ──────────────────────────────────────────────────
    "rpc.app.catalog.list": {
        "summary": "List a discipline's catalog",
        "description": "Permission: public; no authentication required. Returns a paginated list of one discipline's characters, maps or modes (`kind`); `search`, `parent_id`, `attrs` (JSON object) and `active` filter it, active rows only unless `active=false` is passed. 404 `discipline_not_installed` for an unknown discipline, 404 `catalog_kind_not_declared` for a kind the game does not declare (League has no `mode`).",
    },
    "rpc.app.catalog.get": {
        "summary": "Get a catalog entity",
        "description": "Permission: public; no authentication required. Returns one entity with its parent expanded; inactive rows are readable. 404 `not_found` when the id is not a row of that discipline and kind (never an entity relabelled from another game).",
    },
    "rpc.app.disciplines.list": {
        "summary": "List installed disciplines",
        "description": "Permission: public; an optional identity lets a hidden workspace's members read it. Returns the installed disciplines with their kinds, capabilities and, for `workspace_id=<id>`, whether the workspace enabled each (`all` is the global view, every discipline enabled). Order: declaration order for `all`; for a workspace, its enabled disciplines first in its own `disciplines_enabled` order, then the rest in declaration order. 404 for an unknown or hidden-to-viewer workspace, 422 `invalid_workspace_id` otherwise.",
    },
    "rpc.app.disciplines.metadata": {
        "summary": "Get a discipline's native metadata",
        "description": "Permission: public; an optional identity lets a hidden workspace's members read it. Returns the descriptor, the role dictionary (inactive rows included for history; global roles plus the requested workspace's sub-roles), stat and event vocabularies, team-format presets, the bot lobby the game offers pickup mixes (`lobby_bot`: its server regions and default region; null when none) and the native ladder. 404 `discipline_not_installed` for an unknown code; a disabled discipline is still readable.",
    },
    # ── users (identity reads) ───────────────────────────────────────────────────
    "rpc.app.users.list": {
        "summary": "List users",
        "description": "Permission: public; no authentication required. Returns a paginated, sortable, name-searchable list of players.",
    },
    "rpc.app.users.search": {
        "summary": "Search users",
        "description": "Permission: public; no authentication required. Returns players whose profile name, or a game, Discord or Twitch handle shown on their public profile, matches a free-text query.",
    },
    "rpc.app.users.by_name": {
        "summary": "Get user by name",
        "description": "Permission: public; no authentication required. Resolves a player by BattleTag (name containing '#', dashes normalized) or by Discord name with optional entity expansion.",
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
            " Any other value is a 422. Rows carry no `effective_division_grid_versions`: read one workspace for its"
            " grids."
        ),
    },
    "rpc.app.workspaces.by_slug": {
        "summary": "Get workspace by slug",
        "description": (
            "Permission: public; no authentication required -- an optional identity widens what resolves. The"
            " community page's lookup: the workspace whose slug is `slug`, with its grids, when `scope=all` of the"
            " list would include it for the caller (listed, one of their memberships, or any for a superuser);"
            " 404 otherwise, so a hidden or `unverified` workspace never opens to anyone else by its slug."
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
    "rpc.app.workspaces.staff": {
        "summary": "List workspace staff",
        "description": (
            "Permission: public; no authentication required. The organizers credited on the workspace's public page:"
            " one row per person at their highest of the `owner`/`admin`/`referee` system roles, ordered owner →"
            " admin → referee then by name. `name` is the person's linked player name (BattleTag); an account with no"
            " linked player is omitted. 404 if the workspace does not exist."
        ),
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
        "description": "Permission: workspace `workspace_member.read`. Paginated, searchable (username/email) list of a workspace's auth-linked members enriched with auth-user info and RBAC roles. `role_id` keeps holders of that role; `exclude_role_id` drops holders of any listed role. 404 if workspace missing.",
    },
    "rpc.app.workspaces.members_autofill_roles": {
        "summary": "Autofill member roles",
        "description": "Permission: workspace `workspace_member.update`. Grants the baseline 'player' role to every auth-linked member of the workspace that currently has no role; idempotent, returns the count assigned.",
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
    # ── workspace custom domain ─────────────────────────────────────────────────────
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
        "description": "Permission: workspace `workspace.update`, and the caller must additionally administer the Discord guild (owner or MANAGE_GUILD, proven through identity-service). Binds the guild to the workspace, stamping verified_at/verified_by; 404 if workspace missing, 403 `discord_relink_required` when the caller's Discord connection has no usable OAuth token (re-link Discord), 403 `discord_guild_not_administered` if the caller does not administer the guild, 409 if another workspace already claims it, 503 if identity-service is unreachable.",
    },
    "rpc.app.workspaces.discord_guild_clear": {
        "summary": "Unbind a Discord guild",
        "description": "Permission: workspace `workspace.update`, deliberately not Discord administration -- so an organiser can leave a server they were kicked from. Clears the workspace's Discord guild claim (guild id, verified_at, verified_by). 404 if workspace missing. Idempotent when nothing is bound.",
    },
    "rpc.app.workspaces.my_discord_guilds": {
        "summary": "List my administered Discord guilds",
        "description": 'Permission: authenticated (active) user; self-service — the caller\'s own Discord guilds only. Returns the Discord guilds the caller owns or can manage (via identity-service, the `guilds` OAuth scope), for picking one to verify, and `relink_required` — true when the caller\'s Discord connection has no usable OAuth token, so the empty list means "re-link Discord" rather than "administers nothing"; 503 if identity-service is unreachable.',
    },
    "rpc.app.workspaces.notification_config_get": {
        "summary": "Read a workspace's notification delivery settings",
        "description": "Permission: workspace `workspace.update` — the stored channel names a private guild. Returns where this workspace's broadcast notifications are posted (`discord_channel_id`, a snowflake as a string), the language they are written in, which kinds are posted (`broadcast_kinds`), and the full set that may be enabled (`broadcastable_kinds`) so the screen needs no second source of truth. A workspace that never saved anything reads as its defaults — no channel, `ru`, registration and check-in openings. 404 if workspace missing.",
    },
    "rpc.app.workspaces.notification_config_update": {
        "summary": "Update a workspace's notification delivery settings",
        "description": "Permission: workspace `workspace.update`. Stores the whole form. A non-null `discord_channel_id` must be a text channel of THIS workspace's verified guild — otherwise an administrator of one workspace could make the bot post into another organiser's server: 409 `discord_guild_not_linked` when no guild is bound, 422 `discord_channel_not_in_guild` when the channel is not one of its text channels, and 503 `discord_unavailable` when discord-service cannot be asked (an unchecked channel is never stored). `broadcast_kinds` must be a subset of `broadcastable_kinds` and `locale` one of `ru`/`en`, both 422 otherwise. Returns the same shape as the read. 404 if workspace missing.",
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
    # ── quota policy + usage ────────────────────────────────────────────────────────
    "rpc.app.workspaces.quota_set": {
        "summary": "Set a workspace quota override",
        "description": "Permission: workspace `workspace.update`, but authority is asymmetric: a workspace admin may only LOWER a dimension below what the workspace's plan grants, and a superuser may raise it. Writes one scope's override (`workspace`, `key` or `session`) over the five dimensions — `requests_per_minute`, `heavy_per_day`, `concurrent_heavy`, `max_upload_bytes`, `max_items_per_request`. A null dimension inherits the plan's value; an all-null body deletes the override row and puts the workspace back on its plan. Returns the EFFECTIVE limits after the write (plan merged with the stored override), not the row. Audited as `workspace.quota_update`; the policy cache is dropped immediately. 422 `quota_above_inherited` (carrying `limit_name`, `limit` and `requested`) when a non-superuser raises a value, 404 if the workspace is missing. A metered call later refused by these numbers answers 429 `code=rate_limited` with `Retry-After`; the dimension that refused and the bucket it refused at ride the structured details as `details.limit_name` and `details.scope` (the gateway relays them inside `fields[0]`).",
    },
    "rpc.app.quota.plans": {
        "summary": "List quota plans",
        "description": "Permission: superuser only — a plan is a platform-wide tier, not tenant data. Returns every plan with its per-scope limit rows (`workspace`/`key`/`session`); a null dimension means unlimited at that scope. These are the numbers a refusal reports: a metered call over budget answers 429 `code=rate_limited` with `Retry-After`, naming the dimension and the bucket as `details.limit_name` and `details.scope` (relayed by the gateway inside `fields[0]`).",
    },
    "rpc.app.quota.plan_upsert": {
        "summary": "Create or replace a quota plan",
        "description": "Permission: superuser only. Creates the plan named by `slug` or replaces it, INCLUDING its scope rows wholesale — a plan is read as a complete statement of its tier, so a scope omitted from the body is deleted rather than kept. Audited as `quota.plan_upsert` with the previous and new limit rows; the policy cache is dropped immediately, so the next metered call on every affected workspace enforces the new numbers. A call these limits refuse answers 429 `code=rate_limited` with `Retry-After`, naming the dimension and the bucket as `details.limit_name` and `details.scope` (relayed by the gateway inside `fields[0]`).",
    },
    "rpc.app.quota.operations": {
        "summary": "List metered operations",
        "description": "Permission: superuser only. Returns the `quota.operation` catalogue — the slugs that cost heavy budget, their cost and their enabled flag. A slug with no row here costs no heavy budget; it still spends one per-minute request token. A call refused once that budget is spent answers 429 `code=rate_limited` with `Retry-After`, naming the dimension and the bucket as `details.limit_name` and `details.scope` (relayed by the gateway inside `fields[0]`).",
    },
    "rpc.app.quota.operation_upsert": {
        "summary": "Create or update a metered operation",
        "description": "Permission: superuser only. Sets one operation's heavy cost and its enabled flag — `enabled=false` is the per-operation kill switch, and it takes effect on the next call rather than at the end of a cache TTL. Audited as `quota.operation_upsert`. A call refused by the daily heavy budget answers 429 `code=rate_limited` with `Retry-After`, naming the dimension (`details.limit_name`, here `heavy_per_day`) and the bucket (`details.scope`), which the gateway relays inside `fields[0]`.",
    },
    "rpc.app.quota.workspace_usage": {
        "summary": "Read workspace quota usage",
        "description": "Permission: workspace `team.create` (i.e. a workspace admin) or superuser. Returns the workspace's plan slug and its shared pool's effective ceilings next to what has been spent — requests this minute, heavy units today, concurrent heavy slots held, and the two payload caps — with the seconds until each window resets. Per-key usage is not reported here (identity-service answers for an API key). `policy` is the editable half and covers all three scopes (`workspace`/`key`/`session`), because all three override rows belong to this tenant: each entry carries `override`, the row exactly as stored (all-null when the scope has none), and `inherited`, the ceiling `quota_set` holds a non-superuser write to. 404 if the workspace is missing. A metered call refused against these numbers answers 429 `code=rate_limited` with `Retry-After`, naming the dimension and the bucket as `details.limit_name` and `details.scope` (relayed by the gateway inside `fields[0]`).",
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
        "description": "Permission: workspace `asset.create` in the given workspace, or superuser when no `workspace_id` is given. Uploads an achievements/divisions/catalog asset to S3, returning its key and public URL; 422 on invalid asset_type.",
    },
    "rpc.app.assets.delete": {
        "summary": "Delete asset",
        "description": "Permission: workspace `asset.delete` in the given workspace, or superuser when no `workspace_id` is given. Deletes an achievements/divisions/catalog asset from S3 by slug prefix; 422 on invalid asset_type, 404 if nothing deleted.",
    },
    # ── match log (binary download) ──────────────────────────────────────────────────
    "rpc.app.matches.log": {
        "summary": "Download match log",
        "description": "Permission: any authenticated user — the gateway route requires a session and the handler performs no further permission or ownership check. Returns the raw match-log file bytes for a match (base64 from the worker, decoded by the gateway); 404 if the match or log is missing.",
    },
    # ── game catalog admin (catalog.entity) ────────────────────────────────────────────
    "rpc.app.catalog.admin_list": {
        "summary": "Admin list catalog entities",
        "description": "Permission: superuser only. Returns a paginated list of one discipline's catalog entities of one kind (character, map, mode); filters search, parent_id, attrs (JSON containment), active; 404 for a kind the discipline does not declare.",
    },
    "rpc.app.catalog.workspace_characters": {
        "summary": "List a discipline's characters for a workspace",
        "description": "Permission: workspace `achievement.create` or `achievement.update`. Read-only: returns a paginated list of one discipline's catalog characters (same entity shape as the admin catalog list) so an organizer can link an achievement rule to one; catalog mutations stay superuser only; 404 for a missing workspace, 422 for a discipline the workspace does not have enabled.",
    },
    "rpc.app.catalog.admin_create": {
        "summary": "Create catalog entity",
        "description": "Permission: superuser only. Creates a catalog entity; slug defaults to the slugified name and must fit 64 characters (422 otherwise); a character's attrs.class must be one of the discipline's classes; a map of a discipline with modes needs its mode as parent_id.",
    },
    "rpc.app.catalog.admin_update": {
        "summary": "Update catalog entity",
        "description": "Permission: superuser only. Updates a catalog entity by id; attrs is a shallow merge (present keys replace, absent keys keep). Explicit null is refused for name, slug, attrs and active (422); image_path and parent_id can be cleared. Renaming preserves the stored slug; an explicit slug must fit 64 characters.",
    },
    "rpc.app.catalog.admin_delete": {
        "summary": "Delete catalog entity",
        "description": "Permission: superuser only. Deletes a catalog entity by id, returns 204; fails while a game, pool or legacy mapping references it.",
    },
    # ── metadata admin: catalog alias-miss queue ──────────────────────────────────────────
    "rpc.app.catalog_aliases.misses_list": {
        "summary": "List catalog alias misses",
        "description": "Permission: superuser only. Returns a paginated queue of names (any discipline) a match log or canonical document used that did not resolve, ordered by occurrences then recency. kind is one of character|map|mode (catalog entity names) or stat|event|role (undeclared codes; a role's raw_name is dimension:role); open misses only unless include_resolved=true.",
    },
    "rpc.app.catalog_aliases.attach": {
        "summary": "Attach a catalog alias",
        "description": "Permission: superuser only. Adds the raw name to the target entity's aliases and closes that entity's discipline/kind miss in one transaction; 404 if the entity is missing. Stat/event/role misses are never attachable (dismiss only).",
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
        "description": "Permission: superuser only. Previews merging player profiles, including two auth-linked profiles. auth_policy chooses the surviving auth account, keeping/deleting the other, each OAuth connection destination, and explicit resource-conflict choices. Returns account roles/denies, preservation counts, blockers and a state fingerprint without exposing credentials.",
    },
    "rpc.app.users.merge_execute": {
        "summary": "Execute user merge",
        "description": "Permission: superuser only. Atomically merges player references, selected social identities, auth ownership, preserved resources and audit after rechecking the locked preview fingerprint. Requires independent confirmations for auth changes, auth deletion and permission/access changes. Both accounts' refresh tokens/API keys are revoked; identity-service session blacklisting and RBAC invalidation must succeed before commit. Password, email, active and superuser flags are never combined.",
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
    "rpc.app.notification_preferences_get": {
        "summary": "Read the caller's Discord DM preferences",
        "description": (
            "Permission: authenticated (active) user; self-service — the caller's own preferences only. Returns the"
            " Discord-DM group switches (`tournament`, `matches`, `team`, `staff`) with the defaults filled in: a group"
            " the user never touched is on, so a new group reaches everybody without a backfill. `discord_linked`"
            " reports whether the account has a Discord connection at all — the switches deliver nothing without one."
            " `staff_workspaces` lists every workspace where the caller may resolve match results, each with its own"
            " effective switch; a staff DM needs both the `staff` group and its workspace's switch on. Empty when the"
            " caller is staff nowhere."
        ),
    },
    "rpc.app.notification_preferences_update": {
        "summary": "Update the caller's Discord DM preferences",
        "description": (
            "Permission: authenticated (active) user; self-service — the caller's own preferences only. The edit is"
            " partial: an omitted group keeps its stored value, so one toggle flipped in a stale tab cannot re-assert"
            " the other two. Unknown group names are a 422. `staff_workspaces` (`{workspace_id: bool}`) merges the"
            " same way; a workspace the caller is not staff in is a 422. Answers with the same effective shape as the"
            " read. In-app notifications are not switchable — this only governs delivery to Discord."
        ),
    },
    # ── notifications admin (workspace-scoped operator screen) ──────────────────────────────────────
    "rpc.app.notification_admin_list": {
        "summary": "List the notifications a workspace produced",
        "description": (
            "Permission: workspace `notification.read` in the workspace named by `workspace_id`. Returns one page"
            " (`page`/`per_page`, with `total`) of the notifications this workspace's own activity produced"
            " (`source_workspace_id`), newest first, expired ones included — the operator view exists to show what"
            " has already been retired, which the inbox's time window hides. Announcements are not listed here, they"
            " have their own CRUD. 422 on an unknown `kind`."
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
    # ── notifications admin (one account's own notification state) ──────────────────────────────────
    "rpc.app.admin_user_notifications_get": {
        "summary": "Read one account's notification state",
        "description": (
            "Permission: global `auth_user.read`. Everything the account inspector shows about the account named by"
            " the path id: the effective Discord-DM group switches and per-workspace staff switches with defaults"
            " filled in, whether a Discord account"
            " is connected at all, the unread count that account's own bell shows (same audience rules as their inbox,"
            " not a platform-wide total) and the ten most recent Discord DMs handed to the bot for them, newest first,"
            " each with how far it got (`pending`, `posted`, `failed`, or `lost` when the broker dropped it)."
            " Skips are never recorded, so an empty `recent_deliveries` means nothing was sent — it is not a gap in"
            " the record. Unlike the self-service preferences read this acts on another account, which the global"
            " grant is what authorizes. 404 when the account does not exist."
        ),
    },
    "rpc.app.admin_user_notification_preferences_update": {
        "summary": "Update one account's Discord DM preferences",
        "description": (
            "Permission: global `auth_user.update`. Flips the Discord-DM switches of the account named by the path id"
            " — the operator-side twin of the self-service write, with the same partial-merge semantics: an omitted"
            " group keeps its stored value, unknown group names are a 422 and so is a `staff_workspaces` key the"
            " account is not staff in. The edited row is the target's, never the caller's. Answers with the same"
            " full payload as the read, so the screen needs no refetch. 404 when"
            " the account does not exist."
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
