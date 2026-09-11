"""Human-readable docs (summary + description) for parser-service RPC subjects,
merged into the gateway's OpenAPI by the export script. Prose only.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    # ── match-log admin ─────────────────────────────────────────────────────
    "rpc.parser.logs.queue_status": {
        "summary": "Match-log queue depths",
        "description": "Returns per-status counts of match-log processing records; admin-only (requires log.read permission).",
    },
    "rpc.parser.logs.history": {
        "summary": "List log processing records",
        "description": "Lists match-log processing records filtered by tournament, encounter or workspace, plus optional status and free-text search, with pagination; permission is gated per filter argument.",
    },
    "rpc.parser.logs.stats": {
        "summary": "Log processing stats",
        "description": "Returns scope-wide processing counts per status, average completed duration and the newest record timestamp for a tournament, encounter or workspace; permission is gated per filter argument like history.",
    },
    "rpc.parser.logs.retry": {
        "summary": "Retry log processing",
        "description": "Resets a failed/processed log record to pending, re-enqueues it for processing and returns the updated record, 404ing when the record does not exist; requires log.update on the record's workspace.",
    },
    "rpc.parser.logs.upload": {
        "summary": "Upload match logs",
        "description": "Multipart (base64) upload of one or more log files for a tournament, storing each to S3 and enqueueing processing, with per-file errors collected; requires log.create.",
    },
    "rpc.parser.logs.process_tournament": {
        "summary": "Process tournament logs",
        "description": "Enqueues reprocessing of all stored match logs for a tournament and returns an ack message — the work itself runs asynchronously on the log queue — 404ing on an unknown tournament; requires log.update in the tournament's workspace.",
    },
    # ── impact baselines ──────────────────────────────────────────────────────
    "rpc.parser.impact.recompute_baselines": {
        "summary": "Recompute impact baselines",
        "description": "Rebuilds the statistical baselines MVP-impact scoring is measured against (`matches.stat_baselines`) for the active formula version, aggregating a mean/standard deviation per (role, rank bucket, stat) over every historical match-statistics row — global, with no tournament or workspace scope — and returns the row count plus that formula version. Superuser-only. Each run atomically replaces the version's rows and aborts rather than wiping them when the aggregation yields nothing, so repeating it is safe; it does scan the whole statistics table and drops the 10-minute baseline cache every time, so avoid running it back to back.",
    },
    # ── OverFast rank ────────────────────────────────────────────────────────
    "rpc.parser.rank.user_history": {
        "summary": "User rank history",
        "description": "Returns a user's OverFast rank time series with configurable granularity, date range, platform and role filters; public read.",
    },
    "rpc.parser.rank.battle_tag_history": {
        "summary": "Battle tag rank history",
        "description": "Returns a single battle tag's OverFast rank time series with granularity, date range, platform and role filters; public read.",
    },
    "rpc.parser.rank.user_current": {
        "summary": "Current user ranks",
        "description": "Returns a user's current OverFast ranks for the requested platform; public read.",
    },
    "rpc.parser.rank.stats": {
        "summary": "Rank collection health stats",
        "description": "Aggregated OverFast rank-collection health: battle-tag state counts by status and priority tier, snapshot coverage over 24h/7d, last successful capture, last-24h fetch-outcome mix with error rate, and the active config. Requires `rank.read` in `workspace_id` when given (aggregates are then scoped to the battle tags of that workspace's players), or globally when omitted.",
    },
    "rpc.parser.rank.fetch_log": {
        "summary": "Rank fetch log",
        "description": "Lists OverFast rank-collection fetch-log entries filtered by status, source and cursor. Requires `rank.read` in `workspace_id` when given (rows are then scoped to the battle tags of that workspace's players), or globally when omitted.",
    },
    "rpc.parser.rank.user_collection": {
        "summary": "User rank collection status",
        "description": "Returns the OverFast rank-collection status for each of a user's battle tags. Requires `rank.read` in `workspace_id` when given (empty unless the player is a member of that workspace), or globally when omitted.",
    },
    "rpc.parser.rank.collect": {
        "summary": "Trigger rank collection",
        "description": "Enqueues an OverFast rank-collection run for a user or specific battle tags and returns the enqueued count. Requires `rank.update` in `workspace_id` when given (only that workspace's players' tags are touched), or globally when omitted.",
    },
    "rpc.parser.rank.reenable_disabled": {
        "summary": "Re-enable disabled rank collection",
        "description": "Requeues battle tags that were auto-disabled by a transient OverFast outage (status disabled -> pending, failure counter reset), spreading them across the collection interval; optionally limited to tags that previously succeeded. Returns the re-enabled count. Requires `rank.update` in `workspace_id` when given (only that workspace's players' tags are requeued), or globally when omitted.",
    },
    # ── subscription collection admin ─────────────────────────────────────────
    "rpc.parser.subscription.stats": {
        "summary": "Subscription collection health stats",
        "description": "Aggregated subscription-collection health: entitlement counts by state and provider, distinct-user check coverage over 24h/7d, last successful check, last-24h check-outcome mix with error rate, the number of open tournaments enforcing a subscription, and the active config. Requires `subscription.read` in `workspace_id` when given (aggregates are then scoped to that workspace), or globally when omitted.",
    },
    "rpc.parser.subscription.check_log": {
        "summary": "Subscription check log",
        "description": "Lists append-only subscription check-log entries (the collection history) filtered by state, source, provider, auth user and cursor. Requires `subscription.read` in `workspace_id` when given (rows are then scoped to that workspace), or globally when omitted.",
    },
    "rpc.parser.subscription.user_collection": {
        "summary": "User subscription collection status",
        "description": "Returns the current subscription entitlement per workspace and provider for one player. Requires `subscription.read` in `workspace_id` when given (only that workspace's entitlement is returned), or globally when omitted.",
    },
    "rpc.parser.subscription.collect": {
        "summary": "Trigger subscription collection",
        "description": "Runs a live subscription re-check for one player (optionally limited to specific providers) or sweeps every open tournament that requires a subscription, and returns the number of checks performed. Requires `subscription.update` in `workspace_id` when given (the re-check is then limited to that workspace), or globally when omitted.",
    },
    # ── achievement calculate ─────────────────────────────────────────────────
    "rpc.parser.ach.calculate": {
        "summary": "Run achievement calculation",
        "description": "Runs the achievement condition-tree engine across a workspace (optionally seeding the built-in rules first and scoping the run to given slugs) and returns the slugs actually evaluated, rejecting unknown slugs and a missing workspace_id with 400; requires achievement.update in the requested workspace.",
    },
    "rpc.parser.ach.calculate_tournament": {
        "summary": "Calculate tournament achievements",
        "description": "Runs the achievement engine for a single tournament — the workspace is taken from the tournament unless an explicitly matching workspace_id is supplied — and returns the tournament id plus the slugs evaluated, 404ing on an unknown tournament; requires achievement.update in that workspace.",
    },
    # ── achievement rules admin (workspace-scoped) ────────────────────────────
    "rpc.parser.ach.condition_types": {
        "summary": "List condition types",
        "description": "Returns the catalog of available achievement condition-tree leaf types with their grain; requires workspace achievement.read.",
    },
    "rpc.parser.ach.validate": {
        "summary": "Validate condition tree",
        "description": "Validates an achievement condition tree and returns errors plus the inferred grain; requires workspace achievement.read.",
    },
    "rpc.parser.ach.list": {
        "summary": "List achievement rules",
        "description": "Pages a workspace's achievement rules with search, category, and enabled filters; requires workspace achievement.read.",
    },
    "rpc.parser.ach.get": {
        "summary": "Get achievement rule",
        "description": "Returns a single achievement rule scoped to the workspace; requires workspace achievement.read.",
    },
    "rpc.parser.ach.create": {
        "summary": "Create achievement rule",
        "description": "Creates a workspace achievement rule after validating its condition tree and enforcing slug uniqueness; requires workspace achievement.create.",
    },
    "rpc.parser.ach.update": {
        "summary": "Update achievement rule",
        "description": "Updates an achievement rule, revalidating and bumping its version on condition-tree change and re-running evaluation when enabled; requires workspace achievement.update.",
    },
    "rpc.parser.ach.delete": {
        "summary": "Delete achievement rule",
        "description": "Deletes a workspace achievement rule and returns no content, 404ing when the rule does not exist in that workspace; requires workspace achievement.delete.",
    },
    "rpc.parser.ach.seed": {
        "summary": "Seed achievement rules",
        "description": "Seeds the built-in achievement rules into a workspace and returns seeded/removed counts; requires workspace achievement.create.",
    },
    "rpc.parser.ach.reset": {
        "summary": "Reset achievement rules",
        "description": "Hard-resets a workspace by reseeding rules and clearing evaluation results, returning the new run; requires workspace achievement.update.",
    },
    "rpc.parser.ach.export": {
        "summary": "Export achievement rules",
        "description": "Returns a portable JSON export payload of all of a workspace's achievement rules; requires workspace achievement.export.",
    },
    "rpc.parser.ach.import": {
        "summary": "Import achievement rules",
        "description": "Imports portable achievement rules into a workspace (with source-workspace access check) and returns the import result; requires workspace achievement.create.",
    },
    "rpc.parser.ach.evaluate": {
        "summary": "Evaluate achievement rules",
        "description": "Triggers a manual achievement evaluation run for selected rules and/or a tournament; requires workspace achievement.calculate.",
    },
    "rpc.parser.ach.runs": {
        "summary": "List evaluation runs",
        "description": "Returns the 50 most recent achievement evaluation runs for a workspace; requires workspace achievement.read.",
    },
    "rpc.parser.ach.rule_users": {
        "summary": "List rule's qualifying users",
        "description": "Returns a paginated, sortable list of users who earned a rule's achievement with counts and first-qualified timestamps; requires workspace achievement.read.",
    },
    "rpc.parser.ach.test": {
        "summary": "Test achievement rule",
        "description": "Dry-runs a rule's condition tree against an optional tournament and returns the qualifying count plus a sample of results; requires workspace achievement.calculate.",
    },
    "rpc.parser.ach.lib_workspaces": {
        "summary": "List library workspaces",
        "description": "Lists other workspaces (visible to the caller) that have achievement rules available to import as a library; requires workspace achievement.read.",
    },
    "rpc.parser.ach.lib_list": {
        "summary": "List library rules",
        "description": "Lists the achievement rules of a source workspace available for library import; requires workspace achievement.read.",
    },
    "rpc.parser.ach.lib_import": {
        "summary": "Import library rules",
        "description": "Imports selected achievement rules from a source workspace's library into the target workspace, warning on missing slugs; requires workspace achievement.create.",
    },
    "rpc.parser.ach.overrides_list": {
        "summary": "List achievement overrides",
        "description": "Lists manual grant/revoke achievement overrides for a workspace; requires workspace achievement.read.",
    },
    "rpc.parser.ach.override_create": {
        "summary": "Create achievement override",
        "description": "Creates a manual achievement override (grant or revoke) for a user on a rule, stamped with the granting actor; requires workspace achievement.update.",
    },
    "rpc.parser.ach.override_delete": {
        "summary": "Delete achievement override",
        "description": "Deletes a manual achievement override scoped to the workspace; requires workspace achievement.update.",
    },
    # ── OverFast metadata sync ─────────────────────────────────────────────────
    "rpc.parser.metadata.sync_heroes": {
        "summary": "Sync heroes",
        "description": "Syncs hero metadata from OverFast into the database and acks success (superuser only).",
    },
    "rpc.parser.metadata.sync_maps": {
        "summary": "Sync maps",
        "description": "Syncs map metadata from OverFast into the database and acks success (superuser only).",
    },
    "rpc.parser.metadata.sync_gamemodes": {
        "summary": "Sync gamemodes",
        "description": "Syncs gamemode metadata from OverFast into the database and acks success (superuser only).",
    },
    # ── global settings ─────────────────────────────────────────────────────
    "rpc.parser.settings.list": {
        "summary": "List global settings",
        "description": "Returns all global key/value settings; superuser-only.",
    },
    "rpc.parser.settings.get": {
        "summary": "Get global setting",
        "description": "Returns a single global setting by key; superuser-only.",
    },
    "rpc.parser.settings.upsert": {
        "summary": "Upsert global setting",
        "description": "Creates or updates a global setting by key, stamping the updating user; superuser-only.",
    },
    # ── per-tournament Discord channel ────────────────────────────────────────
    "rpc.parser.discord_channel.get": {
        "summary": "Get tournament Discord channel",
        "description": "Returns the Discord channel configuration for a tournament (or null); requires discord_channel.read on the workspace.",
    },
    "rpc.parser.discord_channel.upsert": {
        "summary": "Upsert tournament Discord channel",
        "description": "Creates or updates a tournament's Discord guild/channel binding; requires discord_channel.update on the workspace.",
    },
    "rpc.parser.discord_channel.backfill": {
        "summary": "Backfill Discord channel history",
        "description": "Queues a rescan of the tournament's Discord channel history — the same `process_all` command the bot runs at startup — resubmitting every attachment found in the last 500 messages of each channel bound to the tournament; returns an ack immediately, the scan itself is asynchronous. Requires discord_channel.update on the workspace and 404s when no channel is configured. Ingestion deduplicates on the SHA-256 of a log file's bytes, so logs already processed for the tournament are skipped rather than duplicated, but each call re-downloads and re-uploads every attachment — repeat it only when logs are genuinely missing.",
    },
    "rpc.parser.discord_channel.delete": {
        "summary": "Delete tournament Discord channel",
        "description": "Removes a tournament's Discord channel configuration and returns no content, 404ing when no channel is configured; requires discord_channel.delete on the workspace.",
    },
}
