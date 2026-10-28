"""Human-readable docs (summary + description) for tournament-service RPC
subjects, merged into the gateway's OpenAPI by the export script. Keyed by RPC
subject (generic-CRUD keys use "<subject>#<entity>"). Prose only — types live in
openapi_schemas.py. The gateway appends the RPC subject footer itself.
"""

from __future__ import annotations

# Shared sentences, so the subjects that share a rule word it once.
_CHALLONGE_ERRORS = (
    "Challonge failures are real HTTP errors: 404 `challonge_not_found` when Challonge does not know the tournament, "
    "503 `challonge_unavailable` when it is unreachable, times out, rate-limits or fails (5xx), 400 `challonge_error` "
    "when it refuses the request."
)
_GRID_VISIBLE = (
    "A grid, version or job the caller cannot see (another workspace's, unless the caller is a member or holds "
    "`division_grid.read` there) is 404, checked before the permission (403)."
)
_GRID_READ_ONLY = (
    "A system grid is read-only: a write to it, its versions or tiers is 403 with "
    "`details.fields[0].code = division_grid_read_only`, before the permission check."
)

DOCS: dict[str, dict] = {
    "rpc.tournament.team_format.get": {
        "summary": "Get a tournament's team format",
        "description": "Permission: workspace `tournament.read`. The tournament's own team format with its slot projection.",
    },
    "rpc.tournament.team_format.put": {
        "summary": "Replace a tournament's team format",
        "description": "Permission: workspace `tournament.update`. Replaces the tournament's team format; 409 while a draft is unfinished or teams hold slots; 422 with the `team_format_*` code when the format cannot be stored.",
    },
    # ── public reads (single object) ───────────────────────────────────────
    "rpc.tournament.get_tournament": {
        "summary": "Get tournament",
        "description": "Permission: public; no authentication required — a hidden tournament is visible only to its workspace's admins and users on its preview allowlist. Returns one tournament by id with optionally hydrated related entities selected via the entities query param.",
    },
    "rpc.tournament.get_team": {
        "summary": "Get team",
        "description": "Permission: public; no authentication required — a hidden tournament is visible only to its workspace's admins and users on its preview allowlist. Returns one team by id with optionally hydrated related entities (players, captain, tournament) selected via the entities query param.",
    },
    "rpc.tournament.get_encounter": {
        "summary": "Get encounter",
        "description": "Permission: public; no authentication required — a hidden tournament is visible only to its workspace's admins and users on its preview allowlist. Returns one encounter by id with optionally hydrated related entities selected via the entities query param.",
    },
    "rpc.tournament.get_match": {
        "summary": "Get match with stats",
        "description": "Permission: public; no authentication required — a hidden tournament is visible only to its workspace's admins and users on its preview allowlist. Returns one match by id: its participants (official result lines and observed team facts), every member, segment and fact at every grain, and optionally hydrated related entities, scoped to the given workspace.",
    },
    "rpc.tournament.get_match_kill_feed": {
        "summary": "Get match kill feed",
        "description": "Permission: public; no authentication required — a hidden tournament is visible only to its workspace's admins and users on its preview allowlist. Returns one match's whole event timeline in chronological order with the characters its events name, scoped to the given workspace; 404s when the match is outside that scope.",
    },
    "rpc.tournament.encounters_overview": {
        "summary": "Get encounters overview",
        "description": "Permission: public; no authentication required — an explicit tournament_id is visibility-gated against the caller, and an unfiltered overview counts publicly visible tournaments only. Takes the encounter list's filters and returns the browse's counts: the status segments (`all`, `live`, `upcoming`, `completed`; the status filter ignored, the toggles applied) and the toggles (`finals`, `upsets`, `with_logs`, `my_team`; every other filter applied, that toggle forced on — `my_team` is 0 without an identity), plus `completed_with_logs`, `recent_completed` (played in the last 7 days) and up to 4 encounters in play.",
    },
    "rpc.tournament.encounters_insights": {
        "summary": "Get encounters insights",
        "description": "Permission: public; no authentication required — an explicit tournament_id is visibility-gated against the caller, and an unfiltered read covers publicly visible tournaments only. Takes the encounter list's filters with the status forced to `completed` and returns their analytics: the count, average closeness (0..1) and its histogram in tenths, final score lines, the split by stage kind, the 6 most played maps, the 4 closest encounters, average series length, and — over the duels of more than one map (`multi_map`) — sweeps and series that went the distance.",
    },
    "rpc.tournament.statistics_overall": {
        "summary": "Get overall statistics",
        "description": "Permission: public; no authentication required. Returns aggregate tournament statistics across the workspace: counts of tournaments, teams, players and champions, plus played volume — finished encounters, maps, distinct calendar days covered (overlapping tournaments counted once) and whole hours of logged map time.",
    },
    # ── public reads (arrays) ──────────────────────────────────────────────
    "rpc.tournament.lookup_tournaments": {
        "summary": "Lookup tournaments",
        "description": "Permission: public; no authentication required — hidden tournaments, and every tournament of a hidden workspace, are never listed here, for any caller. Returns a lightweight id/name list of up to 500 most-recent tournaments, optionally filtered by workspace, league flag and installed discipline (an uninstalled code is 422), for pickers.",
    },
    "rpc.tournament.get_stages": {
        "summary": "List tournament stages",
        "description": "Permission: public; no authentication required — a hidden tournament is visible only to its workspace's admins and users on its preview allowlist. Returns all stages of a tournament ordered by stage order, with their items and item inputs hydrated.",
    },
    "rpc.tournament.get_standings": {
        "summary": "Get tournament standings",
        "description": "Permission: public; no authentication required — a hidden tournament is visible only to its workspace's admins and users on its preview allowlist. Returns the standings for a tournament with optionally hydrated related entities selected via the entities query param.",
    },
    # ── ffa lobbies ────────────────────────────────────────────────────────
    "rpc.tournament.ffa_stage": {
        "summary": "Get FFA stage lobbies",
        "description": (
            "Permission: public; no authentication required — a hidden tournament is visible only to its "
            "workspace's admins and users on its preview allowlist. Returns one lobby table per group of an "
            "ffa_league stage, in group order: the stage's scoring rules, every seated team with its running "
            "points and column sums, and one cell per planned game. Columns the organizer marked non-public "
            "are omitted here entirely — their sums and per-game values never leave the service. Positions "
            "come from the group's standings, so a stage nobody has ranked yet answers null positions in "
            "seat order."
        ),
    },
    "rpc.tournament.ffa_lobby": {
        "summary": "Get FFA lobby",
        "description": (
            "Permission: public; no authentication required — a hidden tournament is visible only to its "
            "workspace's admins and users on its preview allowlist. Returns one lobby's table, the same shape "
            "the stage read answers per group. 409 `ffa_not_a_lobby` when the encounter is a duel rather than a lobby."
        ),
    },
    "rpc.tournament.statistics_history": {
        "summary": "Get tournament history stats",
        "description": "Permission: public; no authentication required. Returns per-tournament historical statistics for the workspace; hidden tournaments and the tournaments of hidden workspaces are left out.",
    },
    "rpc.tournament.statistics_division": {
        "summary": "Get division statistics",
        "description": "Permission: public; no authentication required. Returns, for the tournaments of the game named by the required `discipline` query param (422 when absent, 404 `discipline_not_installed` for an unknown code), the average division per tournament keyed by the top-level role codes of that game's rated dimension (`role_avg_divs`; a role nobody played is absent), normalized against the workspace's division grid for that game with fallback to its global grid. Hidden tournaments and the tournaments of hidden workspaces are left out.",
    },
    "rpc.tournament.saved_views": {
        "summary": "List saved encounter views",
        "description": "Permission: any authenticated caller, self-service — only the caller's own views are returned (401 without an identity). Returns the calling user's saved encounter filter views for the workspace.",
    },
    # ── public reads (paginated) ───────────────────────────────────────────
    "rpc.tournament.list_tournaments": {
        "summary": "List tournaments",
        "description": "Permission: public; no authentication required — the page is filtered to the tournaments the viewer may see, so hidden ones surface only for their workspace's admins and preview-allowlisted users. Returns a paginated, sortable, searchable list of tournaments. `status` may be repeated (`?status=live&status=playoffs`) and matches any of the values. `per_page=-1` returns every matching row up to 500.",
    },
    "rpc.tournament.tournaments_facets": {
        "summary": "Tournament facet counts",
        "description": "Permission: public; no authentication required — every count is filtered to the tournaments the viewer may see. Returns chip counters for the tournaments list: unfiltered total/live plus per-status and league/standard counts, each axis counted without its own filter.",
    },
    "rpc.tournament.list_encounters": {
        "summary": "List encounters",
        "description": "Permission: public; no authentication required — an explicit tournament_id filter is visibility-gated against the caller, and an unfiltered page is restricted to publicly visible tournaments. Returns a paginated list of encounters for the search filters, with viewer-scoped fields resolved from the optional identity.",
    },
    "rpc.tournament.list_matches": {
        "summary": "List matches",
        "description": "Permission: public; no authentication required — an explicit tournament_id filter is visibility-gated against the caller, and an unfiltered page is restricted to publicly visible tournaments. Returns a paginated list of matches for the search filters within the given workspace.",
    },
    "rpc.tournament.list_teams": {
        "summary": "List teams",
        "description": "Permission: public; no authentication required — an explicit tournament_id filter is visibility-gated against the caller, and an unfiltered page is restricted to publicly visible tournaments. Returns a paginated list of teams for the filter params within the given workspace: every game's, or only the optional `discipline`'s (by the team's tournament; 422 for an unknown code). `sort=group` and `sort=placement` paginate like every other sort: teams without a group or placement come last, ties break on team id, and `total` and `only_count` count the same rows.",
    },
    # ── computation job reads ──────────────────────────────────────────────
    "rpc.tournament.job_get": {
        "summary": "Get computation job",
        "description": "Permission: workspace `standing.update` when the job's kind is 'standings', otherwise `stage.update`, on the workspace of the job's tournament. Returns one tournament computation job by id.",
    },
    "rpc.tournament.job_list": {
        "summary": "List computation jobs",
        "description": "Permission: workspace `stage.read` on the tournament the query scopes to; listing unscoped (neither `tournament_id` nor `stage_id`) is superuser-only. Lists tournament computation jobs filtered by tournament/stage/active-only with a 1-100 limit.",
    },
    # ── generic CRUD engine: tournament ────────────────────────────────────
    "rpc.tournament.admin.create#tournament": {
        "summary": "Create tournament",
        "description": "Permission: workspace `tournament.create`. Creates a tournament. A generated slug never takes one that a tournament holds or a slug redirect still serves.",
    },
    "rpc.tournament.admin.get#tournament": {
        "summary": "Get tournament (admin)",
        "description": "Permission: workspace `tournament.read`. Returns one tournament by id for admin editing.",
    },
    "rpc.tournament.admin.update#tournament": {
        "summary": "Update tournament",
        "description": "Permission: workspace `tournament.update`. Updates a tournament by id. Linking a Challonge slug fetches that tournament first: 404 `challonge_not_found` when Challonge does not know it, 503 `challonge_unavailable` when Challonge is unreachable, times out, rate-limits or fails.",
    },
    "rpc.tournament.admin.delete#tournament": {
        "summary": "Delete tournament",
        "description": "Permission: workspace `tournament.delete`. Deletes a tournament by id (204 no body).",
    },
    # ── bespoke: tournament cover/logo (binary upload + delete) ────────────
    "rpc.tournament.tournaments.image_upload": {
        "summary": "Upload tournament image",
        "description": "Permission: workspace `tournament.update` on the tournament's workspace. Uploads a tournament's cover or logo to S3 and stores its URL; the slot path segment is 'cover' or 'logo'. The gateway refuses a multipart body over 5 MiB + 64 KiB (400); an image over 5 MiB or a body that is not valid base64 is 422. The previous image's objects are deleted only after the new URL commits, and a failed cleanup is logged, not an error. Answers the tournament with `stages`, `roster_shape`, `division_grid_version` and `rules`.",
    },
    "rpc.tournament.tournaments.image_delete": {
        "summary": "Delete tournament image",
        "description": "Permission: workspace `tournament.update` on the tournament's workspace. Clears a tournament's cover or logo URL, commits, then removes its objects from S3; the slot path segment is 'cover' or 'logo'. A failed S3 delete is logged and the request still succeeds. Answers the tournament with `stages`, `roster_shape`, `division_grid_version` and `rules`.",
    },
    # ── generic CRUD engine: team ──────────────────────────────────────────
    "rpc.tournament.admin.create#team": {
        "summary": "Create team",
        "description": "Permission: workspace `team.create`. Creates a team.",
    },
    "rpc.tournament.admin.get#team": {
        "summary": "Get team (admin)",
        "description": "Permission: workspace `team.read`. Returns one team by id for admin editing.",
    },
    "rpc.tournament.admin.update#team": {
        "summary": "Update team",
        "description": "Permission: workspace `team.update`. Updates a team by id.",
    },
    "rpc.tournament.admin.delete#team": {
        "summary": "Delete team",
        "description": "Permission: workspace `team.delete`. Deletes a team by id (204 no body).",
    },
    # ── bespoke: team image (binary upload + delete) ───────────────────────
    "rpc.tournament.teams.image_upload": {
        "summary": "Upload team image",
        "description": "Permission: workspace `team.update` on the workspace resolved from the team's tournament. Uploads a team's image to S3 and stores its URL. The gateway refuses a multipart body over 5 MiB + 64 KiB (400); an image over 5 MiB or a body that is not valid base64 is 422. The previous image's objects are deleted only after the new URL commits, and a failed cleanup is logged, not an error.",
    },
    "rpc.tournament.teams.image_delete": {
        "summary": "Delete team image",
        "description": "Permission: workspace `team.update` on the workspace resolved from the team's tournament. Clears a team's image URL, commits, then removes its objects from S3; a failed S3 delete is logged and the request still succeeds.",
    },
    # ── bespoke: registered-team image (binary upload + delete) ────────────
    # Captain-gated, not workspace-permission-gated: a registration team belongs
    # to the players who formed it, not to the organizer's staff.
    "rpc.tournament.regteam_image_upload": {
        "summary": "Upload registered team image",
        "description": "Permission: self-service — that registration team's own captain or team manager, no workspace permission, and only while the team is still forming (mutable and unlocked). Uploads a registered team's image to S3 and stores its URL. The gateway refuses a multipart body over 5 MiB + 64 KiB (400); an image over 5 MiB or a body that is not valid base64 is 422. The previous image's objects are deleted only after the new URL commits, and a failed cleanup is logged, not an error.",
    },
    "rpc.tournament.regteam_image_delete": {
        "summary": "Delete registered team image",
        "description": "Permission: self-service — that registration team's own captain or team manager, no workspace permission, and only while the team is still forming (mutable and unlocked). Clears a registered team's image URL, commits, then removes its objects from S3; a failed S3 delete is logged and the request still succeeds.",
    },
    # ── generic CRUD engine: player ────────────────────────────────────────
    "rpc.tournament.admin.create#player": {
        "summary": "Create player",
        "description": "Permission: workspace `player.create`. Creates a player.",
    },
    "rpc.tournament.admin.update#player": {
        "summary": "Update player",
        "description": "Permission: workspace `player.update`. Updates a player by id.",
    },
    "rpc.tournament.admin.delete#player": {
        "summary": "Delete player",
        "description": "Permission: workspace `player.delete`. Deletes a player by id (204 no body).",
    },
    # ── generic CRUD engine: stage ─────────────────────────────────────────
    "rpc.tournament.admin.create#stage": {
        "summary": "Create stage",
        "description": "Permission: workspace `stage.create`. Creates a stage under a tournament.",
    },
    "rpc.tournament.admin.get#stage": {
        "summary": "Get stage",
        "description": "Permission: workspace `stage.read`. Returns one stage by id.",
    },
    "rpc.tournament.admin.update#stage": {
        "summary": "Update stage",
        "description": "Permission: workspace `stage.update`. Updates a stage by id.",
    },
    "rpc.tournament.admin.delete#stage": {
        "summary": "Delete stage",
        "description": "Permission: workspace `stage.delete`. Deletes a stage by id (204 no body).",
    },
    "rpc.tournament.admin.list#stage": {
        "summary": "List stages (admin)",
        "description": "Permission: workspace `stage.read`. Lists all stages of a tournament.",
    },
    # ── generic CRUD engine: stage_item / stage_item_input ─────────────────
    "rpc.tournament.admin.create#stage_item": {
        "summary": "Create stage item",
        "description": "Permission: workspace `stage.create`. Creates a stage item under a stage.",
    },
    "rpc.tournament.admin.update#stage_item": {
        "summary": "Update stage item",
        "description": "Permission: workspace `stage.update`. Updates a stage item by id.",
    },
    "rpc.tournament.admin.delete#stage_item": {
        "summary": "Delete stage item",
        "description": "Permission: workspace `stage.delete`. Deletes a stage item (group/bracket lane) by id, along with its own encounters and standings (204 no body).",
    },
    "rpc.tournament.admin.create#stage_item_input": {
        "summary": "Create stage item input",
        "description": "Permission: workspace `stage.create`. Creates a stage item input under a stage item. A `source_stage_item_id` that does not exist or belongs to another tournament is 400.",
    },
    "rpc.tournament.admin.update#stage_item_input": {
        "summary": "Update stage item input",
        "description": "Permission: workspace `stage.update`. Updates a stage item input by id. A `source_stage_item_id` that does not exist or belongs to another tournament is 400.",
    },
    "rpc.tournament.admin.delete#stage_item_input": {
        "summary": "Delete stage item input",
        "description": "Permission: workspace `stage.delete`. Deletes a stage item input (team slot) by id (204 no body).",
    },
    # ── generic CRUD engine: encounter ─────────────────────────────────────
    "rpc.tournament.admin.create#encounter": {
        "summary": "Create encounter",
        "description": "Permission: workspace `match.create`. Creates an encounter.",
    },
    "rpc.tournament.admin.update#encounter": {
        "summary": "Update encounter",
        "description": (
            "Permission: workspace `match.result` for the result fields (status, closeness, started_at, "
            "ended_at, current_map_index), `match.update` for every other field; a payload mixing both "
            "needs both. Updates an encounter by id. The scoreline is not here: it lives on the "
            "participations and only `encounter_set_result` writes it. Standings are recomputed only when "
            "the status, stage, stage item, round or `best_of` changes; any other edit only refreshes the "
            "encounter reads."
        ),
    },
    "rpc.tournament.admin.delete#encounter": {
        "summary": "Delete encounter",
        "description": "Permission: workspace `match.delete`. Deletes an encounter by id (204 no body).",
    },
    # ── encounter result (the single admin write + its audit trail) ────────
    "rpc.tournament.encounter_set_result": {
        "summary": "Set encounter result",
        "description": (
            "Permission: workspace `match.result` on the encounter's workspace. "
            "Confirms an encounter result in one transaction: the participations' scores, status, "
            "result_status, result_version and the audit row move together. `reason` is mandatory. Each "
            "`results` line names an `encounter_team_id` — never a side — with its score and optional "
            "placement; leave `results` empty and name `adopt_report_team_id` to take that participation's "
            "own report as truth instead, which resolves a dispute in one call. 422 when neither applies, "
            "and 422 `not_a_participation` when a line names an `encounter_team_id` that is not a live "
            "participation of this encounter. 409 when the result is already confirmed (reopen it first)."
        ),
    },
    "rpc.tournament.encounter_reopen_result": {
        "summary": "Reopen encounter result",
        "description": (
            "Permission: workspace `match.result` on the encounter's workspace. "
            "Un-confirms an encounter so it can be replayed or re-reported, clearing the participations' "
            "scores, closeness and confirmation, and cascading through anything the old result advanced. "
            "Team reports are kept. `reason` is mandatory — it is what the journal row carries. "
            "409 when there is no recorded result."
        ),
    },
    # ── per-map match edit (admin) ─────────────────────────────────────────
    "rpc.tournament.encounter_update_match": {
        "summary": "Update match",
        "description": (
            "Permission: workspace `match.result` on the workspace resolved from the match. "
            "Edits the observed score of any participant, addressed by encounter_team_id (422 for a seat the "
            "match does not have), and the nullable duration in seconds. "
            "The map must equal the bound game's existing map (409 otherwise). "
            "Team IDs, source, code, log_name and other unsupported fields are rejected with 422. "
            "Official game scores remain unchanged; score and duration changes carry separate native "
            "evidence records in the same transaction as the existing recalculation outbox."
        ),
    },
    "rpc.tournament.encounter_swap_slot": {
        "description": (
            "Permission: workspace `match.update` on the encounter's workspace. "
            "Swaps one of an encounter's team slots with another slot and answers with both encounters' "
            "resulting seats, so the bracket re-renders the pair without a refetch."
        ),
    },
    # ── match report form (per-tournament captain-report config) ───────────
    "rpc.tournament.report_form_get": {
        "summary": "Get match report form",
        "description": (
            "Permission: workspace `match.read` on the tournament's workspace. "
            "Returns the tournament's captain match-report form config: which built-in fields (closeness, "
            "map codes, comment) are enabled and required, plus any organizer-defined text fields. Always "
            "a complete config — a tournament that has never been configured answers the defaults rather "
            "than null."
        ),
    },
    "rpc.tournament.report_form_upsert": {
        "summary": "Upsert match report form",
        "description": (
            "Permission: workspace `match.update` on the tournament's workspace. "
            "Creates or replaces the tournament's captain match-report form config. Custom fields are text "
            "only, capped at 20, and their keys must be unique, slug-shaped and not collide with a built-in "
            "field name (422 otherwise). Rules apply to new submissions only; existing reports stay valid "
            "and readable."
        ),
    },
    "rpc.tournament.admin_matches_list": {
        "summary": "List parsed matches",
        "description": (
            "Permission: workspace `match.read` on the workspace named by `workspace_id`. "
            "Every observed duel map across the workspace, not one encounter: every game's, or only the "
            "optional `discipline`'s (422 for an unknown code); each row names its own `discipline`. "
            "Scores follow the bound game's historical slots; official game results are unchanged. "
            "`log_record` is its native ingest job and is null for observations with no raw provenance. "
            "Filter with `tournament_id`, `encounter_id`, `map_id`, `log_status`, `unlinked_only` and a "
            "free-text `query` over the actual ingest filename and team names. An empty `log_status` "
            "filters nothing, so observations without an ingest job stay visible."
        ),
    },
    "rpc.tournament.admin_match_get": {
        "summary": "Get a parsed match",
        "description": (
            "Permission: workspace `match.read` on the workspace named by `workspace_id`. "
            "One parsed map with the aggregates the list omits: the round count and how many "
            "statistics, kill-feed and event rows were written for it. Returns 404 both for an "
            "unknown match and for one outside the workspace named by `workspace_id`, so it cannot "
            "be used to probe for ids in another workspace."
        ),
    },
    "rpc.tournament.admin_encounter_reports_list": {
        "summary": "List captain reports",
        "description": (
            "Permission: workspace `match.read` on the workspace named by `workspace_id`. "
            "Every encounter in the workspace with the pair of captain reports filed against it. "
            "The row is the encounter, not the report, because a dispute spans two reports and the "
            "action that settles it is per-encounter. `scores_match` is null until both sides have "
            "reported \u2014 that is a different state from disagreeing. `series_score_valid` is "
            "advisory: reports predate per-round best-of, so a mismatch is information, not an error. "
            "Filter with `tournament_id`, `stage_id`, `result_status`, `mismatch_only`, "
            "`reported_count` and a free-text `query` over team and encounter names."
        ),
    },
    "rpc.tournament.admin_encounter_reports_stats": {
        "summary": "Captain report counters",
        "description": (
            "Permission: workspace `match.read` on the workspace named by `workspace_id`. "
            "Counts behind the list's filter chips. Scoped by `tournament_id`, `stage_id` and "
            "`query`, but deliberately NOT by the chip filters themselves \u2014 each chip reports "
            "how many rows it would select, so selecting one does not zero the others."
        ),
    },
    "rpc.tournament.encounter_result_audit": {
        "summary": "Get encounter result history",
        "description": (
            "Permission: workspace `match.read` on the encounter's workspace. "
            "Returns every recorded transition of the encounter's result, newest first. A null actor_user_id "
            "means a machine actor (Challonge import, bracket cascade)."
        ),
    },
    # ── ffa lobby results (the organizer's three levers) ──────────────────
    "rpc.tournament.ffa_game_results_set": {
        "summary": "Set FFA game results",
        "description": (
            "Permission: workspace `match.result` on the encounter's workspace. "
            "Records one game of a lobby: a line per seated team, every team exactly once, carrying one value "
            "per column of the stage. Placements are required when the stage's formula reads the place and "
            "derived from the game's points otherwise (ties share a place). Re-recording a confirmed position "
            "is a correction and needs a reason. The lobby completes itself when its confirmed games reach its "
            "games count, and reopens when they no longer do. Answers the lobby's settled table, with every "
            "column on it. 409 when a later stage has already been seeded from this group, and 409 "
            "`ffa_not_a_lobby` when the encounter is a duel rather than a lobby."
        ),
    },
    "rpc.tournament.ffa_game_cancel": {
        "summary": "Cancel FFA game",
        "description": (
            "Permission: workspace `match.result` on the encounter's workspace. "
            "Voids one game of a lobby, keeping it as history and freeing its position for a replay. Requires "
            "a reason. Answers the lobby's settled table — which may have reopened, since a voided game no "
            "longer counts towards the games count; a lobby it reopens retires every seat its old result "
            "advanced downstream, as `encounter_reopen_result` does. 409 `ffa_not_a_lobby` when the "
            "encounter is a duel rather than a lobby."
        ),
    },
    "rpc.tournament.ffa_games_count_set": {
        "summary": "Set FFA lobby games count",
        "description": (
            "Permission: workspace `match.update` on the encounter's workspace. "
            "Changes how many games THIS lobby plays. Never below the number it has already confirmed (422), "
            "since the games are the record. Answers the lobby's settled table, completed or reopened by the "
            "new count. A count that completes the lobby runs every effect of a confirmation (the completed "
            "event, bracket advance and standings, the Challonge push); one that reopens a confirmed lobby "
            "retires every seat its old result advanced downstream. 409 `ffa_not_a_lobby` when the encounter "
            "is a duel rather than a lobby."
        ),
    },
    "rpc.tournament.ffa_stage_admin": {
        "summary": "Get FFA stage lobbies (organizer view)",
        "description": (
            "Permission: workspace `match.result` on the tournament's workspace — whoever may record a "
            "result may read the values behind it. The same lobby tables as the public stage read, with the "
            "columns marked non-public still on them: that is what the result-entry dialog fills in. Not "
            "cached by the gateway. 401 without an identity."
        ),
    },
    # ── generic CRUD engine: standing ──────────────────────────────────────
    "rpc.tournament.admin.update#standing": {
        "summary": "Update standing",
        "description": "Permission: workspace `standing.update`. Updates a standing by id. Recomputes update changed rows in place, so a standing keeps its id, but the next recompute still overwrites an edited computed field.",
    },
    "rpc.tournament.admin.delete#standing": {
        "summary": "Delete standing",
        "description": "Permission: workspace `standing.delete`. Deletes a standing by id (204 no body).",
    },
    # ── generic CRUD engine: player_sub_role ───────────────────────────────
    "rpc.tournament.admin.create#player_sub_role": {
        "summary": "Create player sub-role",
        "description": "Permission: workspace `player.create`. Creates a custom player sub-role.",
    },
    "rpc.tournament.admin.update#player_sub_role": {
        "summary": "Update player sub-role",
        "description": "Permission: workspace `player.update`. Updates a player sub-role by id.",
    },
    "rpc.tournament.admin.delete#player_sub_role": {
        "summary": "Delete player sub-role",
        "description": "Permission: workspace `player.delete`. Deactivates a player sub-role by id (204 no body).",
    },
    "rpc.tournament.admin.list#player_sub_role": {
        "summary": "List player sub-roles",
        "description": "Permission: workspace `player.read`. Requires workspace_id; lists only that workspace's child roles — every installed game's, or only the optional `discipline`'s (422 `discipline_not_installed` for an unknown code) — optionally filtered by parent role (which needs `discipline`, else 422) and including inactive ones. Each row names its own `discipline`.",
    },
    # ── generic CRUD engine: tournament_link ───────────────────────────────
    "rpc.tournament.admin.create#tournament_link": {
        "summary": "Create tournament link",
        "description": "Permission: workspace `tournament_link.create`. Attaches one typed external link (Discord, stream, VOD, bracket, rules, other) to a tournament; Rejects a duplicate kind+url pair with 409. The tournament's public overview refreshes at once.",
    },
    "rpc.tournament.admin.update#tournament_link": {
        "summary": "Update tournament link",
        "description": "Permission: workspace `tournament_link.update`. Updates a tournament link by id; Rejects a duplicate kind+url pair with 409. The tournament's public overview refreshes at once.",
    },
    "rpc.tournament.admin.delete#tournament_link": {
        "summary": "Delete tournament link",
        "description": "Permission: workspace `tournament_link.delete`. Deactivates a tournament link by id (204 no body, soft delete via is_active). The tournament's public overview refreshes at once.",
    },
    "rpc.tournament.admin.list#tournament_link": {
        "summary": "List tournament links",
        "description": "Permission: workspace `tournament_link.read`. Lists a tournament's links ordered by sort_order then id, optionally only the active ones.",
    },
    # ── bespoke: tournament status / lifecycle ─────────────────────────────
    "rpc.tournament.tournament_finish": {
        "summary": "Toggle tournament finished",
        "description": "Permission: superuser only. Toggles a tournament's `is_finished` flag and returns it with stages.",
    },
    "rpc.tournament.tournament_status": {
        "summary": "Transition tournament status",
        "description": "Permission: workspace `tournament.update` on the tournament's workspace; the `force` flag additionally requires superuser. Transitions a tournament to the requested status.",
    },
    "rpc.tournament.tournament_schedule_set": {
        "summary": "Set tournament phase schedule",
        "description": "Permission: workspace `tournament.update` on the tournament's workspace. Replaces the tournament's phase schedule (full replace of REGISTRATION/CHECK_IN/DRAFT/LIVE rows).",
    },
    "rpc.tournament.standing_recalculate": {
        "summary": "Recalculate standings",
        "description": "Permission: workspace `standing.update` on the tournament's workspace. Schedules a durable standings-recalculation job (202 Accepted) for the tournament.",
    },
    "rpc.tournament.standing_pins_set": {
        "summary": "Set standings pins",
        "description": "Permission: workspace `standing.update` on the stage's workspace. Replaces every pin of one standings table (the stage plus body `stage_item_id`, null for an elimination stage): a pinned team keeps that place whatever results arrive later, the others fill the free places in computed order. An empty `pins` list unpins the table. 422 for a team outside the table or a place past its end; 409 when a playoff seeded from the group is under way and the change touches its qualifying places or removes a pin. Schedules the standings-recalculation job that applies them (202 Accepted).",
    },
    # ── preview access (who may see a hidden tournament before it is public) ─
    # Workspace-admin gated rather than tournament-permission gated: this grants
    # sight of an unpublished tournament, which no per-resource permission covers.
    "rpc.tournament.preview_access_list": {
        "summary": "List preview-access grants",
        "description": "Permission: workspace `owner`/`admin` role on the tournament's workspace (403 otherwise); no per-resource permission substitutes. Returns every account allowlisted to view a tournament while it is still hidden, as id/tournament_id/auth_user_id/created_at rows.",
    },
    "rpc.tournament.preview_access_add": {
        "summary": "Grant preview access",
        "description": "Permission: workspace `owner`/`admin` role on the tournament's workspace (403 otherwise). Allowlists one account (body `auth_user_id`, 422 when absent) to view a tournament before it is public and invalidates the cached tournament read so the change lands immediately.",
    },
    "rpc.tournament.preview_access_remove": {
        "summary": "Revoke preview access",
        "description": "Permission: workspace `owner`/`admin` role on the tournament's workspace (403 otherwise). Removes an account's preview allowlist entry (204 no body) and invalidates the cached tournament read.",
    },
    # ── bespoke: pick-ban live-session admin overrides (map + hero) ────────
    "rpc.tournament.admin_pick_ban_session_reset": {
        "summary": "Reset pick-ban session",
        "description": "Permission: workspace `match.result` on the encounter's workspace; on a mix match, its host or a co-host (or a superuser). Drops an encounter's pick-ban session (map or hero, per the body's `kind`) and its entries, re-creates them with freshly resolved seeds and returns the new room state.",
    },
    "rpc.tournament.admin_pick_ban_act": {
        "summary": "Act for a side",
        "description": "Permission: workspace `match.result` on the encounter's workspace; on a mix match, its host or a co-host (or a superuser). Performs one ban, pick or protect on behalf of the given side (admin override of the captain flow) against the current OPEN step, optionally naming the opponent roster player a per-player ban is spent on, and returns the full room state with nothing hidden. 400 when the current step is blind — use admin_pick_ban_submit for those. On a mix's member pick `member_id` names the member the hero is for (422 on a tournament match).",
    },
    "rpc.tournament.admin_pick_ban_submit": {
        "summary": "Submit a blind draft for a side",
        "description": "Permission: workspace `match.result` on the encounter's workspace; on a mix match, its host or a co-host (or a superuser). Replaces one side's draft on a BLIND step on behalf of an absent captain and, with `lock: true`, locks it; every side locked reveals the step. Returns the full room state with nothing hidden. 400 when the current step is not blind, when the side already locked, or when the items break the step's rules.",
    },
    "rpc.tournament.admin_pick_ban_reopen": {
        "summary": "Reopen the last revealed step",
        "description": "Permission: workspace `match.result` on the encounter's workspace; on a mix match, its host or a co-host (or a superuser). Voids the last fully revealed step's submissions and re-opens it for a fresh attempt — the organizer's version of a captain dispute, with no attempt budget and no `dispute.enabled` requirement. A reopened open (non-blind) step starts with an empty draft, the voided items available again, so its captain answers it afresh; a blind step's new drafts are prefilled with each side's previous items (still private until everyone locks). A reopened `side_pick` also takes back that game's sides and un-binds the round's side-bound steps, so the re-choice binds them afresh. Returns the new room state. 400 when there is no revealed step to reopen or a later step has already been acted in; 409 `side_locked` when the step is a `side_pick` whose game already has a claim or a confirmed result.",
    },
    "rpc.tournament.admin_pick_ban_elect_opener": {
        "summary": "Elect a round's opener for a side",
        "description": "Permission: workspace `match.result` on the encounter's workspace; on a mix match, its host or a co-host (or a superuser). Names who opens the round a `result_loser_choice` rotation is holding and appends it, on behalf of a losing captain who is unreachable; returns the new room state.",
    },
    # ── bespoke: the room's emergency controls ───────────────────────────
    "rpc.tournament.admin_pick_ban_pause": {
        "summary": "Pause or resume a pick-ban session",
        "description": "Permission: workspace `match.result` on the encounter's workspace; on a mix match, its host or a co-host (or a superuser). Freezes (`{kind, paused: true}`) or releases one kind's room and returns its state. A paused session has no deadline at all: the open step's timer stops, nothing auto-resolves, reveals or times out, and every CAPTAIN write (act, submit, dispute, undo, elect-opener) answers 409 `Pick-ban session is paused` while the admin overrides keep working. Resuming gives the step back exactly the time it had left; a step that opened during the pause gets its full timer. Idempotent, and 409 when no session of that kind exists or it is not active.",
    },
    "rpc.tournament.admin_pick_ban_extend": {
        "summary": "Extend the open step's timer",
        "description": "Permission: workspace `match.result` on the encounter's workspace; on a mix match, its host or a co-host (or a superuser). Adds `seconds` (10..3600) to the open step's clock by moving its start forward, and returns the room state. Allowed while paused. 409 when no session of that kind is active or the open step has no timer (an untimed or already settled step has nothing to extend).",
    },
    "rpc.tournament.admin_pick_ban_cancel": {
        "summary": "Cancel a pick-ban session",
        "description": "Permission: workspace `match.result` on the encounter's workspace; on a mix match, its host or a co-host (or a superuser). Retires one kind's session (body `{kind, reason}`) as CANCELLED and clears any pause, for a room whose veto cannot be played out. A cancelled HERO session simply stops opening rounds; a cancelled MAP session hands the series back to FREEPLAY — the maps it already settled keep their positions and every later one is named by the captains through `captain_select_game_map`. The way back is the session reset. 409 when no session of that kind exists or it is already cancelled.",
    },
    "rpc.tournament.admin_encounter_technical_loss": {
        "summary": "Record a technical loss",
        "description": "Permission: workspace `match.result` on the encounter's workspace. Ends the encounter against `loser_team_id` (a participation, never a side) without playing it out, in one transaction: every live pick-ban session is cancelled, every position that is not already CONFIRMED is cancelled, and the result is confirmed (same shape `encounter_set_result` returns). Omit `results` and the scores are derived — the winner takes `best_of // 2 + 1` wins or more if it already had them, the forfeiting participation keeps the maps it really won, capped one short of winning (a Bo5 standing 2:0 for the participation that forfeits is recorded 2:3). Explicit `results` must put the forfeiting participation below every other (422). Same guards as the result route: 409 on a preview bracket's encounter, on a result a later stage already consumed, and on an already confirmed result. `reason` is mandatory — a walkover is never anonymous.",
    },
    # ── bespoke: readiness override + the pre-game rooms board ────────────
    "rpc.tournament.admin_encounter_readiness_set": {
        "summary": "Force a captain's readiness",
        "description": "Permission: workspace `match.result` on the encounter's workspace; on a mix match, its host or a co-host (or a superuser). Sets one participation's captain readiness (body `{encounter_team_id, ready}`) for an organizer starting a match whose captain is unreachable, and answers `{readiness}` keyed by participation. Signals the room (`encounter:{id}:map-veto`) exactly as the captain's own ready does, so the other captains' screens move without a reload. 404 for an unknown encounter, 409 for a preview bracket's encounter, and 409 on `ready: false` once a pick-ban session of either kind exists — readiness gates session CREATION only, so clearing it afterwards would change nothing; reset the session instead. The readiness row stays unattributed (it names a player identity, which an organizer may not have); the admin audit records who forced it.",
    },
    "rpc.tournament.admin_pregame_rooms": {
        "summary": "List pre-game rooms",
        "description": "Permission: workspace `match.read` on the tournament's workspace. The organizer's board of every pre-game room of a tournament: one row per non-FFA encounter that resolves to a pooled pick-ban config or already has a session, carrying readiness, the map and hero session summaries (open step, acting sides, deadline), the series' game counts, a single `phase` (`teams_unknown`/`readiness`/`map`/`hero`/`report`/`done`/`idle`) and the `attention` flags staff act on (`game_disputed`, `result_disputed`, `awaiting_choice`, `overdue`, `late_not_ready`). Strictly read-only, unlike the room's own state read: it never creates a session, opens a position or settles an expired step, and it answers the whole tournament in a constant number of queries. Rows are ordered stage, round, encounter id; preview-bracket encounters with no session are omitted.",
    },
    "rpc.tournament.admin_pregame_room_history": {
        "summary": "Read a pre-game room's journal",
        "description": "Permission: workspace `match.read` on the encounter's workspace. One room's whole story, newest first: the pre-game journal (readiness, session opened/reset/completed, rounds, every captain and organizer action, step reveals, timeouts, disputes, undo, map and series reports, pause/extend/cancel/technical loss) merged with the encounter's result audit (confirm, reopen, auto_confirm, auto_dispute, auto_pending, import, cascade_reset, game_confirm, game_correct, game_cancel). Each entry carries `id` (`room:<id>`/`result:<id>`), `at`, `origin`, `action`, `kind`, `source` (`captain`/`admin`/`system`), `side`, `actor_auth_user_id`, `actor_name` (null for machine actors), `reason` and an action-specific `data` object. Query `limit` is clamped to 1..500, default 200. The journal is keyed by ENCOUNTER, so resetting a session never erases what it did.",
    },
    # ── bespoke: admin correction of one series position's result ──────────
    "rpc.tournament.admin_game_result": {
        "summary": "Correct a game result",
        "description": "Permission: workspace `match.result` on the encounter's workspace. Writes one series position's numbers as an `admin` result — one `results` line per live participation (`encounter_team_id`, optional score, placement and `column_values`) — and journals the mandatory `reason`; this is the only way a `confirmed` game (locked against captains with 409 `result_locked`) ever changes. When the room's result rotation (`result_*` first-ban rotation) opened the next round off this position and the correction changes who opens it, that round is scrapped and re-opened for the corrected opener in the same commit — provided nobody used it yet; 409 `dependent_round_started` (nothing written, no audit row) when it was already used: a submission on one of its steps, or its game given a side, claimed or confirmed. The way out is to undo that round (captains) or reset the room first. The response is `{game, reset_downstream}`. Also 409 `side_pick_pending` while the position's side step is open, 409 `side_pick_required` while a room that picks this game's sides left them incomplete, 409 `map_not_selected` while the position still has no map (an organizer names it through the pick-ban or the captain map choice first), and 404 when the game belongs to another encounter or is cancelled. When the encounter is confirmed after the correction and linked to a Challonge match, the corrected result is queued for the push to Challonge.",
    },
    # ── a game's match imported by external id (src/rpc/match_import.py) ──
    "rpc.tournament.captain_match_import": {
        "summary": "Import a game's match by its external id",
        "description": (
            "Permission: authenticated user who captains one of the encounter's live teams (403 otherwise). Body "
            "`{external_id}`: the game's match as its discipline's source names it. The stats service fetches it, "
            "retrying with backoff for 24 h while the source does not serve it yet, then stores it like an uploaded "
            "log and ingests it as evidence for this game (binding, `logs_official` and evidence rules unchanged). "
            "Returns the request `{id, status (pending|done|failed), attempts, last_error, external_id, created_at, "
            "warnings}`; re-submitting the same id for the same game returns it, a failed one restarts. 422 "
            "`unsupported_ingestor` when the encounter's discipline has no match source, 422 `invalid_external_id`, "
            "422 `match_import_tournament_only` outside tournaments (mix, scrim), 404 when the game belongs to "
            "another encounter or is cancelled, 409 `match_already_imported` when another game of the workspace "
            "holds the same match, 503 when the stats service is unreachable."
        ),
    },
    "rpc.tournament.captain_match_imports": {
        "summary": "List a game's match imports",
        "description": (
            "Permission: authenticated captain of one of the encounter's live teams. The game's import requests, "
            "newest first, shaped like the submit's answer; `warnings` is always empty on this read."
        ),
    },
    "rpc.tournament.admin_match_import": {
        "summary": "Import a game's match by its external id (organizer)",
        "description": (
            "Permission: workspace `match.result` on the encounter's workspace. Same request and refusals as the "
            "captain submission."
        ),
    },
    "rpc.tournament.admin_match_imports": {
        "summary": "List a game's match imports with warnings (organizer)",
        "description": (
            "Permission: workspace `match.read` on the encounter's workspace. The game's import requests, newest "
            "first, each with its organizer `warnings`, derived on read: `fetch_failed` (the request gave up; "
            "`last_error` says why), `participants_dropped` (`count` players fewer than the tournament format's "
            "starters were observed on the game's teams, e.g. anonymous accounts the decoder dropped) and "
            "`banned_character_played` (`characters` the observation shows that this game's hero room banned). "
            "Warnings never change a result."
        ),
    },
    # ── bespoke: generic pick-ban config CRUD (map + hero) ──────────────────
    "rpc.tournament.admin_pick_ban_config_list": {
        "summary": "List pick-ban configs",
        "description": "Permission: workspace `match.update` on the tournament's workspace (this read is gated on the write action, like its sibling config writes). Returns all pick-ban configs of a tournament for both kinds (map, hero), cascade levels ordered kind, stage, round.",
    },
    "rpc.tournament.admin_pick_ban_config_upsert": {
        "summary": "Upsert pick-ban config",
        "description": 'Permission: workspace `match.update` on the tournament\'s workspace. Creates or replaces the pick-ban config for one (kind, tournament, stage or stage+round) cascade level after validating the ruleset document and the item pool. A ruleset with validation errors is a 422 whose `details.fields[0]` carries `code: "ruleset_invalid"` plus an `issues` array of `{path, code, severity, message}` — the same issue objects admin_pick_ban_rules_validate returns — so the constructor can highlight the offending fields. A hero config whose ruleset holds a `side_pick` step but whose pool is empty is a 422 `pool_required` (save the champion pool first: a pool-less room never opens, yet its side step would hold the result of every game); a pool item that is not a catalog row of the game of the tournament and of the catalog of the kind is a 422 `pool_item_not_in_catalog`. A map config of a game that declares the `mode` kind may also name its modes in the flat `item_ids` (never in slots): ingested logs of another mode are then refused (`mode_not_in_pool`), maps are checked against the map items alone, and the room vetoes the map items only (a pool of only modes opens no room, like a rules template).',
    },
    "rpc.tournament.admin_pick_ban_rules_validate": {
        "summary": "Validate a pick-ban ruleset",
        "description": "Permission: workspace `match.update` on the tournament's workspace (gated like the upsert it precedes). Runs the ruleset engine over a candidate document for the given `kind`/`mode` and returns `{valid, issues}`; unlike the upsert it never errors on a bad ruleset — warnings ride along with the errors and only errors clear `valid`.",
    },
    "rpc.tournament.admin_pick_ban_rules_preview": {
        "summary": "Preview a pick-ban series",
        "description": 'Permission: workspace `match.update` on the tournament\'s workspace (gated like the upsert it precedes). Resolves every map of a best-of series against a candidate ruleset and the pool it would be played out of, returning per map the resolved steps, the new and cumulative active ban counts, and (hero kind) the fewest items that can be left per group — the answer to "how many supports survive map 5" before a tournament runs on the rules.',
    },
    "rpc.tournament.admin_pick_ban_config_delete": {
        "summary": "Delete pick-ban config",
        "description": "Permission: workspace `match.update` on the workspace of the config's tournament. Deletes a pick-ban config by id (running sessions keep their snapshot).",
    },
    # ── bespoke: scrim rooms ───────────────────────────────────────────────
    "rpc.tournament.scrim_create": {
        "summary": "Create scrim room",
        "description": "Permission: authenticated user who is a member of the target workspace (membership only — no resource grant is checked; superusers pass). Creates an ad-hoc pre-game room outside any tournament: the workspace's hidden scrims container (lazily), an isolating stage, that stage's map and optional hero pick-ban configs either copied from an existing tournament round or authored ad hoc, both teams and the encounter; returns the room with its share token. 409s when the caller's active-room cap is reached.",
    },
    "rpc.tournament.scrim_list_mine": {
        "summary": "List scrim rooms",
        "description": "Permission: authenticated user who is a member of the queried workspace (membership only — no resource grant is checked), plus workspace `match.result` when `scope=workspace`; 401 without an identity. Returns the calling user's scrim rooms in a workspace, open and closed alike (scrim history is kept forever); `scope=workspace` instead returns every room of the workspace so staff can find one they neither created nor play, same open-first ordering.",
    },
    "rpc.tournament.scrim_get": {
        "summary": "Get scrim room",
        "description": "Permission: authentication optional — the room is gated by the ordinary visibility rules of its hidden scrims container, not by holding the token. Returns one scrim room by share token, annotating the requesting viewer's captain side and whether they may still claim the free one; visible only to a participant, a workspace insider or a preview-allowlisted user, everyone else gets 404.",
    },
    "rpc.tournament.scrim_claim": {
        "summary": "Claim a scrim side",
        "description": "Permission: authenticated member of the room's workspace plus the room's share token (membership only — no resource grant is checked). Claims the scrim room's free captain side for the calling user and grants them preview access to the hidden scrims container, so the pre-game room resolves their side from then on; idempotent and first-writer-wins, 409 once both sides are taken.",
    },
    "rpc.tournament.scrim_close": {
        "summary": "Close scrim room",
        "description": "Permission: self-service — the room's creator, a captain of either side, a superuser, or workspace staff holding `match.result` (plain workspace membership is not enough). Closes a scrim room so it stops counting against its creator's active-room cap, leaving the encounter and its pick-ban history readable by the participants forever. The same rule is surfaced per room as `can_close`.",
    },
    # ── bespoke: stage workflow ────────────────────────────────────────────
    "rpc.tournament.stage_progress": {
        "summary": "Get stage progress",
        "description": "Permission: workspace `stage.read` on the tournament's workspace. Returns per-stage progress for a tournament.",
    },
    "rpc.tournament.stage_planned_rounds": {
        "summary": "Get stage planned rounds",
        "description": "Permission: workspace `stage.read` on the stage's workspace. Returns the round numbers a stage's bracket has (once generated) or will have, predicted from its planned team inputs.",
    },
    "rpc.tournament.stage_bracket_preview": {
        "summary": "Preview stage bracket",
        "description": "Permission: workspace `stage.read` on the stage's workspace. Returns the bracket a stage would generate — the real generator's pairings, seed order, advancement edges and per-round best-of, with skeleton-local ids because nothing is written; wired teams appear by name, an unseeded playoff is projected from the preceding group stage.",
    },
    "rpc.tournament.stage_bracket_preview_public": {
        "summary": "Preview stage bracket (public)",
        "description": "Permission: public; no authentication required — a hidden tournament is visible only to its workspace's admins and users on its preview allowlist, and a stage of another tournament is a 404. The same read-only skeleton as the admin bracket preview, for drawing an elimination stage whose matches are not generated yet.",
    },
    "rpc.tournament.stage_bracket_template_get": {
        "summary": "Read a stage's bracket layout",
        "description": "Permission: workspace `stage.read`. The stage's custom bracket template, or the one its format would generate for the current seed counts, plus those counts.",
    },
    "rpc.tournament.stage_bracket_template_set": {
        "summary": "Save a custom bracket layout",
        "description": 'Permission: workspace `stage.update`. Validates the template (spec rules) and stores it; refused with 409 while the stage has matches. An invalid template is a 422 whose `details.fields[0]` carries `code: "invalid_bracket_template"` plus a `problems` array of `{match_id, slot, code, message}`.',
    },
    "rpc.tournament.stage_bracket_template_clear": {
        "summary": "Reset to the generated bracket layout",
        "description": "Permission: workspace `stage.update`. Drops the custom template; refused with 409 while the stage has matches.",
    },
    "rpc.tournament.stage_merge": {
        "summary": "Merge group stages",
        "description": "Permission: workspace `stage.update` on the target stage's workspace. Merges source group stages into a target stage.",
    },
    "rpc.tournament.stage_activate": {
        "summary": "Activate stage",
        "description": "Permission: workspace `stage.update` on the stage's workspace. Activates a stage.",
    },
    "rpc.tournament.stage_deactivate": {
        "summary": "Deactivate stage",
        "description": "Permission: workspace `stage.update` on the stage's workspace. Reverts an accidentally-activated stage back to Draft/preview; refuses (409) once any of its matches has been reported or started.",
    },
    "rpc.tournament.stage_generate": {
        "summary": "Generate stage bracket",
        "description": "Permission: workspace `stage.update` on the stage's workspace. Enqueues a bracket-generation job (202 Accepted) for the stage.",
    },
    "rpc.tournament.stage_apply_best_of": {
        "summary": "Apply best-of to existing matches",
        "description": "Permission: workspace `stage.update` on the stage's workspace. Rewrites best_of on the stage's existing encounters from the stage's best-of config (in place, preserving scores).",
    },
    "rpc.tournament.stage_activate_and_generate": {
        "summary": "Activate and generate stage",
        "description": "Permission: workspace `stage.update` on the stage's workspace (the optional force flag needs no extra grant). Enqueues a combined activate-and-generate bracket job (202 Accepted), honoring an optional force flag.",
    },
    "rpc.tournament.stage_auto_wire": {
        "summary": "Auto-wire stage from groups",
        "description": "Permission: workspace `stage.update` on the stage's workspace. Wires the stage's TENTATIVE inputs from a round-robin/Swiss stage's \"Teams advancing to playoff\" count — the same auto-wire Activate & generate runs automatically, exposed standalone for preview/debugging. The source is the one group stage of the latest earlier phase; pass source_stage_id to name it when that phase runs several divisions in parallel (a value that is not an integer is 422 `invalid_query_param`).",
    },
    "rpc.tournament.stage_wire": {
        "summary": "Wire stage from groups",
        "description": "Permission: workspace `stage.update` on the target stage's workspace. Wires a target stage's slots from a source group stage's top placements.",
    },
    "rpc.tournament.stage_seed": {
        "summary": "Seed teams into stage",
        "description": "Permission: workspace `stage.update` on the stage's workspace. Seeds the given teams into a stage using the requested mode. Takes the stage's row lock like every other stage writer; 409 when the stage already has generated matches (delete them first to edit the bracket).",
    },
    # ── integrations: division grids ───────────────────────────────────────
    "rpc.tournament.grid_workspace_list": {
        "summary": "List workspace grids",
        "description": "Permission: workspace `division_grid.read`. Lists a workspace's division grids, each with `tournament_count`: the tournaments pinned to any of its versions.",
    },
    "rpc.tournament.grid_workspace_create": {
        "summary": "Create division grid",
        "description": "Permission: workspace `division_grid.create`. Creates a division grid in a workspace. `slug` is optional: when omitted it is derived as `{discipline}-grid`, then `-2`, `-3`… With `from_version_id` (a published version of this workspace's or a system grid of the same game; 404 for another workspace's version, 422 `division_grid_discipline_mismatch` for another game, 409 for an unpublished one) v1 is a published copy of that version's tiers and label; otherwise v1 is the game's native ladder, and a game without one starts with no version. Never activates anything.",
    },
    "rpc.tournament.grid_update": {
        "summary": "Update division grid metadata",
        "description": "Permission: workspace `division_grid.update` on the grid's workspace, or `division_grid.delete` when the body archives it (`archived: true`). Renames, archives, or restores a workspace-owned division grid. "
        + _GRID_VISIBLE
        + " "
        + _GRID_READ_ONLY,
    },
    "rpc.tournament.grid_portable_export": {
        "summary": "Export a portable division grid",
        "description": "Permission: workspace `division_grid.read` on the grid's workspace. Exports every version and slug-based mapping as a portable division-grid/v1 document. "
        + _GRID_VISIBLE,
    },
    "rpc.tournament.grid_portable_import": {
        "summary": "Import a portable division grid",
        "description": "Permission: workspace `division_grid.create` on the target workspace. Imports a validated division-grid/v1 document in library, sync, or copy mode. Every version in the document is validated before anything is written: 400 with the create-version messages (at least one tier, duplicate slug or sort order, an invalid rank range, more than one open-ended tier).",
    },
    "rpc.tournament.grid_marketplace_workspaces": {
        "summary": "List marketplace source workspaces",
        "description": "Permission: workspace `division_grid.read` on the target workspace. Lists workspaces whose division grids can be imported into the target workspace.",
    },
    "rpc.tournament.grid_marketplace_grids": {
        "summary": "List marketplace grids",
        "description": "Permission: workspace `division_grid.read` on the target workspace; a hidden source workspace additionally requires membership of it or superuser (404 otherwise). Lists importable division grids from a source workspace.",
    },
    "rpc.tournament.grid_marketplace_preflight": {
        "summary": "Preflight marketplace grid import",
        "description": "Permission: workspace `division_grid.create` on the target workspace; a hidden source workspace additionally requires membership of it or superuser (404 otherwise). Reports conflicts, asset policy, operation counts, and a stable source fingerprint without writing data. 404 when a selected version is not in the selected grid.",
    },
    "rpc.tournament.grid_marketplace_import": {
        "summary": "Queue marketplace grid import",
        "description": "Permission: workspace `division_grid.create` on the target workspace; a hidden source workspace additionally requires membership of it or superuser (404 otherwise). Creates or reuses an idempotent background import job (202 Accepted). 404 when a selected version is not in the selected grid. The job fails as a conflict (409) when the source's provenance no longer matches or a concurrent import changed this workspace's imports, and as 404 when its source or target workspace is gone; its `error` carries the message. A job still running 15 minutes after it started is requeued.",
    },
    "rpc.tournament.grid_import_job_get": {
        "summary": "Get division grid import job",
        "description": "Permission: workspace `division_grid.read` on the job's workspace. Returns durable progress, result, and failure details for one workspace import job. "
        + _GRID_VISIBLE,
    },
    "rpc.tournament.grid_import_jobs_list": {
        "summary": "List division grid import jobs",
        "description": "Permission: workspace `division_grid.read`. Lists recent workspace import jobs, optionally restricted to pending and running jobs.",
    },
    "rpc.tournament.grid_versions_list": {
        "summary": "List grid versions",
        "description": "Permission: workspace `division_grid.read` on the grid's workspace. Lists the versions of a division grid. "
        + _GRID_VISIBLE,
    },
    "rpc.tournament.grid_version_create": {
        "summary": "Create grid version",
        "description": "Permission: workspace `division_grid.create` on the grid's workspace. Creates a new version of a division grid (201 Created). "
        + _GRID_VISIBLE
        + " "
        + _GRID_READ_ONLY,
    },
    "rpc.tournament.grid_version_get": {
        "summary": "Get grid version",
        "description": "Permission: authenticated user who can see the version: any authenticated user for a system grid (no workspace); for a workspace-owned grid, a member of that workspace or a holder of `division_grid.read` there (superusers pass). 404 for anyone else. Returns one division grid version by id.",
    },
    "rpc.tournament.grid_version_update": {
        "summary": "Update grid version",
        "description": "Permission: workspace `division_grid.update` on the grid's workspace. Updates a division grid version by id. "
        + _GRID_VISIBLE
        + " "
        + _GRID_READ_ONLY,
    },
    "rpc.tournament.grid_version_delete": {
        "summary": "Delete grid version",
        "description": "Permission: workspace `division_grid.delete` on the grid's workspace. Deletes a division grid version by id (204 no body). "
        + _GRID_VISIBLE
        + " "
        + _GRID_READ_ONLY,
    },
    "rpc.tournament.grid_delete": {
        "summary": "Delete division grid",
        "description": "Permission: workspace `division_grid.delete` on the grid's workspace. Hard-deletes a division grid and its versions/tiers/mappings (204 no body); refuses the workspace default or grids whose versions are used by tournaments. "
        + _GRID_VISIBLE
        + " "
        + _GRID_READ_ONLY,
    },
    "rpc.tournament.grid_version_publish": {
        "summary": "Publish grid version",
        "description": "Permission: workspace `division_grid.update` on the grid's workspace. Publishes a division grid version. "
        + _GRID_VISIBLE
        + " "
        + _GRID_READ_ONLY,
    },
    "rpc.tournament.grid_version_readiness": {
        "summary": "Check grid activation readiness",
        "description": "Permission: workspace `division_grid.read`. Checks that mappings from every version used by workspace tournaments to the target version are complete. 404 for another workspace's version.",
    },
    "rpc.tournament.grid_version_activate": {
        "summary": "Activate a published grid version",
        "description": "Permission: workspace `division_grid.update`. Atomically checks mapping readiness and assigns the published version as the workspace default. 404 for another workspace's version. A system grid's version may be activated: this writes only the workspace's own default, never the system grid.",
    },
    "rpc.tournament.grid_save": {
        "summary": "Save the workspace division grid",
        "description": "Permission: workspace `division_grid.update`. Server-authoritative save: applies cosmetic edits in place, or spawns a new version, auto-generates mappings from every used source version, and auto-activates when complete, but only if the grid already holds the workspace's active version for its game (another grid is activated explicitly). A `grid_id` of another workspace is 404. "
        + _GRID_READ_ONLY,
    },
    "rpc.tournament.grid_version_clone": {
        "summary": "Clone grid version",
        "description": "Permission: workspace `division_grid.create` on the grid's workspace. Clones a division grid version into a new draft (201 Created). "
        + _GRID_VISIBLE
        + " "
        + _GRID_READ_ONLY,
    },
    "rpc.tournament.grid_mapping_get": {
        "summary": "Get grid mapping",
        "description": "Permission: authenticated user who can see BOTH versions — any authenticated user for a system grid; for a workspace-owned grid, a member of that workspace or a holder of `division_grid.read` there (404 otherwise). Returns the division mapping between a source and target grid version.",
    },
    "rpc.tournament.grid_mapping_put": {
        "summary": "Upsert grid mapping",
        "description": "Permission: workspace `division_grid.update` on the source version's workspace, plus read access to the target version (a member of its workspace or a holder of `division_grid.read` there, or a system grid; 404 otherwise). Creates or updates the division mapping between two grid versions. The mapping belongs to the source version's workspace, so a workspace may map its own versions onto a system version (what activating that system version needs); a mapping from a system version is 403 with `details.fields[0].code = division_grid_read_only`.",
    },
    # ── integrations: Challonge ─────────────────────────────────────────────
    "rpc.tournament.challonge_fetch_tournament": {
        "summary": "Fetch Challonge tournament",
        "description": "Permission: global `challonge.read`. Fetches a Challonge tournament by slug from the Challonge API. "
        + _CHALLONGE_ERRORS,
    },
    "rpc.tournament.challonge_fetch_participants": {
        "summary": "Fetch Challonge participants",
        "description": "Permission: global `challonge.read`. Fetches a Challonge tournament's participants from the Challonge API. "
        + _CHALLONGE_ERRORS,
    },
    "rpc.tournament.challonge_fetch_matches": {
        "summary": "Fetch Challonge matches",
        "description": "Permission: global `challonge.read`. Fetches a Challonge tournament's matches from the Challonge API. "
        + _CHALLONGE_ERRORS,
    },
    "rpc.tournament.challonge_import": {
        "summary": "Import from Challonge",
        "description": "Permission: workspace `challonge.update` on the tournament's workspace. Imports a tournament's bracket from Challonge, optionally as a dry run. A match Challonge did not change writes nothing (no sync-log row, no recompute, no cache invalidation) and counts as skipped; `matches_synced` counts real writes only. 404 when the tournament does not exist, 422 when it has no Challonge source, 409 while an import or export of it is already running (the request waits up to 3 s for it). "
        + _CHALLONGE_ERRORS
        + " Metered: a 429 reports `code=rate_limited` with the exceeded limit in `details.limit_name`.",
    },
    "rpc.tournament.challonge_export": {
        "summary": "Export to Challonge",
        "description": "Permission: workspace `challonge.update` on the tournament's workspace. Exports a tournament's bracket to Challonge. 404 when the tournament does not exist, 422 when it has no Challonge source, 409 while an import or export of it is already running (the request waits up to 3 s for it). "
        + _CHALLONGE_ERRORS
        + " Metered: a 429 reports `code=rate_limited` with the exceeded limit in `details.limit_name`.",
    },
    "rpc.tournament.challonge_push_result": {
        "summary": "Push result to Challonge",
        "description": "Permission: workspace `challonge.update` on the encounter's workspace. Pushes a confirmed encounter result to Challonge and returns a status acknowledgment. "
        + _CHALLONGE_ERRORS,
    },
    "rpc.tournament.challonge_sync_log": {
        "summary": "Get Challonge sync log",
        "description": "Permission: workspace `challonge.read` on the tournament's workspace. Returns the tournament's newest Challonge sync-log entries, `limit` of them (default 50, clamped to 1..200). A match a sync found unchanged leaves no entry; `error_message` is `<ExceptionType>: <message>`, never a traceback. Entries older than 30 days are purged daily.",
    },
    # ── bootstrap importers ────────────────────────────────────────────────
    "rpc.tournament.challonge_create_tournament": {
        "summary": "Create tournament from Challonge",
        "description": "Permission: workspace `tournament.create` on the target workspace. Creates a tournament from an existing Challonge bracket -- fetches it for the name/description, links it, and imports its current structure and results in one shot. "
        + _CHALLONGE_ERRORS,
    },
    "rpc.tournament.challonge_team_preview": {
        "summary": "Preview Challonge team sync",
        "description": "Permission: workspace `challonge.read` on the tournament's workspace. Previews the mapping of Challonge participants to teams for a tournament before syncing. "
        + _CHALLONGE_ERRORS,
    },
    "rpc.tournament.challonge_team_apply": {
        "summary": "Sync Challonge teams",
        "description": "Permission: workspace `challonge.update` on the tournament's workspace. Applies Challonge participant-to-team mappings for a tournament. "
        + _CHALLONGE_ERRORS,
    },
    # ── integrations: Google Sheets ────────────────────────────────────────
    "rpc.tournament.sheet_get": {
        "summary": "Get Google Sheet feed",
        "description": "Permission: workspace `team.read` on the tournament's workspace. Returns a tournament's registration Google Sheets feed config, or null if none.",
    },
    "rpc.tournament.sheet_upsert": {
        "summary": "Upsert Google Sheet feed",
        "description": "Permission: workspace `team.create` on the tournament's workspace. Creates or updates a tournament's registration Google Sheets feed config.",
    },
    "rpc.tournament.sheet_sync": {
        "summary": "Sync Google Sheet feed",
        "description": "Permission: workspace `team.create` on the tournament's workspace. Syncs registrations from the configured Google Sheet and returns created/updated/withdrawn/skipped counts plus errors. Only rows whose content changed since the last sync are re-applied and counted in `updated`; a sync that changed nothing sends no invalidation, and ranks the sheet does not map are kept. While another sync of the same feed runs (the scheduler's or another request's), it returns zero counts without syncing. Metered: a 429 reports `code=rate_limited` with the exceeded limit in `details.limit_name`.",
    },
    "rpc.tournament.sheet_mapping_catalog": {
        "summary": "Get sheet mapping catalog",
        "description": "Permission: workspace `team.read` on the tournament's workspace. Returns the available registration field mapping catalog (optionally with sheet headers).",
    },
    "rpc.tournament.sheet_suggest_mapping": {
        "summary": "Suggest sheet mapping",
        "description": "Permission: workspace `team.read` on the tournament's workspace. Reads a source sheet and suggests a column-to-field mapping with detected headers.",
    },
    "rpc.tournament.sheet_preview": {
        "summary": "Preview sheet mapping",
        "description": "Permission: workspace `team.read` on the tournament's workspace. Previews how sample sheet rows map to registrations under the given mapping config.",
    },
    "rpc.tournament.sheet_players_export": {
        "summary": "Export sheet players",
        "description": (
            "Permission: workspace `player.read` on the tournament's workspace. Exports a tournament's "
            "balancer pool as a players payload. `format=xv-1` (default) is the solver's own input contract, "
            "accepted as-is by the balance-job upload. `format=owt-1` is the full snapshot: the same player "
            "nodes plus per-player `owt` "
            "metadata (identity ids, every declared role with its rank source, division and top heroes, workflow "
            "status) and the tournament's roster shape including flex slots. `include_private=1` adds the "
            "organizer-only block (notes, admin notes, custom-field answers, contacts, smurf tags). Metered: a 429 "
            "reports `code=rate_limited` with the exceeded limit in `details.limit_name`."
        ),
    },
    # ── registration admin ─────────────────────────────────────────────────
    "rpc.tournament.reg_form_get": {
        "summary": "Get registration form (admin)",
        "description": "Permission: workspace `registration_form.read` on the tournament's workspace. Returns a tournament's registration form config, or null if none.",
    },
    "rpc.tournament.reg_form_upsert": {
        "summary": "Upsert registration form",
        "description": "Permission: workspace `registration_form.update` on the tournament's workspace. Creates or replaces a tournament's registration form config (built-in and custom fields).",
    },
    "rpc.tournament.regform_template_list": {
        "summary": "List registration form templates",
        "description": "Permission: workspace `registration_form.read` on the workspace in the path. Lists that workspace's named registration-form question sets, ordered by name; each carries its game (`discipline`). The optional `discipline` narrows to one game's (422 `discipline_not_installed` for an unknown code).",
    },
    "rpc.tournament.regform_template_create": {
        "summary": "Create registration form template",
        "description": "Permission: workspace `registration_form.update` on the workspace in the path. Stores a named question set for one game of the workspace (201 Created). `discipline` is required (422 `discipline_required`) and must be enabled for the workspace (422 `discipline_not_enabled`). Names are unique per workspace, case-insensitively: a collision is 409 `template_name_taken` on field `name`.",
    },
    "rpc.tournament.regform_template_update": {
        "summary": "Update registration form template",
        "description": "Permission: workspace `registration_form.update` on the workspace in the path. Replaces a template's name and question set wholesale. Its game never changes: `discipline` is omitted or equal, another game is 409 `template_discipline_immutable`. 404 `template_not_found` when the id belongs to another workspace; 409 `template_name_taken` on a case-insensitive name collision.",
    },
    "rpc.tournament.regform_template_delete": {
        "summary": "Delete registration form template",
        "description": "Permission: workspace `registration_form.update` on the workspace in the path. Deletes a template by id (204 no body). Nothing references a template -- applying one copies it -- so no tournament form changes.",
    },
    "rpc.tournament.regform_template_apply": {
        "summary": "Apply template to registration form",
        "description": "Permission: workspace `registration_form.update` on the tournament's workspace. Copies the template's question set onto the tournament's registration form and returns the form. An ordinary schema save: a changed question set appends a new version, an identical one appends nothing. The form is NOT linked to the template afterwards, so editing the template later never rewrites a live form. The template must belong to the tournament's workspace (else 404 `template_not_found`). The template's game must be the tournament's (else 409 `template_discipline_mismatch`).",
    },
    "rpc.tournament.regform_template_save_from_form": {
        "summary": "Save registration form as template",
        "description": "Permission: workspace `registration_form.update` on the tournament's workspace. Snapshots the tournament form's CURRENT question set into a new workspace template under the given name (201 Created). A snapshot, not a link: later edits to either side are invisible to the other. 404 `form_not_configured` when the tournament has no form yet; 409 `template_name_taken` on a case-insensitive name collision. The template takes the tournament's game.",
    },
    "rpc.tournament.reg_list": {
        "summary": "List registrations (admin)",
        "description": "Permission: workspace `registration.read` on the tournament's workspace. Lists a tournament's registrations with status metadata and per-registration OW-rank snapshots, filtered by status/inclusion/source and optionally including deleted.",
    },
    "rpc.tournament.reg_create_manual": {
        "summary": "Create manual registration",
        "description": "Permission: workspace `registration.create` on the tournament's workspace, plus `registration.approve` when the body's `status` is approved and `registration.reject` when it is rejected or banned. Admin-creates a registration for a tournament (201 Created) and broadcasts a realtime change.",
    },
    "rpc.tournament.reg_update": {
        "summary": "Update registration",
        "description": "Permission: workspace `registration.update` on the registration's workspace, plus `registration.roles` when the body carries `roles`, an `answers.roles` answer, `pin` or `clear_pin`, and — when the body changes `status` — `registration.approve` to make it approved or `registration.reject` to make it rejected or banned. Updates a registration's profile, roles, and statuses and broadcasts a realtime change.",
    },
    "rpc.tournament.reg_approve": {
        "summary": "Approve registration",
        "description": "Permission: workspace `registration.approve` on the registration's workspace. Approves a registration (recording the reviewer) and broadcasts a realtime change.",
    },
    "rpc.tournament.reg_reject": {
        "summary": "Reject registration",
        "description": "Permission: workspace `registration.reject` on the registration's workspace. Rejects a registration (recording the reviewer) and broadcasts a realtime change.",
    },
    "rpc.tournament.reg_include_balancer": {
        "summary": "Include registration in balancer",
        "description": "Permission: workspace `registration.update` on the registration's workspace. Adds an approved registration to the balancer pool, rated ready/incomplete from its role ranks, and broadcasts a realtime change.",
    },
    "rpc.tournament.reg_withdraw": {
        "summary": "Withdraw registration (admin)",
        "description": "Permission: workspace `registration.update` on the registration's workspace. Withdraws a registration and broadcasts a realtime change.",
    },
    "rpc.tournament.reg_restore": {
        "summary": "Restore registration",
        "description": "Permission: workspace `registration.update` on the registration's workspace, plus `registration.approve` because a restore lands the registration approved (unless it already is). Restores a withdrawn or rejected registration and broadcasts a realtime change.",
    },
    "rpc.tournament.reg_delete": {
        "summary": "Delete registration",
        "description": "Permission: workspace `registration.delete` on the registration's workspace. Soft-deletes a registration (204 no body) and broadcasts a realtime change.",
    },
    "rpc.tournament.reg_bulk_approve": {
        "summary": "Bulk approve registrations",
        "description": "Permission: workspace `registration.approve` on the tournament's workspace. Approves multiple registrations by id (at most 500 per call), returning approved and skipped ids and broadcasting a realtime change.",
    },
    "rpc.tournament.reg_set_balancer_status": {
        "summary": "Set balancer status",
        "description": "Permission: workspace `registration.update` on the registration's workspace. Sets a registration's balancer status and broadcasts a realtime change.",
    },
    "rpc.tournament.reg_bulk_add_balancer": {
        "summary": "Bulk add to balancer",
        "description": "Permission: workspace `registration.update` on the tournament's workspace. Adds multiple registrations to the balancer with a given status, returning updated/skipped counts and broadcasting a realtime change.",
    },
    "rpc.tournament.reg_bulk_set_balancer_status": {
        "summary": "Bulk set balancer status",
        "description": "Permission: workspace `registration.update` on the tournament's workspace. Explicitly pins the balancer status (not_in_balancer / excluded / a custom slug) on multiple registrations, returning updated/skipped counts and broadcasting a realtime change.",
    },
    "rpc.tournament.reg_rank_autofill_preview": {
        "summary": "Preview rank autofill",
        "description": "Permission: workspace `registration.read` on the tournament's workspace. Previews autofilling registration ranks from parsed OW data without writing.",
    },
    "rpc.tournament.reg_rank_autofill_apply": {
        "summary": "Apply rank autofill",
        "description": "Permission: workspace `registration.update` and `registration.roles` on the tournament's workspace. Autofills registration ranks from parsed OW data, persisting changes and broadcasting a realtime change.",
    },
    "rpc.tournament.reg_user_rank_history": {
        "summary": "Get user rank history",
        "description": "Permission: workspace `registration.read` on the workspace named by the required `workspace_id` query param, checked (403) before any validation error. Returns a user's balancer rank history within that workspace for the installed game named by the required `discipline` query param (422 `discipline_not_installed` otherwise); another game's ranks are never included.",
    },
    "rpc.tournament.reg_check_in": {
        "summary": "Toggle registration check-in",
        "description": "Permission: workspace `registration.check_in` on the registration's workspace. Checks a registration in or out (per the body flag) and broadcasts a realtime change.",
    },
    # ── team registration admin (organizer side of the captain surfaces) ───
    "rpc.tournament.regteam_list": {
        "summary": "List registration teams (admin)",
        "description": (
            "Permission: workspace `team.read` on the tournament's workspace. "
            "The organizer's view of a tournament's registered teams: every team with its members, its "
            "outstanding invites and its per-slot shortfall, plus the number of free agents on no team -- "
            "the players the export cannot place. Occupancy is recomputed rather than read off the "
            "denormalized status, because the shortfall is what is actionable. `include_terminal` also "
            "returns rejected and disbanded teams."
        ),
    },
    "rpc.tournament.regteam_reject": {
        "summary": "Reject a registration team",
        "description": (
            "Permission: workspace `team.update` on the tournament's workspace. "
            "An ORGANIZER refuses an entire team -- the counterpart of rejecting a solo registration, and "
            "distinct from regteam_decline, which is one invitee refusing one offer. Revokes the team's "
            "pending invites and returns its members to the solo pool without changing their registration "
            "status by default; `withdraw_members: true` explicitly withdraws them instead. Requires a "
            "reason of 1–1000 characters after trimming whitespace. The stored reason is visible to the "
            "organizer and the entitled captain, including after roster detachment, but not to the public. "
            "Returns the rejected team. 404 when the team belongs to another tournament, 409 once it is "
            "already exported, rejected or disbanded."
        ),
    },
    "rpc.tournament.regteam_invite_revoke_admin": {
        "summary": "Revoke an invite (organizer)",
        "description": (
            "Permission: workspace `team.update` on the tournament's workspace. "
            "An organizer withdraws an outstanding offer from a team they do not captain (204 no body); the "
            "write records that staff did it, which is what distinguishes the row from the captain's own "
            "regteam_invite_revoke. Unlike the captain path it does not require the team to still be "
            "mutable -- the reason to reach in is usually that something is stuck. The invite must belong to "
            "this tournament (404 otherwise, deliberately not 403)."
        ),
    },
    "rpc.tournament.regteam_invite_cap_reset": {
        "summary": "Reset a team's invite cap",
        "description": (
            "Permission: workspace `team.update` on the tournament's workspace. "
            "Forgives a team's cumulative invite count so its captain can invite again -- the recourse the "
            "cap's own 409 names (204 no body). A watermark, not a counter reset: the earlier invites stay "
            "readable in the history and only the count's floor moves. 404 when the team belongs to another "
            "tournament."
        ),
    },
    "rpc.tournament.regteam_rename_admin": {
        "summary": "Rename a registration team (organizer)",
        "description": (
            "Permission: workspace `team.update` on the tournament's workspace. "
            "An organizer renames a registered team they do not captain. 404 when the team belongs to "
            "another tournament (deliberately not 403)."
        ),
    },
    "rpc.tournament.regteam_unlock": {
        "summary": "Unlock a registration team roster",
        "description": (
            "Permission: workspace `team.update` on the tournament's workspace. "
            "Clears a captain's roster lock so the team can edit again. Organizer-only; captains lock, "
            "they do not unlock."
        ),
    },
    "rpc.tournament.regteam_admission": {
        "summary": "Set registration-team admission",
        "description": (
            "Permission: workspace `team.update` on the tournament's workspace. "
            "Sets the orthogonal admission axis (pending, accepted, waitlisted) without changing occupancy "
            "status. Waitlisted complete teams are skipped at export."
        ),
    },
    "rpc.tournament.regteam_notes": {
        "summary": "Set organizer notes on a registration team",
        "description": (
            "Permission: workspace `team.update` on the tournament's workspace. "
            "Staff-only notes on a registered team; never returned on the public roster."
        ),
    },
    "rpc.tournament.regteam_place_admin": {
        "summary": "Place a player on a registration team (organizer)",
        "description": (
            "Permission: workspace `team.update` on the tournament's workspace. "
            "Moves a live registration onto a slot of a team in this tournament, even from another team. "
            "The captain of a source team cannot be moved until captaincy is transferred."
        ),
    },
    "rpc.tournament.regteam_attach_admin": {
        "summary": "Attach a player by BattleTag (organizer)",
        "description": (
            "Permission: workspace `team.update` on the tournament's workspace. "
            "Places a live registration onto a slot, or creates a shadow registration for a BattleTag "
            "that has not signed up and places that. Eligibility warnings stay on the team card but do "
            "not refuse the write."
        ),
    },
    "rpc.tournament.regteam_invite_history": {
        "summary": "Get invite history (admin)",
        "description": (
            "Permission: workspace `team.read` on the tournament's workspace. "
            "Every invite a team ever issued, newest first, with its cumulative cap standing (used, limit, "
            "reset watermark) and, per row, whether staff or the captain withdrew it. The same data the "
            "team's captain reads through regteam_invite_history_public, which authorizes by captaincy "
            "instead."
        ),
    },
    # ── registration status catalog ────────────────────────────────────────
    "rpc.tournament.regstatus_catalog": {
        "summary": "Get status catalog",
        "description": "Permission: workspace `registration_status.read` on the workspace in the path. Returns the full registration status catalog (built-in plus custom) for that workspace.",
    },
    "rpc.tournament.regstatus_list": {
        "summary": "List custom statuses",
        "description": "Permission: workspace `registration_status.read` on the workspace in the path. Lists that workspace's custom registration statuses.",
    },
    "rpc.tournament.regstatus_create": {
        "summary": "Create custom status",
        "description": "Permission: workspace `registration_status.create` on the workspace in the path. Creates a custom registration status in that workspace (201 Created).",
    },
    "rpc.tournament.regstatus_update": {
        "summary": "Update custom status",
        "description": "Permission: workspace `registration_status.update` on the workspace in the path. Updates a custom registration status by id.",
    },
    "rpc.tournament.regstatus_delete": {
        "summary": "Delete custom status",
        "description": "Permission: workspace `registration_status.delete` on the workspace in the path. Deletes a custom registration status by id (204 no body).",
    },
    "rpc.tournament.regstatus_builtin_upsert": {
        "summary": "Override built-in status",
        "description": "Permission: workspace `registration_status.update` on the workspace in the path. Creates or updates a workspace override (icon/color/name/description) for a built-in registration status identified by scope and slug.",
    },
    "rpc.tournament.regstatus_builtin_reset": {
        "summary": "Reset built-in status",
        "description": "Permission: workspace `registration_status.update` on the workspace in the path. Removes that workspace's override for a built-in registration status (204 no body), reverting to defaults.",
    },
    # ── workspace subscription provider config ────────────────────────────
    "rpc.tournament.sub_config_list": {
        "summary": "List subscription providers",
        "description": "Permission: workspace `subscription.read` on the workspace in the path. Returns every configurable subscription provider for that workspace (present or not) with its raw ids; challenge codes are redacted to tier and expiry only.",
    },
    "rpc.tournament.sub_config_upsert": {
        "summary": "Configure subscription provider",
        "description": "Permission: workspace `subscription.update` on the workspace in the path. Creates or updates one provider's config (Discord guild id and role→tier mapping, Twitch broadcaster, challenge codes) and its verification_method: 'live' accepts only the provider's own signal, 'code' only a redeemed challenge code, 'any' either. Narrowing the method revokes stored entitlements whose source it no longer accepts. Plaintext codes are hashed server-side and never stored; omitting a field keeps the stored value.",
    },
    # ── workspace subscription requirement ────────────────────────────────
    "rpc.tournament.sub_requirement_get": {
        "summary": "Get workspace subscription requirement",
        "description": "Permission: workspace `subscription.read` on the workspace in the path. Returns the workspace's subscription admission rule as `{mode, requirements: [{provider, min_tier_rank}]}`, shared by every tournament in the workspace whose registration form has require_subscription on; an empty object means nothing is enforced.",
    },
    "rpc.tournament.sub_requirement_upsert": {
        "summary": "Set workspace subscription requirement",
        "description": "Permission: workspace `subscription.update` on the workspace in the path. Replaces the workspace's admission rule wholesale (no partial merge -- that would be a silent policy change). `mode` is 'all' or 'any'; each row names a provider and its min_tier_rank. An unknown mode or a row without a provider is rejected with 422 rather than degrading at check-in. An empty `requirements` list clears the rule, which disarms every tournament in the workspace whose toggle is on.",
    },
    # ── public registration (captain / self-service) ──────────────────────
    "rpc.tournament.captain_my_role": {
        "summary": "Get my seat",
        "description": "Permission: authenticated user; self-service — the answer is only about the caller's own captaincy. Returns the calling user's participation for an encounter as `{encounter_team_id, slot}`, both null if they captain none of its seats.",
    },
    "rpc.tournament.captain_submit_report": {
        "summary": "Submit team report",
        "description": (
            "Permission: authenticated user who captains one of the encounter's live participations (403 "
            "otherwise). Lets a captain submit their own report of the finished series: `basis_version`, "
            "`games_played` and one `results` line per live participation (`encounter_team_id`, score and "
            "optionally placement or wins — never a side), plus whatever the tournament's match-report form "
            "enables — closeness 1..10, per-map match codes, a free-text comment and any organizer-defined "
            "text fields. The reporting seat is resolved from the caller, never taken from the body. Fields "
            "the config disables are dropped rather than rejected, so a stale client cannot fail a submit; "
            "fields it marks required are enforced with a 422. A `basis_version` behind the encounter's "
            "current one is stale and refused rather than silently winning. Reports are per-participation; "
            "when every live participation's numbers agree the encounter auto-confirms and closeness becomes "
            "their average (null when any of them left it blank), otherwise it is disputed — comments and "
            "custom values never take part in that comparison. Upsert allowed until confirmed."
        ),
    },
    "rpc.tournament.captain_reports": {
        "summary": "Get captain reports",
        "description": (
            "Permission: public; no authentication required — visible to anyone who may view the tournament. "
            "Returns every participation's report for an encounter (score, closeness, comment and custom field "
            "values), every participation's per-position replay codes under `replay_codes`, and the tournament's "
            "match-report form config under `form`, so the report dialog renders exactly the rules the submit "
            "endpoint enforces."
        ),
    },
    # ── captain pre-game room (pick/ban, readiness, per-map results) ───────
    # These are the CAPTAIN's own encounter surfaces, not an organizer's: the
    # caller must captain one of the two teams, and their side is resolved from
    # their linked player profile rather than taken from the request. The
    # organizer's equivalents are the admin_pick_ban_* subjects above.
    "rpc.tournament.captain_pick_ban_state": {
        "summary": "Get pick-ban room state",
        "description": (
            "Permission: public; no authentication required — gated only by the tournament's visibility rule; a "
            "mix match's room is public. "
            "Returns the live pick/ban room for an encounter and the `kind` path segment ('map' or 'hero', "
            "422 otherwise): the resolved steps, the candidate pool, which sides still owe the current step, "
            "both sides' readiness, any open undo request, and for maps the captains' per-map result claims. "
            "A captain additionally gets their own side annotated, their eligible items, why their draft "
            "cannot be locked yet, and their own unrevealed draft — a blind step never serializes the other "
            "side's. When no session can exist yet the payload names why (teams unknown, bracket still a "
            "preview, no pick-ban configured, slot count mismatch, sides not ready, waiting on the map round) "
            "instead of erroring."
            " A mix room also lists `members` (seats in pick order), the member step's `acting_member_ids`, whom the"
            " viewer may pick for (`viewer_member_ids`; a member owes their own pick, a captain also their team's)"
            " and each member's choosable heroes (`member_eligible`, Fearless applied)."
        ),
    },
    "rpc.tournament.captain_pick_ban_act": {
        "summary": "Ban, pick or protect",
        "description": (
            "Permission: authenticated user who captains one of the encounter's two teams (403 otherwise). "
            "Applies one ban, pick or protect to the encounter's live pick/ban session of the given `kind`, "
            "under the session's row lock, and returns the caller's new room state. OPEN steps only: a blind "
            "step is a 400 that says to use the submit route. Acting when the caller's side does not owe the "
            "current step, sending the wrong action for it, naming an item the step's rules do not allow, or "
            "omitting the opponent player a per-player ban must name is a 400, as is a session that is not "
            "initialized or no longer active."
            " On a mix match the captain is the roster snapshot's (the lineup's crown)."
            " On a mix match's member pick (spec §11.6) the body names `member_id`, the `encounter.team_member` seat"
            " the hero is for: the member themselves or their team's captain may pick (403 otherwise; 422 on a"
            " tournament match). An assignment step is answered through captain_pick_ban_submit."
        ),
    },
    "rpc.tournament.captain_pick_ban_submit": {
        "summary": "Submit a blind draft",
        "description": (
            "Permission: authenticated user who captains one of the encounter's two teams (403 otherwise). "
            "Replaces the caller's whole draft for the current BLIND step and, with `lock: true`, locks it "
            "— a locked submission is final, and once every acting side has locked the step reveals for "
            "both. Returns the caller's new room state; while the step is unrevealed it carries the caller's "
            "own items and only the opponent's progress counts. 400 when the current step is not blind, when "
            "the caller already locked, or when the items break the step's rules (the reasons are also "
            "listed in the state's `draft_issues`)."
            " On a mix match the captain is the roster snapshot's (the lineup's crown)."
            " It also answers a mix's assignment step (open, not blind): each item names `member_id`, one hero of"
            " the team's picks per member, none a member's Fearless excludes (422 on a tournament match)."
        ),
    },
    "rpc.tournament.captain_pick_ban_dispute": {
        "summary": "Dispute the last revealed step",
        "description": (
            "Permission: authenticated user who captains one of the encounter's two teams (403 otherwise). "
            "Unilateral, no opponent consent: voids the last fully revealed BLIND step and re-opens it for a "
            "fresh attempt with each side's previous items prefilled, so a captain who named the wrong "
            "opponent player can redo it. Allowed only while that step's `dispute` is enabled, its attempt "
            "budget is not spent, no later step has been acted in, and the map that round settled has no "
            "result yet; anything else is a 400. Returns the caller's new room state."
            " On a mix match the captain is the roster snapshot's (the lineup's crown)."
        ),
    },
    "rpc.tournament.captain_pick_ban_elect_opener": {
        "summary": "Elect the next round's opener",
        "description": (
            "Permission: authenticated user who captains one of the encounter's two teams, and only the side "
            "that LOST the previous round may choose (403 otherwise). "
            "Resolves a round the `result_loser_choice` rotation is holding by naming which side opens it, "
            "then appends that round and returns the session. 400 when no round is awaiting a "
            "choice. An organizer overrides an unreachable captain through admin_pick_ban_elect_opener."
            " On a mix match the captain is the roster snapshot's (the lineup's crown)."
        ),
    },
    "rpc.tournament.captain_pick_ban_undo": {
        "summary": "Request or withdraw an undo",
        "description": (
            "Permission: authenticated user who captains one of the encounter's two teams (403 otherwise). "
            "Records the calling captain's consent to undo the session's last action and applies it the "
            "moment the opposing captain consents too; `consent=false` withdraws an open request (either "
            "side may). An applied undo of a `side_pick` takes that game's sides back. Returns the resulting "
            "undo block. 400 when the session is not "
            "initialized or cancelled, when there is nothing left to undo, or when the target is a map pick "
            "whose hero round has already started -- undo those hero actions first; 409 `side_locked` when "
            "the undo would take back a side whose game already has a claim or a confirmed result."
            " On a mix match the captain is the roster snapshot's (the lineup's crown)."
        ),
    },
    "rpc.tournament.captain_report_game": {
        "summary": "Claim a game result",
        "description": (
            "Permission: authenticated user who captains one of the encounter's live participations (403 "
            "otherwise). Files the calling captain's own claim of ONE series position's result, immediately "
            "after that game rather than at series end: `basis_version` plus one `results` line per "
            "participation (`encounter_team_id`, optional score, placement and the stage's own "
            "`column_values`). The claiming seat is taken from the caller, never from the body. Every live "
            "participation claims independently: matching claims accept the game's result and open whatever "
            "the series owes next, differing ones mark the game `disputed` for an organizer. Returns "
            "`{disputed, resolved, game}`. 404 when the game belongs to another encounter or is cancelled, "
            "409 `result_locked` once the game is confirmed (only the admin correction changes it), 409 "
            "`map_not_selected` while the position still has no map (choose it first, through "
            "captain_select_game_map or the map pick-ban), 409 `side_pick_pending` while the position's side "
            "step is open, 409 `side_pick_required` while a room that picks this game's sides left them "
            "incomplete, 409 on a `basis_version` behind the game's "
            "current one, and 409 while the stage bracket is still a preview the organizer has not "
            "activated."
        ),
    },
    "rpc.tournament.captain_select_game_map": {
        "summary": "Name a game's map",
        "description": (
            "Permission: authenticated user who captains one of the encounter's two teams (403 otherwise). "
            "Freeplay's half of what the map pick-ban does automatically: names the map an open position is "
            "played on, moving a `planned` game to `awaiting_result`. Returns `{game}`. 404 when the game "
            "belongs to another encounter, 409 `result_locked` when the position's result is already "
            "settled, 409 `side_pick_pending` / `side_pick_required` while the position's sides are not "
            "decided where the room picks them, and 409 `map_locked` once a captain has claimed a score "
            "against the current map."
        ),
    },
    "rpc.tournament.captain_ready": {
        "summary": "Confirm readiness",
        "description": (
            "Permission: authenticated user who captains one of the encounter's live participations (403 "
            "when the account captains none of them or has no linked player profile). "
            "Marks the calling captain's seat ready to begin the encounter's pre-game phase and returns the "
            "resulting readiness map, keyed by participation id; idempotent. The pick/ban session only "
            "opens once every seat is ready, and any change of team assignment clears them all."
            " On a mix match the captain is the roster snapshot's (the lineup's crown)."
        ),
    },
    "rpc.tournament.encounter_chat_history": {
        "summary": "Read the pre-game room chat",
        "description": (
            "Permission: optional authentication. Captains of either team and the workspace's staff "
            "always read; anybody else reads only while the room's `spectators_can_read` is on, which "
            "a pre-game room has OFF by default (captains trade custom-lobby codes there). A hidden "
            "tournament is visible only to its workspace's admins and its preview allowlist. "
            "Returns the messages plus the room settings, the caller's own viewer rights and — for "
            "moderators only — the active mutes. `after_id` tails the room; `limit` pages it."
            " A mix match's chat is read and written only by its seated players (role captain or player) and the "
            "mix's hosts (staff); everyone else gets 403."
        ),
    },
    "rpc.tournament.encounter_chat_post": {
        "summary": "Post to the pre-game room chat",
        "description": (
            "Permission: authenticated captain of either team, or workspace staff; spectators never "
            "write, at any setting. The body is sanitized and capped at 500 characters. 403 with code "
            "`chat_muted` while the account is muted in this room, 429 past 10 messages per 10 seconds. "
            "Returns the stored message, which is also fanned out to the room's realtime topic."
        ),
    },
    "rpc.tournament.encounter_chat_delete": {
        "summary": "Delete a pre-game chat message",
        "description": (
            "Permission: the message's author, or a moderator of the room (workspace staff). "
            "Soft-deletes one message and publishes the removal to the room's subscribers. "
            "404 when the id is not a message of this room. Answers `{deleted: true}`."
        ),
    },
    "rpc.tournament.encounter_chat_settings": {
        "summary": "Set pre-game chat visibility",
        "description": (
            "Permission: moderator of the room (workspace staff). Opens or closes the room to "
            "spectators and returns the stored setting. Closing it also revokes the spectators already "
            "subscribed to the room's realtime topic; a no-op toggle emits nothing."
        ),
    },
    "rpc.tournament.encounter_chat_mute_set": {
        "summary": "Mute an account in the pre-game chat",
        "description": (
            "Permission: moderator of the room (workspace staff). Mutes one account in this room for "
            "`minutes` (1..10080), or until lifted when `minutes` is null, with an optional reason. "
            "422 on muting yourself. Returns the mute."
        ),
    },
    "rpc.tournament.encounter_chat_mute_clear": {
        "summary": "Unmute an account in the pre-game chat",
        "description": (
            "Permission: moderator of the room (workspace staff). Lifts one account's mute in this "
            "room, idempotent. Answers `{deleted: true}`."
        ),
    },
    "rpc.tournament.get_pick_ban_configs": {
        "summary": "List public map pick-ban configs",
        "description": "Permission: public; no authentication required — a hidden tournament is visible only to its workspace's admins and users on its preview allowlist. Returns the tournament's map pick-ban configs in cascade order.",
    },
    "rpc.tournament.pick_ban_outcomes": {
        "summary": "List the tournament's pick-ban outcomes",
        "description": "Permission: public; no authentication required — a hidden tournament is visible only to its workspace's admins and users on its preview allowlist (404 otherwise, and for an unknown tournament). Returns every hero ban of the tournament's encounters an anonymous spectator may see in the room (`hero_bans`: one row per banned hero of a current-attempt submission to a ban step that is revealed or not blind; `first_map` when the step plays round 1, `target_player_id` the opponent roster player a per-player ban is spent on) and every map its map rooms picked or banned (`map_outcomes`). Cached up to 30 seconds: a live room's newest bans may lag that long.",
    },
    "rpc.tournament.pick_ban_rules_catalog": {
        "summary": "Get the pick-ban ruleset catalog",
        "description": "Permission: public; no authentication required — the catalog describes the rules ENGINE (which condition leaves and constraints exist, what parameters they take) plus ONE discipline's vocabulary: its item groups per kind (character classes declared by its module, mode slugs for maps) and its presets (the module's own plus the generic map presets; a preset's `first_ban_rotation`, when set, is the rotation the preset needs; `mix_eligible` says whether a pickup mix may play it -- a hero preset that bans no player on map 1 of a Bo1). `discipline` is required: 422 when absent, 404 `discipline_not_installed` for a code no module declares, never another game's presets. The pick-ban constructor loads it before a config exists to attach it to.",
    },
    "rpc.tournament.reg_pub_form": {
        "summary": "Get public registration form",
        "description": "Permission: public; no authentication required — gated only by the tournament's visibility rule. Returns the public registration form (with sub-role catalog) for a tournament, or null if none.",
    },
    "rpc.tournament.reg_pub_create": {
        "summary": "Submit registration",
        "description": "Permission: authenticated user; self-service — the caller registers only themselves. Lets a user self-register for a tournament (201 Created) after validating the form is open and the input; rejects duplicates with 409, refuses with 400 only when the form's subscription_stage is 'registration' and a required subscription is confirmed missing by an automatic check (a verdict a challenge code could still change is deferred to check-in, and an undetermined verdict fails open). With the default stage 'check_in' sign-up is never refused on a subscription.",
    },
    "rpc.tournament.reg_pub_get_me": {
        "summary": "Get my registration",
        "description": "Permission: authenticated user; self-service — resolved from the caller's own token, never from a supplied id. Returns the calling user's registration for a tournament, or null if none.",
    },
    "rpc.tournament.reg_pub_update_me": {
        "summary": "Update my registration",
        "description": "Permission: authenticated user; self-service — the caller's own registration only. Lets a user update their own still-pending registration after re-validating the input.",
    },
    "rpc.tournament.reg_pub_withdraw_me": {
        "summary": "Withdraw my registration",
        "description": "Permission: authenticated user; self-service — the caller's own registration only. Withdraws the calling user's own registration and returns the new status; refuses with 409 once the registration has been checked in (only an organizer can withdraw an attendee from that point on).",
    },
    "rpc.tournament.reg_pub_check_in": {
        "summary": "Check in to tournament",
        "description": "Permission: authenticated user; self-service — the caller's own registration only. Checks the calling user's own registration in, blocking when the form requires a confirmed-public OW profile that is private, or when a required subscription is confirmed missing (an undetermined verdict fails open).",
    },
    "rpc.tournament.reg_pub_recheck_me": {
        "summary": "Re-check my profile and subscriptions",
        "description": "Permission: authenticated user; self-service — the caller's own registration only. Forces a live subscription check and queues a re-fetch of the registration's BattleTags, each only when the tournament requires it; returns 204 and the client refetches its registration. One call per user per 60 seconds: a repeat answers 429 with Retry-After.",
    },
    "rpc.tournament.sub_me": {
        "summary": "My subscription status",
        "description": "Permission: authenticated user; self-service — the caller's own subscription standing only. Returns the calling user's composed subscription outcome for the tournament plus a per-provider verdict; never forces a provider refresh.",
    },
    "rpc.tournament.sub_redeem_code": {
        "summary": "Redeem a subscription code",
        "description": "Permission: authenticated user; self-service — the entitlement is granted to the caller's own account. Redeems a challenge code published in a subscriber-only post, granting an entitlement at the code's tier; never downgrades an existing higher tier and is rate-limited per user.",
    },
    "rpc.tournament.reg_pub_list": {
        "summary": "List public registrations",
        "description": "Permission: public; no authentication required — gated only by the tournament's visibility rule. Returns the live public registration list for a tournament with tournament-history and division grids.",
    },
    # ── team registration: public + captain surfaces ──────────────────────
    # A registration team belongs to the players who formed it, so these are
    # gated by captaincy or by holding an invite -- never by workspace
    # permission. The organizer's counterparts are the regteam_* admin subjects
    # further down. Invites persist only a token_sha256: the raw token is
    # returned exactly once, by regteam_invite, and never served again.
    "rpc.tournament.regteam_list_public": {
        "summary": "List registration teams",
        "description": (
            "Permission: public; no authentication required beyond the tournament's own visibility rule. "
            "The public roster of a tournament's registered teams: name, crest, status, members and each "
            "team's remaining per-slot shortfall, plus the count of free agents on no team. Rejected and "
            "disbanded teams are omitted, and so are outstanding invites -- except on a team the caller "
            "themselves captains or manages, who sees their own pending offers here."
        ),
    },
    "rpc.tournament.regteam_invite_preview": {
        "summary": "Preview an invite link",
        "description": (
            "Permission: public; no authentication required and no tournament visibility check — the invite "
            "token itself is the credential. "
            "Resolves a link invite's token to what it offers -- tournament, team, slot, substitute flag, "
            "expiry and whether it is still redeemable -- without consuming it. The only anonymous invite "
            "surface, so a link into a private tournament still works for its holder. Reveals nothing "
            "about the roster. A dead or expired invite answers with its state rather than an error; only a "
            "token matching nothing is a 404."
        ),
    },
    "rpc.tournament.regteam_create": {
        "summary": "Create a registration team",
        "description": (
            "Permission: authenticated user; self-service — the caller founds the team and is registered as "
            "its own captain. "
            "Founds a team for a tournament and registers the caller as its captain in one transaction, "
            "occupying the requested roster slot. The captain passes the same registration form and the same "
            "admission gate as a solo entrant. Returns the new team including its own invites. 400 on an "
            "empty name or one containing '#', 409 when the name is taken or the caller is already "
            "registered."
        ),
    },
    "rpc.tournament.regteam_invite": {
        "summary": "Invite a player",
        "description": (
            "Permission: authenticated user who is the team's own captain or one of its managers (403 "
            "otherwise); no workspace permission substitutes. "
            "Offers one roster slot, in either of two modes: with `target_registration_id` it is an in-app "
            "offer to a named free agent, which carries no token at all and is read by its recipient through "
            "regteam_my_invites; without it a shareable link invite is minted. The link's raw token is "
            "returned in this response and nowhere else -- only its sha256 is stored. Expires after "
            "`ttl_days` (default 7). The team must still be forming and unlocked, and a pending invite "
            "reserves its slot. 409 once the team has issued 60 invites in total, counting revoked and "
            "declined ones: revoke an outstanding offer or ask an organizer for a cap reset."
        ),
    },
    "rpc.tournament.regteam_invite_revoke": {
        "summary": "Revoke an invite (captain)",
        "description": (
            "Permission: authenticated user who is the team's own captain or one of its managers (403 "
            "otherwise). "
            "Withdraws an outstanding offer the team issued, releasing its reserved slot "
            "(204 no body). An organizer reaching into a team they do not captain "
            "uses regteam_invite_revoke_admin instead, which records that staff did it. 404 on an unknown "
            "invite."
        ),
    },
    "rpc.tournament.regteam_invite_history_public": {
        "summary": "Get invite history (captain)",
        "description": (
            "Permission: authenticated user who is the team's own captain or one of its managers; authorized "
            "by team staffing rather than workspace permission. "
            "Reads every invite the team ever issued, newest first -- live, accepted, "
            "declined, revoked or lapsed -- alongside the cumulative cap standing (used, limit, and the "
            "reset watermark if an organizer forgave the count). Deliberately still readable after the team "
            "is rejected or exported, which is usually when someone opens it. The organizer reads the same "
            "data through regteam_invite_history."
        ),
    },
    "rpc.tournament.regteam_my_invites": {
        "summary": "List invites addressed to me",
        "description": (
            "Permission: authenticated user; self-service — the list is scoped to the caller from their own "
            "token and there is no id to pass. "
            "Returns the targeted invites offered to the calling user in this tournament -- the only way "
            "their recipient can learn one exists, since a targeted invite carries no token to paste. "
            "Link invites are excluded (a bearer "
            "credential has no addressee), as are expired offers and offers from teams no longer forming."
        ),
    },
    "rpc.tournament.regteam_free_agents": {
        "summary": "List free agents",
        "description": (
            "Permission: authenticated user; no captaincy, workspace permission or tournament-visibility "
            "check is applied. "
            "Returns this tournament's live registrants who are on no team, with the roles they signed up "
            "for (primary first) -- the picker a captain fills a slot from. Everything here is also on the "
            "public participants list. Carries registration "
            "ids, never account ids."
        ),
    },
    "rpc.tournament.regteam_accept": {
        "summary": "Accept an invite",
        "description": (
            "Permission: authenticated user holding the invite — a link invite redeems by its `token` only (by "
            "`invite_id` it is 404 `invite_not_found`), a targeted invite by `token` or `invite_id` and only by "
            "the account it names (403 otherwise). The body names exactly one of `token` and `invite_id` (422 "
            "otherwise). Takes the offered slot, returning the team. "
            "A player already registered solo is attached to the team rather than duplicated, and the "
            "submitted registration body is then ignored -- their recorded answers stand; a player with no "
            "registration yet first passes the tournament's sign-up admission gate (400 when it refuses) and "
            "is registered from that body. A player already on another team is never moved: 409 "
            "`already_on_team`. A refused accept leaves the invite pending. The consume is a single guarded "
            "update, so two simultaneous redemptions of one link cannot both win. 409 on a full slot, a "
            "terminal registration, a lost race, or `registration_changed` when the caller's registration "
            "changed between the admission check and the team lock."
        ),
    },
    "rpc.tournament.regteam_decline": {
        "summary": "Decline an invite",
        "description": (
            "Permission: authenticated user holding the invite — a link invite is declined by its `token` only "
            "(by `invite_id` it is 404 `invite_not_found`), a targeted invite by `token` or `invite_id` and only "
            "by the account it names (403 otherwise). "
            "The INVITEE refuses an offer made to them, releasing its reserved slot back to the captain (204 no "
            "body). The body names exactly one of `token` and `invite_id` (422 otherwise). Distinct from "
            "regteam_reject, which is an organizer refusing an entire team. 409 when the invite is no longer "
            "pending."
        ),
    },
    "rpc.tournament.regteam_kick": {
        "summary": "Remove a team member",
        "description": (
            "Permission: authenticated user who is the team's own captain or one of its managers (403 "
            "otherwise). "
            "Removes an accepted member, freeing their slot (204 no body). The member's "
            "registration survives as withdrawn rather than being deleted. The team must "
            "still be forming and unlocked and registration still open; 409 when aimed at the captain "
            "themselves -- transfer captaincy or disband instead -- and 404 when the player is not on the "
            "team."
        ),
    },
    "rpc.tournament.regteam_leave": {
        "summary": "Leave a team",
        "description": (
            "Permission: authenticated user; self-service — the caller may only remove their own membership, "
            "matched from their own account. "
            "A member withdraws themselves from a team, freeing their slot (204 no body); their registration "
            "becomes withdrawn. The mirror of regteam_kick. 409 when the caller is the captain -- a captain "
            "must transfer or disband rather than vanish from a team others have joined -- and 404 when the "
            "caller is not on the team."
        ),
    },
    "rpc.tournament.regteam_transfer_captain": {
        "summary": "Transfer captaincy",
        "description": (
            "Permission: authenticated user who is the team's own captain (403 for a manager or anyone "
            "else). "
            "Hands captaincy to another accepted member (204 no body); the roster itself is unchanged. "
            "The team must still be forming and registration still open. 404 when the "
            "successor is not on the team, 409 when they are a substitute -- a bench player holds no starter "
            "slot and cannot captain the roster."
        ),
    },
    "rpc.tournament.regteam_disband": {
        "summary": "Disband a team",
        "description": (
            "Permission: authenticated user who is the team's own captain (403 for a manager or anyone "
            "else). "
            "Dissolves their own team (204 no body): members' registrations become withdrawn but "
            "keep their team link, so each player's card can say the team was disbanded rather than leaving "
            "an unexplained withdrawal, and every pending invite is revoked. The team must "
            "still be forming and registration still open. An organizer's equivalent is regteam_reject."
        ),
    },
    "rpc.tournament.regteam_rename": {
        "summary": "Rename a registration team",
        "description": (
            "Permission: authenticated user who is the team's own captain or one of its managers (403 "
            "otherwise). "
            "Renames their team. The roster must still be mutable and unlocked. '#' in "
            "a name is refused."
        ),
    },
    "rpc.tournament.regteam_place_member": {
        "summary": "Reassign a roster slot",
        "description": (
            "Permission: authenticated user who is the team's own captain or one of its managers (403 "
            "otherwise); the roster must still be mutable and unlocked. "
            "Moves a member to another slot, onto or off the bench, or swaps two members when "
            "swap_with_registration_id is set. A captain cannot become a substitute."
        ),
    },
    "rpc.tournament.regteam_set_manager": {
        "summary": "Grant or revoke team-manager",
        "description": (
            "Permission: authenticated user who is the team's own captain (403 for a manager or anyone "
            "else); the roster must still be mutable and unlocked. "
            "Flags another accepted member as a manager so they can invite, kick, rename "
            "and check the roster in. The captain themselves is not a manager."
        ),
    },
    "rpc.tournament.regteam_extend_invite": {
        "summary": "Extend or rotate an invite",
        "description": (
            "Permission: authenticated user who is the team's own captain or one of its managers (403 "
            "otherwise); the roster must still be mutable and unlocked. "
            "Refreshes a pending invite's TTL. rotate_token is only valid for a link invite and returns a "
            "new raw token exactly once."
        ),
    },
    "rpc.tournament.regteam_lock": {
        "summary": "Lock a complete roster",
        "description": (
            "Permission: authenticated user who is the team's own captain (403 for a manager or anyone "
            "else). "
            "A complete roster can be frozen so further edits refuse with roster_locked until "
            "an organizer unlocks it."
        ),
    },
    "rpc.tournament.regteam_check_in": {
        "summary": "Check in a team's roster",
        "description": (
            "Permission: authenticated user who is the team's own captain or one of its managers (403 "
            "otherwise). "
            "Checks in every approved member except those listed in "
            "exclude_registration_ids. Gated by the tournament check-in window. Every member's approval, "
            "account and admission are checked in one batch before the team is locked, so a refusal names "
            "the first blocked member in roster order; 409 `roster_changed` when the roster changed between "
            "that check and the lock."
        ),
    },
    "rpc.tournament.regteam_cover_subscription": {
        "summary": "Cover a team subscription",
        "description": (
            "Permission: authenticated user who is the team's own captain or one of its managers (403 "
            "otherwise). "
            "Stamps the registered team with the captain or manager's active entitlement, or a redeemed "
            "challenge code. Only when the form's subscription_scope is team."
        ),
    },
    # ── encounter saved-view writes ────────────────────────────────────────
    "rpc.tournament.saved_view_create": {
        "summary": "Save encounter view",
        "description": "Permission: authenticated member of the workspace named by `workspace_id` (403 otherwise); self-service — the view belongs to the caller. Creates the calling user's saved encounter filter view in a workspace; 409 `saved_view_exists` when the caller already has a view of that name, 409 `saved_view_limit` when the caller already keeps 20 views there.",
    },
    "rpc.tournament.saved_view_delete": {
        "summary": "Delete saved view",
        "description": "Permission: authenticated member of the workspace named by `workspace_id` (403 otherwise); self-service — only the caller's own view is deleted. Deletes the calling user's saved encounter view by id in a workspace (204 no body).",
    },
    # ── organizer dashboard ──────────────────────────────────────────────────
    "rpc.tournament.admin_dashboard": {
        "summary": "Organizer dashboard",
        "description": (
            "Permission: any of workspace `tournament.read`, `team.read`, `match.read`, `user.read` or"
            " `achievement.read`. Returns the organizer home of one workspace: one card per tournament that is not"
            " finished (hidden ones included) plus completed tournaments within 14 days of finishing whose wrap-up"
            " (results confirmed, duel logs, achievements, standings) is not done; the next 7 days of phase-schedule"
            " boundaries plus every overdue phase start; the work queue of those cards ordered by severity; and the"
            " backlog of every other tournament with a data-quality issue. Each field group is null when the caller"
            " lacks the permission that gates it, never zero. 422 without `workspace_id`, 403 without any of the"
            " permissions."
        ),
    },
    "rpc.tournament.admin_dashboard_trends": {
        "summary": "Organizer dashboard trends",
        "description": (
            "Permission: workspace `tournament.read`. Returns participants, newcomers, duel log coverage and the"
            " median match-end-to-confirmation time of the workspace's last 10 finished, non-league, non-hidden"
            " tournaments, oldest first, optionally narrowed to one installed `discipline` (404"
            " `discipline_not_installed` for an unknown code). 422 without `workspace_id`."
        ),
    },
    "rpc.tournament.tournament_readiness": {
        "summary": "Tournament readiness checklist",
        "description": (
            "Permission: workspace `tournament.read` or `team.read` on the tournament's own workspace. Returns the"
            " living readiness checklist for one tournament, telling its organisers what is still missing before it can"
            " run: schedule/grid/stage-slot configuration, bracket, duel log coverage and pending standings"
            " recalculation (`tournament.read`); the registration, pool, balance and draft state (`team.read`); the"
            " overdue, pending-confirmation and disputed results (`match.read`); and the achievement evaluation status"
            " (`achievement.read`). Each group of fields is masked to null when the caller lacks the permission that"
            " gates it, so a partial reader sees no-access rather than zeros. 403 without `tournament.read` or"
            " `team.read`, 404 if the tournament is unknown; hidden tournaments of the caller's own workspace are"
            " visible."
        ),
    },
}
