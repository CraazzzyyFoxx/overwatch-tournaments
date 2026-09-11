"""Human-readable docs (summary + description) for balancer-service RPC
subjects, merged into the gateway's OpenAPI by the export script. Prose only.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    "rpc.balancer.config": {
        "summary": "Get balancer config",
        "description": "Returns the public balancer configuration (ranks, roles, defaults) with no authentication required.",
    },
    "rpc.balancer.admin.tournament_config_get": {
        "summary": "Get tournament balancer config",
        "description": "Returns the per-tournament balancer config for admins with workspace team-read permission, or null when none is set.",
    },
    "rpc.balancer.admin.tournament_config_upsert": {
        "summary": "Upsert tournament balancer config",
        "description": "Creates or updates the per-tournament balancer config (requires workspace team-create) and emits a balancer config-changed realtime event.",
    },
    "rpc.balancer.admin.tournament_summary_get": {
        "summary": "Get tournament summary",
        "description": "Returns the tournament id/name/status/workspace_id for the balancer tool context; requires workspace team-read and includes hidden tournaments.",
    },
    "rpc.balancer.admin.balance_get": {
        "summary": "Get saved balance",
        "description": "Returns the saved team balance for a tournament for admins with workspace team-read permission, or null when none exists.",
    },
    "rpc.balancer.admin.balance_save": {
        "summary": "Save tournament balance",
        "description": "Persists a computed team balance for the tournament (requires workspace team-create) and emits a balance-saved realtime event.",
    },
    "rpc.balancer.admin.balance_export": {
        "summary": "Export balance to teams",
        "description": "Materializes a saved balance into tournament teams, returning removed/imported counts and emitting a teams-changed realtime event.",
    },
    "rpc.balancer.admin.balance_ranks_export": {
        "summary": "Re-export balance ranks",
        "description": (
            "Updates the ranks of players already materialized from the saved balance, "
            "without removing or creating any team, and emits a teams-changed realtime event."
        ),
    },
    "rpc.balancer.admin.workspace_config_get": {
        "summary": "Get workspace balancer config",
        "description": (
            "Returns the workspace-level balancer config (rank-delta threshold, pool-hide flag and "
            "the Discord channel every mix posts its matchup to) for members with workspace read permission."
        ),
    },
    "rpc.balancer.admin.workspace_config_upsert": {
        "summary": "Upsert workspace balancer config",
        "description": (
            "Creates or updates the workspace-level rank-delta threshold, hide-from-pool flag and the "
            "workspace-wide Discord channel for mix matchups, requiring workspace update permission."
        ),
    },
    "rpc.balancer.admin.teams_import": {
        "summary": "Import teams file",
        "description": "Bulk-imports tournament teams from a multipart JSON upload (atravkovs or internal format, auto-detected) and emits a teams-changed realtime event.",
    },
    "rpc.balancer.jobs.create": {
        "summary": "Create balance job",
        "description": "Queues an asynchronous balance job from a multipart player-data upload plus optional config overrides, returning 202 with the job id.",
    },
    "rpc.balancer.jobs.status": {
        "summary": "Get balance job status",
        "description": "Returns the current status of a balance job by its uuid, scoped to the requesting access token or workspace API key.",
    },
    "rpc.balancer.jobs.result": {
        "summary": "Get balance job result",
        "description": "Returns the computed result of a completed balance job by its uuid, scoped to the requesting token or API key.",
    },
    "rpc.balancer.draft.tournament_board": {
        "summary": "Get tournament draft board",
        "description": "Returns the live draft board snapshot for a tournament's active session (no auth), or null when no session is active.",
    },
    "rpc.balancer.draft.session_get": {
        "summary": "Get draft session",
        "description": "Returns a single draft session by id for spectating, with no authentication required.",
    },
    "rpc.balancer.draft.session_board": {
        "summary": "Get draft session board",
        "description": "Returns the full draft board snapshot (teams, picks, pool) for a given session id, with no authentication required.",
    },
    "rpc.balancer.draft.suggestions": {
        "summary": "Get pick suggestions",
        "description": "Ranks the top five available players by fit for the current pick (requires workspace team-read); 409 if the draft has no current pick.",
    },
    "rpc.balancer.draft.feasibility": {
        "summary": "Get draft feasibility",
        "description": "Reports whether every remaining team-role slot can be filled. Requires workspace team-create permission.",
    },
    "rpc.balancer.draft.pick_options": {
        "summary": "Get safe draft pick options",
        "description": "Returns safe and blocked player-role choices for the current pick. Available only to the on-clock captain or a workspace admin.",
    },
    "rpc.balancer.draft.player_role_edit": {
        "summary": "Preview or add a draft player role",
        "description": "Previews or commits an emergency role addition to the draft snapshot with optimistic versioning and private audit reason. Requires workspace team-create permission.",
    },
    "rpc.balancer.draft.session_list": {
        "summary": "List tournament draft sessions",
        "description": "Returns every draft session ever created for a tournament, newest first (requires workspace team-read).",
    },
    "rpc.balancer.draft.session_delete": {
        "summary": "Delete draft session",
        "description": "Permanently erases a draft session with its teams, pool, picks and audit trail (requires team-create); 409 while the draft is live or paused. Teams already exported to the tournament are kept.",
    },
    "rpc.balancer.draft.session_create": {
        "summary": "Create draft session",
        "description": "Creates a new draft session for a tournament (requires workspace team-create) and publishes a session-updated realtime event.",
    },
    "rpc.balancer.draft.seed": {
        "summary": "Seed draft session",
        "description": "Seeds a draft session with captains and players from the balancer pool or a manual list (requires team-create); 422 if neither is provided.",
    },
    "rpc.balancer.draft.session_patch": {
        "summary": "Patch draft session",
        "description": "Updates mutable draft settings (pick time, autopick strategy, override flag, rounds, settings) before the draft starts, requiring team-create.",
    },
    "rpc.balancer.draft.start": {
        "summary": "Start draft session",
        "description": "Starts the draft and opens the first pick (requires team-create), publishing a pick-started realtime event with the clock deadline. The tournament must be in its draft phase unless the caller is a superuser.",
    },
    "rpc.balancer.draft.pause": {
        "summary": "Pause draft session",
        "description": "Pauses an in-progress draft (requires team-create) and publishes a draft-paused realtime event.",
    },
    "rpc.balancer.draft.resume": {
        "summary": "Resume draft session",
        "description": "Resumes a paused draft (requires team-create) and publishes a draft-resumed realtime event.",
    },
    "rpc.balancer.draft.cancel": {
        "summary": "Cancel draft session",
        "description": "Cancels the draft (requires team-create) and publishes a draft-cancelled realtime event.",
    },
    "rpc.balancer.draft.rollback": {
        "summary": "Rollback draft pick",
        "description": "Rolls back the most recent draft action (requires team-create) and publishes a rollback realtime event.",
    },
    "rpc.balancer.draft.export": {
        "summary": "Export draft to teams",
        "description": "Finalizes the drafted rosters into tournament teams (requires team-create) and publishes a draft-completed realtime event.",
    },
    "rpc.balancer.draft.export_ranks": {
        "summary": "Re-export draft ranks",
        "description": (
            "Updates the ranks of players already exported from this completed draft "
            "(requires team-create), leaving the tournament teams themselves untouched."
        ),
    },
    "rpc.balancer.draft.pick_select": {
        "summary": "Select draft pick",
        "description": "Makes a pick for the current slot as the on-clock captain (or admin), enforcing role fit and optimistic version, then broadcasts pick-made/next-pick events.",
    },
    "rpc.balancer.draft.pick_autopick": {
        "summary": "Autopick draft pick",
        "description": "Auto-selects the best-fit available player for a pick using the session's autopick strategy (requires team-create) and broadcasts the result.",
    },
    "rpc.balancer.draft.pick_override": {
        "summary": "Override draft pick",
        "description": "Admin-overrides a pick to an arbitrary player (requires team-create), bypassing captain/clock constraints, and broadcasts a pick-made event.",
    },
    "rpc.balancer.custom.create": {
        "summary": "Create custom game",
        "description": (
            "Opens a pickup mix in the workspace and returns it with its roster; the caller becomes "
            "its host. Requires the workspace custom_game create permission, and member_ids may be "
            "empty to start from an empty lineup. With clone_from_game_id the new mix starts from a "
            "previous mix of the same workspace -- its pool (everyone back in the pool), per-seat "
            "role setup, role shape, points per win, team names, solver overrides and co-hosts -- "
            "but never its balance result, rolled map, match history or status."
        ),
    },
    "rpc.balancer.custom.list": {
        "summary": "List custom games",
        "description": "Returns every mix in the workspace with its settings and host display name, but without rosters; public, no authentication required.",
    },
    "rpc.balancer.custom.get": {
        "summary": "Get custom game",
        "description": (
            "Returns one mix with its full lineup: each seat's participation state, role "
            "order, the ranks the balancer would use and which layer each came from. Public, no "
            "authentication required; 404 when the mix belongs to another workspace."
        ),
    },
    "rpc.balancer.custom.update_roster": {
        "summary": "Replace custom game roster",
        "description": (
            "Replaces the mix lineup with the given workspace_member ids (at most 100) and returns "
            "the refreshed mix. Host or co-host only; a member with no linked login account can be "
            "rostered here, unlike the host and co-host grants."
        ),
    },
    "rpc.balancer.custom.update_player": {
        "summary": "Update custom game player",
        "description": "Patches one seat's participation state, role order or flex flag and returns the refreshed mix. Host or co-host only; 404 when the member is not on this mix's roster.",
    },
    "rpc.balancer.custom.set_participation": {
        "summary": "Set custom game participation",
        "description": (
            "Moves several seats between must_play, pool and benched in one transaction -- the whole "
            "rotation verdict at once -- and returns the refreshed mix. Host or co-host only; 404 if "
            "any member is not on the roster."
        ),
    },
    "rpc.balancer.custom.balance": {
        "summary": "Balance custom game",
        "description": (
            "Balances the non-benched lineup, reading the host's own rank book above the workspace "
            "canon, stores the resulting options on the mix and returns it. Host or co-host only; "
            "422 when the lineup is empty or a seated player has no ranked role."
        ),
    },
    "rpc.balancer.custom.set_team_names": {
        "summary": "Set custom game team names",
        "description": "Renames the balanced teams by index and returns the refreshed mix. Host or co-host only.",
    },
    "rpc.balancer.custom.set_role_mask": {
        "summary": "Set custom game role mask",
        "description": "Overrides how many seats of each role a team gets in this mix; null restores the workspace default shape. Host or co-host only.",
    },
    "rpc.balancer.custom.set_points_per_win": {
        "summary": "Set custom game points per win",
        "description": "Sets how far a decided match moves both teams' ranks in the host's own book, or null to record matches without touching ranks. Host or co-host only.",
    },
    "rpc.balancer.custom.set_next_map": {
        "summary": "Set custom game next map",
        "description": (
            "Names the map the mix's next match is played on -- rolled or picked by a host ahead of "
            "the lobby -- or clears it with null. The next recorded match takes this map unless the "
            "outcome names one explicitly, and clears it either way. Host or co-host only; 404 when "
            "the map is not in the catalogue."
        ),
    },
    "rpc.balancer.custom.set_discord_channel": {
        "summary": "Set custom game Discord channel",
        "description": (
            "Overrides the workspace-wide mix channel for this one mix, as a digits-only snowflake "
            "string, or clears the override with null so the workspace channel applies again. "
            "Workspace admin only -- an ordinary host cannot redirect the workspace's Discord. The id "
            "is not verified against Discord here, an unreachable channel surfaces when the bot tries "
            "to deliver."
        ),
    },
    "rpc.balancer.custom.post_discord": {
        "summary": "Post custom game lineup to Discord",
        "description": (
            "Queues an embed of one balance option's teams, the next map and the points at stake "
            "to the mix's own channel, or the workspace-wide mix channel when it has none, and "
            "returns immediately -- delivery is the bot's, and nothing about the mix changes. Host "
            "or co-host only; 409 when neither channel is configured and 404 when the balance option "
            "is missing."
        ),
    },
    "rpc.balancer.custom.set_balancer_config": {
        "summary": "Set custom game balancer config",
        "description": "Replaces the mix's solver overrides with a validated config, or clears them with null, and returns the refreshed mix. Host or co-host only.",
    },
    "rpc.balancer.custom.transfer_host": {
        "summary": "Transfer custom game host",
        "description": (
            "Hands primary ownership to another signed-in member of the workspace, dropping their "
            "co-host grant if they held one. Host or co-host only; 404 when the target has no linked "
            "login account here, since a host is an auth.user id and not a roster member."
        ),
    },
    "rpc.balancer.custom.add_co_host": {
        "summary": "Add custom game co-host",
        "description": (
            "Grants another signed-in workspace member the same write access as the host. Host or "
            "co-host only; 404 when the target has no linked login account here, and 422 once the "
            "mix is at its co-host limit."
        ),
    },
    "rpc.balancer.custom.remove_co_host": {
        "summary": "Remove custom game co-host",
        "description": "Revokes a co-host grant, including a co-host removing themselves, and returns the refreshed mix. An account that has since left the workspace stays revocable.",
    },
    "rpc.balancer.custom.swap_seats": {
        "summary": "Swap custom game seats",
        "description": (
            "Swaps two seated players between teams inside one balance option, same role only, and "
            "returns the refreshed mix. Host or co-host only; 404 when the option or either seat is "
            "missing, 422 when the seats hold different roles or sit on the same team."
        ),
    },
    "rpc.balancer.custom.record_outcome": {
        "summary": "Record custom game match",
        "description": (
            "Freezes one played match of a balance option into the mix's history, moving both teams' "
            "ranks in the host's book by points_per_win when a winner is given and redeeming every "
            "seat's must_play pin back to the pool. Host or co-host only, and repeatable until the "
            "mix is closed."
        ),
    },
    "rpc.balancer.custom.match_history": {
        "summary": "List custom game matches",
        "description": "Returns every match recorded for the mix, newest first, with team names, scores, winner and map. Public, no authentication required.",
    },
    "rpc.balancer.custom.undo_match": {
        "summary": "Undo custom game match",
        "description": (
            "Deletes the mix's most recent match and gives back exactly the rank points it applied, "
            "read from the match itself rather than the mix's current points_per_win. Host or "
            "co-host only; 404 when the match belongs to another mix and 409 when a newer match "
            "exists, since the rank book compounds. must_play pins the recording redeemed are not "
            "restored."
        ),
    },
    "rpc.balancer.custom.rotation": {
        "summary": "Get custom game rotation hints",
        "description": "Recommends who is owed the next seat and who should sit out, computed from this mix's own match history. Read-only and public, no authentication required.",
    },
    "rpc.balancer.custom.stats": {
        "summary": "Get custom game statistics",
        "description": (
            "Per-member wins/losses/draws, win rate, current streak and the per-role split across "
            "every mix this workspace has run, best record first. The optional since query parameter "
            "(ISO 8601) narrows it to matches recorded on or after that moment; without it the whole "
            "history counts. Read-only and public, no authentication required."
        ),
    },
    "rpc.balancer.custom.close": {
        "summary": "Close custom game",
        "description": (
            "Marks the mix completed so no further writes land. Nothing is destroyed -- the mix and "
            "every match it recorded stay readable -- so this is the reversible end of a mix, and any "
            "host or co-host may call it."
        ),
    },
    "rpc.balancer.custom.hard_delete": {
        "summary": "Delete custom game",
        "description": (
            "Permanently erases the mix together with its roster and every match it recorded, and "
            "returns the deleted id. Irreversible, and unlike close it is restricted to workspace "
            "admins rather than the mix's host and co-hosts."
        ),
    },
    "rpc.balancer.players.list": {
        "summary": "List workspace players",
        "description": (
            "Returns a page of the workspace roster carrying two rank dictionaries that are never "
            "merged: `ranks` is the workspace canon and `author_ranks` is one author's own book, "
            "which is what lets a row say whether a number is its own or inherited. Any workspace "
            "member may read another organiser's book through `author_user_id`."
        ),
    },
    "rpc.balancer.players.summary": {
        "summary": "Get workspace roster summary",
        "description": 'Returns the workspace roster size alongside how many of those members the read author has personally ranked, which is what the "My ranks" filter counts. Open to any workspace member.',
    },
    "rpc.balancer.players.upsert": {
        "summary": "Upsert workspace player",
        "description": "Creates or reuses a workspace member for a BattleTag and returns it shaped exactly like a roster row. Open to any workspace member; 422 when battle_tag is missing or blank.",
    },
    "rpc.balancer.players.set_ranks": {
        "summary": "Set workspace player ranks",
        "description": (
            'Writes one rank layer for a member and returns that layer. `scope: "workspace"` edits '
            'the shared canon every author inherits; `scope: "author"` edits the caller\'s own book '
            "and takes no author id, so nobody can rewrite another organiser's ranks. `clear` deletes "
            "roles from the layer instead of zeroing them, so a cleared author rank falls back to "
            "canon, while an omitted role is left alone. 404 when the member belongs to another "
            "workspace."
        ),
    },
    "rpc.balancer.players.authors": {
        "summary": "List rank authors",
        "description": "Returns everyone who has personally rank-corrected a member in this workspace, busiest first, with their display name and correction count. Open to any workspace member.",
    },
    "rpc.balancer.teams.export_registered": {
        "summary": "Export registered teams",
        "description": (
            "Materializes the tournament's complete registered teams into balancer teams, optionally "
            "narrowed to given team ids, and returns removed/imported/created counts plus every team "
            "skipped and why. Requires admin panel access and workspace team-create permission, and "
            "emits a teams-changed realtime event when anything was imported."
        ),
    },
}
