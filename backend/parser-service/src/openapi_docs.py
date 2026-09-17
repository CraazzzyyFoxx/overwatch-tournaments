"""Human-readable docs (summary + description) for parser-service RPC subjects,
merged into the gateway's OpenAPI by the export script. Prose only.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    # ── match-log admin ─────────────────────────────────────────────────────
    "rpc.parser.logs.queue_status": {
        "summary": "Match-log queue depths",
        "description": "Permission: global `log.read`. Returns per-status counts of match-log processing records.",
    },
    "rpc.parser.logs.history": {
        "summary": "List log processing records",
        "description": "Permission: `log.read` in the workspace named by the scope argument — `workspace_id`, else the tournament's, else the encounter's workspace — or global `log.read` when no scope argument is given. Lists match-log processing records filtered by tournament, encounter or workspace, plus optional status and free-text search, with pagination.",
    },
    "rpc.parser.logs.stats": {
        "summary": "Log processing stats",
        "description": "Permission: `log.read` in the workspace named by the scope argument — `workspace_id`, else the tournament's, else the encounter's workspace — or global `log.read` when no scope argument is given. Returns scope-wide processing counts per status, average completed duration and the newest record timestamp for a tournament, encounter or workspace.",
    },
    "rpc.parser.logs.retry": {
        "summary": "Retry log processing",
        "description": "Permission: workspace `log.update` in the record's workspace. Resets a failed/processed log record to pending, re-enqueues it for processing and returns the updated record, 404ing when the record does not exist.",
    },
    "rpc.parser.logs.upload": {
        "summary": "Upload match logs",
        "description": "Permission: workspace `log.create` in the tournament's workspace. Multipart (base64) upload of one or more log files for a tournament, storing each to S3 and enqueueing processing, with per-file errors collected. Metered: over quota the call answers 429 with `code=rate_limited` and the exceeded limit in `details.limit_name`.",
    },
    "rpc.parser.logs.process_tournament": {
        "summary": "Process tournament logs",
        "description": "Permission: workspace `log.update` in the tournament's workspace. Enqueues reprocessing of all stored match logs for a tournament and returns an ack message — the work itself runs asynchronously on the log queue — 404ing on an unknown tournament. Metered: over quota the call answers 429 with `code=rate_limited` and the exceeded limit in `details.limit_name`.",
    },
    # ── impact baselines ──────────────────────────────────────────────────────
    "rpc.parser.impact.recompute_baselines": {
        "summary": "Recompute impact baselines",
        "description": "Permission: superuser. Rebuilds the statistical baselines MVP-impact scoring is measured against (`matches.stat_baselines`) for the active formula version, aggregating a mean/standard deviation per (role, rank bucket, stat) over every historical match-statistics row — global, with no tournament or workspace scope — and returns the row count plus that formula version. Each run atomically replaces the version's rows and aborts rather than wiping them when the aggregation yields nothing, so repeating it is safe; it does scan the whole statistics table and drops the 10-minute baseline cache every time, so avoid running it back to back.",
    },
    # ── OverFast rank ────────────────────────────────────────────────────────
    "rpc.parser.rank.user_history": {
        "summary": "User rank history",
        "description": "Permission: public; no authentication required. Returns a user's OverFast rank time series with configurable granularity, date range, platform and role filters.",
    },
    "rpc.parser.rank.battle_tag_history": {
        "summary": "Battle tag rank history",
        "description": "Permission: public; no authentication required. Returns a single battle tag's OverFast rank time series with granularity, date range, platform and role filters.",
    },
    "rpc.parser.rank.user_current": {
        "summary": "Current user ranks",
        "description": "Permission: public; no authentication required. Returns a user's current OverFast ranks for the requested platform.",
    },
    "rpc.parser.rank.stats": {
        "summary": "Rank collection health stats",
        "description": "Permission: workspace `rank.read` when `workspace_id` is given (aggregates are then scoped to the battle tags of that workspace's players), otherwise global `rank.read`. Aggregated OverFast rank-collection health: battle-tag state counts by status and priority tier, snapshot coverage over 24h/7d, last successful capture, last-24h fetch-outcome mix with error rate, and the active config.",
    },
    "rpc.parser.rank.fetch_log": {
        "summary": "Rank fetch log",
        "description": "Permission: workspace `rank.read` when `workspace_id` is given (rows are then scoped to the battle tags of that workspace's players), otherwise global `rank.read`. Lists OverFast rank-collection fetch-log entries filtered by status, source and cursor.",
    },
    "rpc.parser.rank.user_collection": {
        "summary": "User rank collection status",
        "description": "Permission: workspace `rank.read` when `workspace_id` is given (empty unless the player is a member of that workspace), otherwise global `rank.read`. Returns the OverFast rank-collection status for each of a user's battle tags.",
    },
    "rpc.parser.rank.collect": {
        "summary": "Trigger rank collection",
        "description": "Permission: workspace `rank.update` when `workspace_id` is given (only that workspace's players' tags are touched), otherwise global `rank.update`. Enqueues an OverFast rank-collection run for a user or specific battle tags and returns the enqueued count.",
    },
    "rpc.parser.rank.reenable_disabled": {
        "summary": "Re-enable disabled rank collection",
        "description": "Permission: workspace `rank.update` when `workspace_id` is given (only that workspace's players' tags are requeued), otherwise global `rank.update`. Requeues battle tags that were auto-disabled by a transient OverFast outage (status disabled -> pending, failure counter reset), spreading them across the collection interval; optionally limited to tags that previously succeeded. Returns the re-enabled count.",
    },
    # ── subscription collection admin ─────────────────────────────────────────
    "rpc.parser.subscription.stats": {
        "summary": "Subscription collection health stats",
        "description": "Permission: workspace `subscription.read` when `workspace_id` is given (aggregates are then scoped to that workspace), otherwise global `subscription.read`. Aggregated subscription-collection health: entitlement counts by state and provider, distinct-user check coverage over 24h/7d, last successful check, last-24h check-outcome mix with error rate, the number of open tournaments enforcing a subscription, and the active config.",
    },
    "rpc.parser.subscription.check_log": {
        "summary": "Subscription check log",
        "description": "Permission: workspace `subscription.read` when `workspace_id` is given (rows are then scoped to that workspace), otherwise global `subscription.read`. Lists append-only subscription check-log entries (the collection history) filtered by state, source, provider, auth user and cursor.",
    },
    "rpc.parser.subscription.user_collection": {
        "summary": "User subscription collection status",
        "description": "Permission: workspace `subscription.read` when `workspace_id` is given (only that workspace's entitlement is returned), otherwise global `subscription.read`. Returns the current subscription entitlement per workspace and provider for one player.",
    },
    "rpc.parser.subscription.collect": {
        "summary": "Trigger subscription collection",
        "description": "Permission: workspace `subscription.update` when `workspace_id` is given (the re-check is then limited to that workspace), otherwise global `subscription.update`. Runs a live subscription re-check for one player (optionally limited to specific providers) or sweeps every open tournament that requires a subscription, and returns the number of checks performed.",
    },
    # ── achievement calculate ─────────────────────────────────────────────────
    "rpc.parser.ach.calculate": {
        "summary": "Run achievement calculation",
        "description": "Permission: workspace `achievement.update` in the payload's `workspace_id`. Runs the achievement condition-tree engine across a workspace (optionally seeding the built-in rules first and scoping the run to given slugs) and returns the slugs actually evaluated, rejecting unknown slugs and a missing workspace_id with 400. Metered: over quota the call answers 429 with `code=rate_limited` and the exceeded limit in `details.limit_name`.",
    },
    "rpc.parser.ach.calculate_tournament": {
        "summary": "Calculate tournament achievements",
        "description": "Permission: workspace `achievement.update` in the tournament's workspace. Runs the achievement engine for a single tournament — the workspace is taken from the tournament unless an explicitly matching workspace_id is supplied — and returns the tournament id plus the slugs evaluated, 404ing on an unknown tournament. Metered: over quota the call answers 429 with `code=rate_limited` and the exceeded limit in `details.limit_name`.",
    },
    # ── achievement rules admin (workspace-scoped) ────────────────────────────
    "rpc.parser.ach.condition_types": {
        "summary": "List condition types",
        "description": "Permission: workspace `achievement.read`. Returns the catalog of available achievement condition-tree leaf types with their grain.",
    },
    "rpc.parser.ach.validate": {
        "summary": "Validate condition tree",
        "description": "Permission: workspace `achievement.read`. Validates an achievement condition tree and returns errors plus the inferred grain.",
    },
    "rpc.parser.ach.list": {
        "summary": "List achievement rules",
        "description": "Permission: workspace `achievement.read`. Pages a workspace's achievement rules with search, category, and enabled filters.",
    },
    "rpc.parser.ach.get": {
        "summary": "Get achievement rule",
        "description": "Permission: workspace `achievement.read`. Returns a single achievement rule scoped to the workspace.",
    },
    "rpc.parser.ach.create": {
        "summary": "Create achievement rule",
        "description": "Permission: workspace `achievement.create`. Creates a workspace achievement rule after validating its condition tree and enforcing slug uniqueness.",
    },
    "rpc.parser.ach.update": {
        "summary": "Update achievement rule",
        "description": "Permission: workspace `achievement.update`. Updates an achievement rule, revalidating and bumping its version on condition-tree change and re-running evaluation when enabled.",
    },
    "rpc.parser.ach.delete": {
        "summary": "Delete achievement rule",
        "description": "Permission: workspace `achievement.delete`. Deletes a workspace achievement rule and returns no content, 404ing when the rule does not exist in that workspace.",
    },
    "rpc.parser.ach.seed": {
        "summary": "Seed achievement rules",
        "description": "Permission: workspace `achievement.create`. Seeds the built-in achievement rules into a workspace and returns seeded/removed counts.",
    },
    "rpc.parser.ach.reset": {
        "summary": "Reset achievement rules",
        "description": "Permission: workspace `achievement.update`. Hard-resets a workspace by reseeding rules and clearing evaluation results, returning the new run.",
    },
    "rpc.parser.ach.export": {
        "summary": "Export achievement rules",
        "description": "Permission: workspace `achievement.read`. Returns a portable JSON export payload of all of a workspace's achievement rules. Metered: over quota the call answers 429 with `code=rate_limited` and the exceeded limit in `details.limit_name`.",
    },
    "rpc.parser.ach.import": {
        "summary": "Import achievement rules",
        "description": "Permission: workspace `achievement.create` in the target workspace, plus membership of (or superuser over) the source workspace when one is named. Imports portable achievement rules into a workspace and returns the import result. Metered: over quota the call answers 429 with `code=rate_limited` and the exceeded limit in `details.limit_name`.",
    },
    "rpc.parser.ach.evaluate": {
        "summary": "Evaluate achievement rules",
        "description": "Permission: workspace `achievement.update`. Triggers a manual achievement evaluation run for selected rules and/or a tournament.",
    },
    "rpc.parser.ach.runs": {
        "summary": "List evaluation runs",
        "description": "Permission: workspace `achievement.read`. Returns the 50 most recent achievement evaluation runs for a workspace.",
    },
    "rpc.parser.ach.rule_users": {
        "summary": "List rule's qualifying users",
        "description": "Permission: workspace `achievement.read`. Returns a paginated, sortable list of users who earned a rule's achievement with counts and first-qualified timestamps.",
    },
    "rpc.parser.ach.test": {
        "summary": "Test achievement rule",
        "description": "Permission: workspace `achievement.update`. Dry-runs a rule's condition tree against an optional tournament and returns the qualifying count plus a sample of results.",
    },
    "rpc.parser.ach.lib_workspaces": {
        "summary": "List library workspaces",
        "description": "Permission: workspace `achievement.read`. Lists other workspaces (visible to the caller) that have achievement rules available to import as a library.",
    },
    "rpc.parser.ach.lib_list": {
        "summary": "List library rules",
        "description": "Permission: workspace `achievement.read` in the target workspace, plus membership of (or superuser over) the source workspace. Lists the achievement rules of a source workspace available for library import.",
    },
    "rpc.parser.ach.lib_import": {
        "summary": "Import library rules",
        "description": "Permission: workspace `achievement.create` in the target workspace, plus membership of (or superuser over) the source workspace. Imports selected achievement rules from a source workspace's library into the target workspace, warning on missing slugs. Metered: over quota the call answers 429 with `code=rate_limited` and the exceeded limit in `details.limit_name`.",
    },
    "rpc.parser.ach.overrides_list": {
        "summary": "List achievement overrides",
        "description": "Permission: workspace `achievement.read`. Lists manual grant/revoke achievement overrides for a workspace.",
    },
    "rpc.parser.ach.override_create": {
        "summary": "Create achievement override",
        "description": "Permission: workspace `achievement.update`. Creates a manual achievement override (grant or revoke) for a user on a rule, stamped with the granting actor.",
    },
    "rpc.parser.ach.override_delete": {
        "summary": "Delete achievement override",
        "description": "Permission: workspace `achievement.update`. Deletes a manual achievement override scoped to the workspace.",
    },
    # ── OverFast metadata sync ─────────────────────────────────────────────────
    "rpc.parser.metadata.sync_heroes": {
        "summary": "Sync heroes",
        "description": "Permission: superuser. Syncs hero metadata from OverFast into the database and acks success.",
    },
    "rpc.parser.metadata.sync_maps": {
        "summary": "Sync maps",
        "description": "Permission: superuser. Syncs map metadata from OverFast into the database and acks success.",
    },
    "rpc.parser.metadata.sync_gamemodes": {
        "summary": "Sync gamemodes",
        "description": "Permission: superuser. Syncs gamemode metadata from OverFast into the database and acks success.",
    },
    # ── global settings ─────────────────────────────────────────────────────
    "rpc.parser.settings.list": {
        "summary": "List global settings",
        "description": "Permission: superuser. Returns all global key/value settings.",
    },
    "rpc.parser.settings.get": {
        "summary": "Get global setting",
        "description": "Permission: superuser. Returns a single global setting by key.",
    },
    "rpc.parser.settings.upsert": {
        "summary": "Upsert global setting",
        "description": "Permission: superuser. Creates or updates a global setting by key, stamping the updating user.",
    },
    # ── per-tournament Discord channel ────────────────────────────────────────
    "rpc.parser.discord_channel.get": {
        "summary": "Get tournament Discord channel",
        "description": "Permission: workspace `discord_channel.read` in the tournament's workspace. Returns the Discord channel configuration for a tournament (or null).",
    },
    "rpc.parser.discord_channel.upsert": {
        "summary": "Upsert tournament Discord channel",
        "description": "Permission: workspace `discord_channel.update` in the tournament's workspace. Creates or updates a tournament's Discord guild/channel binding.",
    },
    "rpc.parser.discord_channel.backfill": {
        "summary": "Backfill Discord channel history",
        "description": "Permission: workspace `discord_channel.update` in the tournament's workspace. Queues a rescan of the tournament's Discord channel history — the same `process_all` command the bot runs at startup — resubmitting every attachment found in the last 500 messages of each channel bound to the tournament; returns an ack immediately, the scan itself is asynchronous, and 404s when no channel is configured. Ingestion deduplicates on the SHA-256 of a log file's bytes, so logs already processed for the tournament are skipped rather than duplicated, but each call re-downloads and re-uploads every attachment — repeat it only when logs are genuinely missing.",
    },
    "rpc.parser.discord_channel.delete": {
        "summary": "Delete tournament Discord channel",
        "description": "Permission: workspace `discord_channel.delete` in the tournament's workspace. Removes a tournament's Discord channel configuration and returns no content, 404ing when no channel is configured.",
    },
}
