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
        "description": "Lists match-log processing records filtered by tournament, encounter or workspace with pagination; permission is gated per filter argument.",
    },
    "rpc.parser.logs.retry": {
        "summary": "Retry log processing",
        "description": "Resets a failed/processed log record to pending and re-enqueues it for processing; requires log.reprocess on the record's workspace.",
    },
    "rpc.parser.logs.upload": {
        "summary": "Upload match logs",
        "description": "Multipart (base64) upload of one or more log files for a tournament, storing each to S3 and enqueueing processing, with per-file errors collected; requires log.upload.",
    },
    "rpc.parser.logs.process_tournament": {
        "summary": "Process tournament logs",
        "description": "Enqueues processing of all stored match logs for a tournament; requires the global admin role.",
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
    "rpc.parser.rank.fetch_log": {
        "summary": "Rank fetch log",
        "description": "Lists OverFast rank-collection fetch-log entries filtered by status, source and cursor; requires the global admin role.",
    },
    "rpc.parser.rank.user_collection": {
        "summary": "User rank collection status",
        "description": "Returns the OverFast rank-collection status for each of a user's battle tags; requires the global admin role.",
    },
    "rpc.parser.rank.collect": {
        "summary": "Trigger rank collection",
        "description": "Enqueues an OverFast rank-collection run for a user or specific battle tags and returns the enqueued count; requires the global admin role.",
    },
    # ── achievement calculate ─────────────────────────────────────────────────
    "rpc.parser.ach.calculate": {
        "summary": "Run achievement calculation",
        "description": "Runs the achievement condition-tree engine across a workspace (optionally seeding rules and scoping to specific slugs); requires the global admin role.",
    },
    "rpc.parser.ach.calculate_tournament": {
        "summary": "Calculate tournament achievements",
        "description": "Runs the achievement engine for a single tournament's workspace; requires the global admin role.",
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
        "description": "Lists a workspace's achievement rules filtered by category and enabled flag; requires workspace achievement.read.",
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
        "description": "Deletes a workspace achievement rule; requires workspace achievement.delete.",
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
        "description": "Imports portable achievement rules into a workspace (with source-workspace access check) and returns the import result; requires workspace achievement.import.",
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
        "description": "Imports selected achievement rules from a source workspace's library into the target workspace, warning on missing slugs; requires workspace achievement.import.",
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
        "description": "Syncs hero metadata from OverFast into the database and acks success; requires hero.sync permission.",
    },
    "rpc.parser.metadata.sync_maps": {
        "summary": "Sync maps",
        "description": "Syncs map metadata from OverFast into the database and acks success; requires map.sync permission.",
    },
    "rpc.parser.metadata.sync_gamemodes": {
        "summary": "Sync gamemodes",
        "description": "Syncs gamemode metadata from OverFast into the database and acks success; requires gamemode.sync permission.",
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
    "rpc.parser.discord_channel.delete": {
        "summary": "Delete tournament Discord channel",
        "description": "Removes a tournament's Discord channel configuration; requires discord_channel.delete on the workspace.",
    },
    # ── bootstrap importers ───────────────────────────────────────────────────
    "rpc.parser.tournament.create_with_groups": {
        "summary": "Create tournament with groups",
        "description": "Creates a tournament and its group stages (optionally from a Challonge slug) for a workspace; requires workspace tournament.create.",
    },
    "rpc.parser.teams.challonge_preview": {
        "summary": "Preview Challonge team sync",
        "description": "Previews the mapping of Challonge participants to teams for a tournament before syncing; requires the global admin role.",
    },
    "rpc.parser.teams.create_challonge": {
        "summary": "Sync Challonge teams",
        "description": "Applies Challonge participant-to-team mappings for a tournament; requires the global admin role.",
    },
    "rpc.parser.teams.create_balancer": {
        "summary": "Import balancer teams",
        "description": "Multipart (base64) import of teams from a balancer export JSON (atravkovs or internal format) for a tournament; requires the global admin role.",
    },
    "rpc.parser.encounter.create_challonge": {
        "summary": "Create Challonge encounters",
        "description": "Bulk-creates a tournament's encounters from its Challonge bracket, optionally skipping finals; requires the global admin role.",
    },
}
