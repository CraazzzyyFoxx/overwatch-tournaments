"""Human-readable docs (summary + description) for tournament-service RPC
subjects, merged into the gateway's OpenAPI by the export script. Keyed by RPC
subject (generic-CRUD keys use "<subject>#<entity>"). Prose only — types live in
openapi_schemas.py. The gateway appends the RPC subject footer itself.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    # ── public reads (single object) ───────────────────────────────────────
    "rpc.tournament.get_tournament": {
        "summary": "Get tournament",
        "description": "Returns one tournament by id with optionally hydrated related entities selected via the entities query param.",
    },
    "rpc.tournament.get_team": {
        "summary": "Get team",
        "description": "Returns one team by id with optionally hydrated related entities (players, captain, tournament) selected via the entities query param.",
    },
    "rpc.tournament.get_encounter": {
        "summary": "Get encounter",
        "description": "Returns one encounter by id with optionally hydrated related entities selected via the entities query param.",
    },
    "rpc.tournament.get_match": {
        "summary": "Get match with stats",
        "description": "Returns one match by id with player statistics and optionally hydrated related entities, scoped to the given workspace.",
    },
    "rpc.tournament.encounters_overview": {
        "summary": "Get encounters overview",
        "description": "Returns an aggregated encounters overview for the search filters, with viewer-scoped fields resolved from the optional identity.",
    },
    "rpc.tournament.statistics_overall": {
        "summary": "Get overall statistics",
        "description": "Returns aggregate tournament statistics across the workspace.",
    },
    "rpc.tournament.owal_results": {
        "summary": "Get league standings",
        "description": "Returns OWAL league standings for the workspace, for a specific season when given or overall, normalized against the workspace division grid.",
    },
    "rpc.tournament.owal_seasons": {
        "summary": "List league seasons",
        "description": "Returns the list of available OWAL league seasons for the workspace.",
    },
    # ── public reads (arrays) ──────────────────────────────────────────────
    "rpc.tournament.lookup_tournaments": {
        "summary": "Lookup tournaments",
        "description": "Returns a lightweight id/name list of up to 500 most-recent tournaments, optionally filtered by workspace and league flag, for pickers.",
    },
    "rpc.tournament.get_stages": {
        "summary": "List tournament stages",
        "description": "Returns all stages of a tournament ordered by stage order, with their items and item inputs hydrated.",
    },
    "rpc.tournament.get_standings": {
        "summary": "Get tournament standings",
        "description": "Returns the standings for a tournament with optionally hydrated related entities selected via the entities query param.",
    },
    "rpc.tournament.statistics_history": {
        "summary": "Get tournament history stats",
        "description": "Returns per-tournament historical statistics for the workspace.",
    },
    "rpc.tournament.statistics_division": {
        "summary": "Get division statistics",
        "description": "Returns average-division statistics per tournament, normalized against the workspace division grid with fallback to the global grid.",
    },
    "rpc.tournament.owal_stacks": {
        "summary": "Get league player stacks",
        "description": "Returns OWAL league player stacks for the workspace and season, defaulting to the latest season when none is given.",
    },
    "rpc.tournament.saved_views": {
        "summary": "List saved encounter views",
        "description": "Returns the calling user's saved encounter filter views for the workspace; requires authentication.",
    },
    # ── public reads (paginated) ───────────────────────────────────────────
    "rpc.tournament.list_tournaments": {
        "summary": "List tournaments",
        "description": "Returns a paginated, sortable, searchable list of tournaments.",
    },
    "rpc.tournament.list_encounters": {
        "summary": "List encounters",
        "description": "Returns a paginated list of encounters for the search filters, with viewer-scoped fields resolved from the optional identity.",
    },
    "rpc.tournament.list_matches": {
        "summary": "List matches",
        "description": "Returns a paginated list of matches for the search filters within the given workspace.",
    },
    "rpc.tournament.list_teams": {
        "summary": "List teams",
        "description": "Returns a paginated list of teams for the filter params within the given workspace.",
    },
    # ── computation job reads ──────────────────────────────────────────────
    "rpc.tournament.job_get": {
        "summary": "Get computation job",
        "description": "Returns one tournament computation job by id; requires the caller's standing-recalculate or stage-update permission on the job's tournament.",
    },
    "rpc.tournament.job_list": {
        "summary": "List computation jobs",
        "description": "Lists tournament computation jobs filtered by tournament/stage/active-only with a 1-100 limit; requires stage-read permission on the scoped tournament (superusers may list unscoped).",
    },
    # ── generic CRUD engine: tournament ────────────────────────────────────
    "rpc.tournament.admin.create#tournament": {
        "summary": "Create tournament",
        "description": "Creates a tournament; requires the tournament-create permission on the workspace supplied in the body.",
    },
    "rpc.tournament.admin.get#tournament": {
        "summary": "Get tournament (admin)",
        "description": "Returns one tournament by id for admin editing; requires tournament-read permission on its workspace.",
    },
    "rpc.tournament.admin.update#tournament": {
        "summary": "Update tournament",
        "description": "Updates a tournament by id; requires tournament-update permission on its workspace.",
    },
    "rpc.tournament.admin.delete#tournament": {
        "summary": "Delete tournament",
        "description": "Deletes a tournament by id (204 no body); requires tournament-delete permission on its workspace.",
    },
    # ── generic CRUD engine: team ──────────────────────────────────────────
    "rpc.tournament.admin.create#team": {
        "summary": "Create team",
        "description": "Creates a team; requires team-create permission on the workspace resolved from the body's tournament_id.",
    },
    "rpc.tournament.admin.get#team": {
        "summary": "Get team (admin)",
        "description": "Returns one team by id for admin editing; requires team-read permission on its workspace.",
    },
    "rpc.tournament.admin.update#team": {
        "summary": "Update team",
        "description": "Updates a team by id; requires team-update permission on its workspace.",
    },
    "rpc.tournament.admin.delete#team": {
        "summary": "Delete team",
        "description": "Deletes a team by id (204 no body); requires team-delete permission on its workspace.",
    },
    # ── generic CRUD engine: player ────────────────────────────────────────
    "rpc.tournament.admin.create#player": {
        "summary": "Create player",
        "description": "Creates a player; requires player-create permission on the workspace resolved from the body's tournament_id.",
    },
    "rpc.tournament.admin.update#player": {
        "summary": "Update player",
        "description": "Updates a player by id; requires player-update permission on its workspace.",
    },
    "rpc.tournament.admin.delete#player": {
        "summary": "Delete player",
        "description": "Deletes a player by id (204 no body); requires player-delete permission on its workspace.",
    },
    # ── generic CRUD engine: stage ─────────────────────────────────────────
    "rpc.tournament.admin.create#stage": {
        "summary": "Create stage",
        "description": "Creates a stage under a tournament; requires stage-create permission on the workspace resolved from the path tournament_id.",
    },
    "rpc.tournament.admin.get#stage": {
        "summary": "Get stage",
        "description": "Returns one stage by id; requires stage-read permission on its workspace.",
    },
    "rpc.tournament.admin.update#stage": {
        "summary": "Update stage",
        "description": "Updates a stage by id; requires stage-update permission on its workspace.",
    },
    "rpc.tournament.admin.delete#stage": {
        "summary": "Delete stage",
        "description": "Deletes a stage by id (204 no body); requires stage-delete permission on its workspace.",
    },
    "rpc.tournament.admin.list#stage": {
        "summary": "List stages (admin)",
        "description": "Lists all stages of a tournament; requires stage-read permission on the workspace resolved from the path tournament_id.",
    },
    # ── generic CRUD engine: stage_item / stage_item_input ─────────────────
    "rpc.tournament.admin.create#stage_item": {
        "summary": "Create stage item",
        "description": "Creates a stage item under a stage; requires stage-create permission on the workspace resolved from the path stage_id.",
    },
    "rpc.tournament.admin.update#stage_item": {
        "summary": "Update stage item",
        "description": "Updates a stage item by id; requires stage-update permission on its workspace.",
    },
    "rpc.tournament.admin.create#stage_item_input": {
        "summary": "Create stage item input",
        "description": "Creates a stage item input under a stage item; requires stage-create permission on the workspace resolved from the path stage_item_id.",
    },
    "rpc.tournament.admin.update#stage_item_input": {
        "summary": "Update stage item input",
        "description": "Updates a stage item input by id; requires stage-update permission on its workspace.",
    },
    # ── generic CRUD engine: encounter ─────────────────────────────────────
    "rpc.tournament.admin.create#encounter": {
        "summary": "Create encounter",
        "description": "Creates an encounter; requires match-create permission on the workspace resolved from the body's tournament_id.",
    },
    "rpc.tournament.admin.update#encounter": {
        "summary": "Update encounter",
        "description": "Updates an encounter by id; requires match-update permission on its workspace.",
    },
    "rpc.tournament.admin.delete#encounter": {
        "summary": "Delete encounter",
        "description": "Deletes an encounter by id (204 no body); requires match-delete permission on its workspace.",
    },
    # ── generic CRUD engine: standing ──────────────────────────────────────
    "rpc.tournament.admin.update#standing": {
        "summary": "Update standing",
        "description": "Updates a standing by id; requires standing-update permission on its workspace.",
    },
    "rpc.tournament.admin.delete#standing": {
        "summary": "Delete standing",
        "description": "Deletes a standing by id (204 no body); requires standing-delete permission on its workspace.",
    },
    # ── generic CRUD engine: player_sub_role ───────────────────────────────
    "rpc.tournament.admin.create#player_sub_role": {
        "summary": "Create player sub-role",
        "description": "Creates a custom player sub-role; requires player-create permission on the workspace supplied in the body.",
    },
    "rpc.tournament.admin.update#player_sub_role": {
        "summary": "Update player sub-role",
        "description": "Updates a player sub-role by id; requires player-update permission on its workspace.",
    },
    "rpc.tournament.admin.delete#player_sub_role": {
        "summary": "Delete player sub-role",
        "description": "Deactivates a player sub-role by id (204 no body); requires player-delete permission on its workspace.",
    },
    "rpc.tournament.admin.list#player_sub_role": {
        "summary": "List player sub-roles",
        "description": "Lists a workspace's player sub-roles, optionally filtered by role and including inactive ones; requires player-read permission on the workspace.",
    },
    # ── bespoke: tournament status / lifecycle ─────────────────────────────
    "rpc.tournament.tournament_finish": {
        "summary": "Toggle tournament finished",
        "description": "Toggles a tournament's legacy finished flag and returns it with stages; superuser-only.",
    },
    "rpc.tournament.tournament_status": {
        "summary": "Transition tournament status",
        "description": "Transitions a tournament to the requested status; requires tournament-update permission, and the force bypass is superuser-only.",
    },
    "rpc.tournament.tournament_schedule_set": {
        "summary": "Set tournament phase schedule",
        "description": "Replaces the tournament's phase schedule (full replace of REGISTRATION/CHECK_IN/DRAFT/LIVE rows); requires tournament-update permission.",
    },
    "rpc.tournament.standing_recalculate": {
        "summary": "Recalculate standings",
        "description": "Schedules a durable standings-recalculation job (202 Accepted) for the tournament; requires standing-recalculate permission.",
    },
    # ── bespoke: stage workflow ────────────────────────────────────────────
    "rpc.tournament.stage_progress": {
        "summary": "Get stage progress",
        "description": "Returns per-stage progress for a tournament; requires stage-read permission on its workspace.",
    },
    "rpc.tournament.stage_merge": {
        "summary": "Merge group stages",
        "description": "Merges source group stages into a target stage; requires stage-update permission on its workspace.",
    },
    "rpc.tournament.stage_activate": {
        "summary": "Activate stage",
        "description": "Activates a stage; requires stage-update permission on its workspace.",
    },
    "rpc.tournament.stage_generate": {
        "summary": "Generate stage bracket",
        "description": "Enqueues a bracket-generation job (202 Accepted) for the stage; requires stage-update permission on its workspace.",
    },
    "rpc.tournament.stage_activate_and_generate": {
        "summary": "Activate and generate stage",
        "description": "Enqueues a combined activate-and-generate bracket job (202 Accepted), honoring an optional force flag; requires stage-update permission on its workspace.",
    },
    "rpc.tournament.stage_wire": {
        "summary": "Wire stage from groups",
        "description": "Wires a target stage's slots from a source group stage's top placements; requires stage-update permission on its workspace.",
    },
    "rpc.tournament.stage_seed": {
        "summary": "Seed teams into stage",
        "description": "Seeds the given teams into a stage using the requested mode; requires stage-update permission on its workspace.",
    },
    # ── integrations: division grids ───────────────────────────────────────
    "rpc.tournament.grid_workspace_list": {
        "summary": "List workspace grids",
        "description": "Lists a workspace's division grids; requires division_grid-read permission and an authenticated user.",
    },
    "rpc.tournament.grid_workspace_create": {
        "summary": "Create division grid",
        "description": "Creates a division grid in a workspace; requires division_grid-create permission and an authenticated user.",
    },
    "rpc.tournament.grid_marketplace_workspaces": {
        "summary": "List marketplace source workspaces",
        "description": "Lists workspaces whose division grids can be imported into the target workspace; requires division_grid-read permission.",
    },
    "rpc.tournament.grid_marketplace_grids": {
        "summary": "List marketplace grids",
        "description": "Lists importable division grids from a source workspace; requires division_grid-read on the target and access to the source workspace.",
    },
    "rpc.tournament.grid_marketplace_import": {
        "summary": "Import marketplace grids",
        "description": "Imports selected division grids from a source workspace (copying assets via S3, 201 Created); requires division_grid-import permission on the target workspace.",
    },
    "rpc.tournament.grid_versions_list": {
        "summary": "List grid versions",
        "description": "Lists the versions of a division grid; requires division_grid-read permission on the grid's workspace.",
    },
    "rpc.tournament.grid_version_create": {
        "summary": "Create grid version",
        "description": "Creates a new version of a division grid (201 Created); requires division_grid-create permission on the grid's workspace.",
    },
    "rpc.tournament.grid_version_get": {
        "summary": "Get grid version",
        "description": "Returns one division grid version by id; requires an authenticated user but no workspace permission.",
    },
    "rpc.tournament.grid_version_update": {
        "summary": "Update grid version",
        "description": "Updates a division grid version by id; requires division_grid-update permission on the grid's workspace.",
    },
    "rpc.tournament.grid_version_delete": {
        "summary": "Delete grid version",
        "description": "Deletes a division grid version by id (204 no body); requires division_grid-delete permission on the grid's workspace.",
    },
    "rpc.tournament.grid_version_publish": {
        "summary": "Publish grid version",
        "description": "Publishes a division grid version; requires division_grid-publish permission on the grid's workspace.",
    },
    "rpc.tournament.grid_version_clone": {
        "summary": "Clone grid version",
        "description": "Clones a division grid version into a new draft (201 Created); requires division_grid-create permission on the grid's workspace.",
    },
    "rpc.tournament.grid_mapping_get": {
        "summary": "Get grid mapping",
        "description": "Returns the division mapping between a source and target grid version; requires an authenticated user but no workspace permission.",
    },
    "rpc.tournament.grid_mapping_put": {
        "summary": "Upsert grid mapping",
        "description": "Creates or updates the division mapping between two grid versions; requires division_grid-update permission on the source version's workspace.",
    },
    # ── integrations: Challonge ─────────────────────────────────────────────
    "rpc.tournament.challonge_fetch_tournament": {
        "summary": "Fetch Challonge tournament",
        "description": "Fetches a Challonge tournament by slug from the Challonge API; requires the global challonge-read permission.",
    },
    "rpc.tournament.challonge_fetch_participants": {
        "summary": "Fetch Challonge participants",
        "description": "Fetches a Challonge tournament's participants from the Challonge API; requires the global challonge-read permission.",
    },
    "rpc.tournament.challonge_fetch_matches": {
        "summary": "Fetch Challonge matches",
        "description": "Fetches a Challonge tournament's matches from the Challonge API; requires the global challonge-read permission.",
    },
    "rpc.tournament.challonge_import": {
        "summary": "Import from Challonge",
        "description": "Imports a tournament's bracket from Challonge, optionally as a dry run; requires challonge-sync permission on the tournament.",
    },
    "rpc.tournament.challonge_export": {
        "summary": "Export to Challonge",
        "description": "Exports a tournament's bracket to Challonge; requires challonge-sync permission on the tournament.",
    },
    "rpc.tournament.challonge_push_result": {
        "summary": "Push result to Challonge",
        "description": "Pushes a confirmed encounter result to Challonge and returns a status acknowledgment; requires challonge-sync permission on the encounter.",
    },
    "rpc.tournament.challonge_sync_log": {
        "summary": "Get Challonge sync log",
        "description": "Returns recent Challonge sync-log entries for a tournament (limit-bounded); requires challonge-read permission on the tournament.",
    },
    # ── integrations: Google Sheets ────────────────────────────────────────
    "rpc.tournament.sheet_get": {
        "summary": "Get Google Sheet feed",
        "description": "Returns a tournament's registration Google Sheets feed config, or null if none; requires team-read permission on the tournament.",
    },
    "rpc.tournament.sheet_upsert": {
        "summary": "Upsert Google Sheet feed",
        "description": "Creates or updates a tournament's registration Google Sheets feed config; requires team-import permission on the tournament.",
    },
    "rpc.tournament.sheet_sync": {
        "summary": "Sync Google Sheet feed",
        "description": "Syncs registrations from the configured Google Sheet and returns created/updated/withdrawn/skipped counts plus errors; requires team-import permission on the tournament.",
    },
    "rpc.tournament.sheet_mapping_catalog": {
        "summary": "Get sheet mapping catalog",
        "description": "Returns the available registration field mapping catalog (optionally with sheet headers); requires team-read permission on the tournament.",
    },
    "rpc.tournament.sheet_suggest_mapping": {
        "summary": "Suggest sheet mapping",
        "description": "Reads a source sheet and suggests a column-to-field mapping with detected headers; requires team-read permission on the tournament.",
    },
    "rpc.tournament.sheet_preview": {
        "summary": "Preview sheet mapping",
        "description": "Previews how sample sheet rows map to registrations under the given mapping config; requires team-read permission on the tournament.",
    },
    "rpc.tournament.sheet_players_export": {
        "summary": "Export sheet players",
        "description": "Exports a tournament's active registrations as a players payload; requires player-read permission on the tournament.",
    },
    # ── registration admin ─────────────────────────────────────────────────
    "rpc.tournament.reg_form_get": {
        "summary": "Get registration form (admin)",
        "description": "Returns a tournament's registration form config, or null if none; requires team-read permission on its workspace.",
    },
    "rpc.tournament.reg_form_upsert": {
        "summary": "Upsert registration form",
        "description": "Creates or replaces a tournament's registration form config (built-in and custom fields); requires team-import permission on its workspace.",
    },
    "rpc.tournament.reg_list": {
        "summary": "List registrations (admin)",
        "description": "Lists a tournament's registrations with status metadata and per-registration OW-rank snapshots, filtered by status/inclusion/source and optionally including deleted; requires team-read permission.",
    },
    "rpc.tournament.reg_create_manual": {
        "summary": "Create manual registration",
        "description": "Admin-creates a registration for a tournament (201 Created) and broadcasts a realtime change; requires team-import permission on its workspace.",
    },
    "rpc.tournament.reg_update": {
        "summary": "Update registration",
        "description": "Updates a registration's profile, roles, and statuses and broadcasts a realtime change; requires team-update permission on its workspace.",
    },
    "rpc.tournament.reg_approve": {
        "summary": "Approve registration",
        "description": "Approves a registration (recording the reviewer) and broadcasts a realtime change; requires team-import permission on its workspace.",
    },
    "rpc.tournament.reg_reject": {
        "summary": "Reject registration",
        "description": "Rejects a registration (recording the reviewer) and broadcasts a realtime change; requires team-import permission on its workspace.",
    },
    "rpc.tournament.reg_exclusion": {
        "summary": "Set registration exclusion",
        "description": "Sets a registration's exclude-from-balancer flag and reason and broadcasts a realtime change; requires team-update permission on its workspace.",
    },
    "rpc.tournament.reg_withdraw": {
        "summary": "Withdraw registration (admin)",
        "description": "Withdraws a registration and broadcasts a realtime change; requires team-update permission on its workspace.",
    },
    "rpc.tournament.reg_restore": {
        "summary": "Restore registration",
        "description": "Restores a withdrawn or rejected registration and broadcasts a realtime change; requires team-update permission on its workspace.",
    },
    "rpc.tournament.reg_delete": {
        "summary": "Delete registration",
        "description": "Soft-deletes a registration (204 no body) and broadcasts a realtime change; requires team-import permission on its workspace.",
    },
    "rpc.tournament.reg_bulk_approve": {
        "summary": "Bulk approve registrations",
        "description": "Approves multiple registrations by id, returning approved and skipped ids and broadcasting a realtime change; requires team-import permission on the tournament.",
    },
    "rpc.tournament.reg_set_balancer_status": {
        "summary": "Set balancer status",
        "description": "Sets a registration's balancer status and broadcasts a realtime change; requires team-update permission on its workspace.",
    },
    "rpc.tournament.reg_bulk_add_balancer": {
        "summary": "Bulk add to balancer",
        "description": "Adds multiple registrations to the balancer with a given status, returning updated/skipped counts and broadcasting a realtime change; requires team-import permission on the tournament.",
    },
    "rpc.tournament.reg_bulk_exclusion": {
        "summary": "Bulk set registration exclusion",
        "description": "Sets the exclude-from-balancer flag and reason on multiple registrations, returning updated/skipped counts and broadcasting a realtime change; requires team-update permission on the tournament.",
    },
    "rpc.tournament.reg_rank_autofill_preview": {
        "summary": "Preview rank autofill",
        "description": "Previews autofilling registration ranks from parsed OW data without writing; requires team-read permission on the tournament.",
    },
    "rpc.tournament.reg_rank_autofill_apply": {
        "summary": "Apply rank autofill",
        "description": "Autofills registration ranks from parsed OW data, persisting changes and broadcasting a realtime change; requires team-update permission on the tournament.",
    },
    "rpc.tournament.reg_user_rank_history": {
        "summary": "Get user rank history",
        "description": "Returns a user's balancer rank history within a workspace; requires team-read permission on the query workspace_id.",
    },
    "rpc.tournament.reg_export_users": {
        "summary": "Export registrations to users",
        "description": "Exports a tournament's approved registrations into user records and returns the result summary; requires team-import permission on its workspace.",
    },
    "rpc.tournament.reg_check_in": {
        "summary": "Toggle registration check-in",
        "description": "Checks a registration in or out (per the body flag) and broadcasts a realtime change; requires team-update permission on its workspace.",
    },
    # ── registration status catalog ────────────────────────────────────────
    "rpc.tournament.regstatus_catalog": {
        "summary": "Get status catalog",
        "description": "Returns the full registration status catalog (built-in plus custom) for a workspace; requires team-read permission on it.",
    },
    "rpc.tournament.regstatus_list": {
        "summary": "List custom statuses",
        "description": "Lists a workspace's custom registration statuses; requires team-read permission on it.",
    },
    "rpc.tournament.regstatus_create": {
        "summary": "Create custom status",
        "description": "Creates a custom registration status in a workspace (201 Created); requires team-update permission on it.",
    },
    "rpc.tournament.regstatus_update": {
        "summary": "Update custom status",
        "description": "Updates a custom registration status by id; requires team-update permission on its workspace.",
    },
    "rpc.tournament.regstatus_delete": {
        "summary": "Delete custom status",
        "description": "Deletes a custom registration status by id (204 no body); requires team-update permission on its workspace.",
    },
    "rpc.tournament.regstatus_builtin_upsert": {
        "summary": "Override built-in status",
        "description": "Creates or updates a workspace override (icon/color/name/description) for a built-in registration status identified by scope and slug; requires team-update permission.",
    },
    "rpc.tournament.regstatus_builtin_reset": {
        "summary": "Reset built-in status",
        "description": "Removes a workspace's override for a built-in registration status (204 no body), reverting to defaults; requires team-update permission.",
    },
    # ── public registration (captain / self-service) ──────────────────────
    "rpc.tournament.captain_my_role": {
        "summary": "Get my captain side",
        "description": "Returns the calling user's captain side (home/away) for an encounter, or null if they are not a captain; requires authentication.",
    },
    "rpc.tournament.captain_submit_result": {
        "summary": "Submit encounter result",
        "description": "Lets an encounter captain submit a home/away score and returns the updated result status; requires authentication.",
    },
    "rpc.tournament.captain_submit_match_report": {
        "summary": "Submit match report",
        "description": "Lets an encounter captain submit per-match scores and a closeness rating; requires authentication.",
    },
    "rpc.tournament.captain_confirm_result": {
        "summary": "Confirm encounter result",
        "description": "Lets the opposing captain confirm a submitted encounter result; requires authentication.",
    },
    "rpc.tournament.captain_dispute_result": {
        "summary": "Dispute encounter result",
        "description": "Lets an encounter captain dispute a submitted result with a reason; requires authentication.",
    },
    "rpc.tournament.captain_map_pool": {
        "summary": "Get encounter map pool",
        "description": "Returns the public map pool for an encounter; no authentication required.",
    },
    "rpc.tournament.captain_map_pool_state": {
        "summary": "Get map veto state",
        "description": "Returns the encounter's map-veto state; with optional auth the requesting captain's side is annotated, otherwise viewer_side is null.",
    },
    "rpc.tournament.captain_veto": {
        "summary": "Veto map",
        "description": "Lets a captain ban or pick a map in the encounter's veto and returns the updated pool entry; requires authentication.",
    },
    "rpc.tournament.reg_pub_form": {
        "summary": "Get public registration form",
        "description": "Returns the public registration form (with sub-role catalog) for a tournament, or null if none; no authentication required.",
    },
    "rpc.tournament.reg_pub_create": {
        "summary": "Submit registration",
        "description": "Lets a user self-register for a tournament (201 Created) after validating the form is open and the input; rejects duplicates with 409 and requires authentication.",
    },
    "rpc.tournament.reg_pub_get_me": {
        "summary": "Get my registration",
        "description": "Returns the calling user's registration for a tournament, or null if none; requires authentication.",
    },
    "rpc.tournament.reg_pub_update_me": {
        "summary": "Update my registration",
        "description": "Lets a user update their own still-pending registration after re-validating the input; requires authentication.",
    },
    "rpc.tournament.reg_pub_withdraw_me": {
        "summary": "Withdraw my registration",
        "description": "Withdraws the calling user's own registration and returns the new status; requires authentication.",
    },
    "rpc.tournament.reg_pub_check_in": {
        "summary": "Check in to tournament",
        "description": "Checks the calling user's own registration in, blocking when the form requires a confirmed-public OW profile that is private; requires authentication.",
    },
    "rpc.tournament.reg_pub_list": {
        "summary": "List public registrations",
        "description": "Returns the live public registration list for a tournament with tournament-history and division grids; no authentication required.",
    },
    # ── encounter saved-view writes ────────────────────────────────────────
    "rpc.tournament.saved_view_create": {
        "summary": "Save encounter view",
        "description": "Creates or upserts the calling user's saved encounter filter view in a workspace; requires authentication.",
    },
    "rpc.tournament.saved_view_delete": {
        "summary": "Delete saved view",
        "description": "Deletes the calling user's saved encounter view by id in a workspace (204 no body); requires authentication.",
    },
}
