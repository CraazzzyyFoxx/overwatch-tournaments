"""Human-readable docs (summary + description) for balancer-service RPC
subjects, merged into the gateway's OpenAPI by the export script. Prose only.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    "rpc.balancer.config": {
        "summary": "Get balancer config",
        "description": "Permission: public; no authentication required. Returns the public balancer configuration (ranks, roles, defaults).",
    },
    "rpc.balancer.admin.tournament_config_get": {
        "summary": "Get tournament balancer config",
        "description": "Permission: admin-panel access plus workspace `team.read`. Returns the per-tournament balancer config, or null when none is set.",
    },
    "rpc.balancer.admin.tournament_config_upsert": {
        "summary": "Upsert tournament balancer config",
        "description": "Permission: admin-panel access plus workspace `team.create`. Creates or updates the per-tournament balancer config and emits a balancer config-changed realtime event.",
    },
    "rpc.balancer.admin.tournament_summary_get": {
        "summary": "Get tournament summary",
        "description": "Permission: admin-panel access plus workspace `team.read`. Returns the tournament id/name/status/workspace_id for the balancer tool context, hidden tournaments included.",
    },
    "rpc.balancer.admin.balance_get": {
        "summary": "Get saved balance",
        "description": "Permission: admin-panel access plus workspace `team.read`. Returns the saved team balance for a tournament, or null when none exists.",
    },
    "rpc.balancer.admin.balance_save": {
        "summary": "Save tournament balance",
        "description": "Permission: admin-panel access plus workspace `team.create`. Persists a computed team balance for the tournament and emits a balance-saved realtime event.",
    },
    "rpc.balancer.admin.balance_export": {
        "summary": "Export balance to teams",
        "description": (
            "Permission: admin-panel access plus `team.create` on the balance's workspace. "
            "Materializes a saved balance into tournament teams, returning removed/imported counts "
            "and emitting a teams-changed realtime event."
        ),
    },
    "rpc.balancer.admin.balance_ranks_export": {
        "summary": "Re-export balance ranks",
        "description": (
            "Permission: admin-panel access plus `team.create` on the balance's workspace. "
            "Updates the ranks of players already materialized from the saved balance, "
            "without removing or creating any team, and emits a teams-changed realtime event."
        ),
    },
    "rpc.balancer.admin.workspace_config_get": {
        "summary": "Get workspace balancer config",
        "description": (
            "Permission: admin-panel access plus workspace `workspace.read`. "
            "Returns the workspace-level balancer config (rank-delta threshold, pool-hide flag and "
            "the Discord channel every mix posts its matchup to)."
        ),
    },
    "rpc.balancer.admin.workspace_config_upsert": {
        "summary": "Upsert workspace balancer config",
        "description": (
            "Permission: admin-panel access plus workspace `team.update`, and additionally "
            "`workspace.update` when the Discord channel actually changes. "
            "Creates or updates the workspace-level rank-delta threshold, hide-from-pool flag and the "
            "workspace-wide Discord channel for mix matchups."
        ),
    },
    "rpc.balancer.admin.teams_import": {
        "summary": "Import teams file",
        "description": "Permission: admin-panel access plus workspace `team.create`. Bulk-imports tournament teams from a multipart JSON upload (atravkovs or internal format, auto-detected) and emits a teams-changed realtime event.",
    },
    "rpc.balancer.jobs.create": {
        "summary": "Create balance job",
        "description": (
            "Permission: workspace `team.create` on the given workspace_id; an API-key caller must "
            "also be scoped to that workspace and hold the `team.create` scope. "
            "Queues an asynchronous balance job from a multipart player-data upload plus optional "
            "config overrides, returning 202 with the job id."
        ),
    },
    "rpc.balancer.jobs.create_for_tournament": {
        "summary": "Balance tournament pool",
        "description": (
            "Permission: workspace `team.create` on the tournament's workspace; an API-key caller "
            "must also be scoped to that workspace and hold the `team.create` scope. "
            "Queues an asynchronous balance job built server-side from the tournament's own pool "
            "registrations -- nothing is uploaded -- returning 202 with the job id; 422 when no pool "
            "registration has a ranked role."
        ),
    },
    "rpc.balancer.jobs.status": {
        "summary": "Get balance job status",
        "description": (
            "Permission: workspace `team.create` on the job's own workspace, and an API key may read "
            "only the jobs it created itself. Returns the current status of a balance job by its uuid."
        ),
    },
    "rpc.balancer.jobs.result": {
        "summary": "Get balance job result",
        "description": (
            "Permission: workspace `team.create` on the job's own workspace, and an API key may read "
            "only the jobs it created itself. Returns the computed result of a completed balance job "
            "by its uuid."
        ),
    },
    "rpc.balancer.balance": {
        "summary": "Balance a pool synchronously",
        "description": (
            "Permission: workspace `team.create` on the given workspace_id; an API-key caller must "
            "also be scoped to that workspace and hold the `team.create` scope. "
            "Solves the posted pool and returns the ranked variants in the same response -- no job "
            "id, no polling, no realtime events. Everything the solver needs is in the body "
            "(`player_data`, optional per-team `role_mask`, optional `config_overrides`); nothing is "
            "read from the workspace. The solver budget is clamped to 60s, so a pool too large to "
            "settle in time answers 504 and belongs on the asynchronous job API instead. Rate "
            "limits, the per-key config policy and the concurrency slot are the job path's."
        ),
    },
    "rpc.balancer.draft.tournament_board": {
        "summary": "Get tournament draft board",
        "description": "Permission: public; no authentication required. Returns the live draft board snapshot for a tournament's active session, or null when no session is active.",
    },
    "rpc.balancer.draft.session_get": {
        "summary": "Get draft session",
        "description": "Permission: public; no authentication required. Returns a single draft session by id for spectating.",
    },
    "rpc.balancer.draft.session_board": {
        "summary": "Get draft session board",
        "description": "Permission: public; no authentication required. Returns the full draft board snapshot (teams, picks, pool) for a given session id.",
    },
    "rpc.balancer.draft.suggestions": {
        "summary": "Get pick suggestions",
        "description": "Permission: workspace `team.read`. Ranks the top five available players by fit for the current pick; 409 if the draft has no current pick.",
    },
    "rpc.balancer.draft.feasibility": {
        "summary": "Get draft feasibility",
        "description": "Permission: workspace `team.create`. Reports whether every remaining team-role slot can be filled.",
    },
    "rpc.balancer.draft.pick_options": {
        "summary": "Get safe draft pick options",
        "description": "Permission: the on-clock captain of the pick's team, or a workspace admin. Returns safe and blocked player-role choices for the current pick.",
    },
    "rpc.balancer.draft.player_role_edit": {
        "summary": "Preview or add a draft player role",
        "description": "Permission: workspace `team.create`. Previews or commits an emergency role addition to the draft snapshot with optimistic versioning and private audit reason.",
    },
    "rpc.balancer.draft.team_fit": {
        "summary": "Get team fit scores",
        "description": (
            "Permission: the team's own captain, or workspace `team.read`. Scores every available "
            "player against every role this team can still seat, normalized 1..99 across the "
            "response (50 when all candidates tie). `role` is null under a role-less (all-flex) "
            "roster shape, where each player has exactly one entry. Empty once the team's roster is "
            "full or the draft is completed/cancelled."
        ),
    },
    "rpc.balancer.draft.queue_get": {
        "summary": "Get captain pick queue",
        "description": (
            "Permission: the team's own captain, or workspace `team.create`. Returns the team's "
            "private autopick priority in stored order, filtered to players still available, plus "
            "`autopick_preview` -- exactly what autopick would take -- while this team is on the "
            "clock. Never part of the public board."
        ),
    },
    "rpc.balancer.draft.queue_set": {
        "summary": "Set captain pick queue",
        "description": (
            "Permission: the team's own captain, or workspace `team.create`. Replaces the queue "
            "with the given order (max 60, duplicates collapsed to their first placement); 422 when "
            "an id is not an available non-captain player of this draft, 409 once the draft is "
            "completed or cancelled. Publishes no realtime event -- a queue is private to its team."
        ),
    },
    "rpc.balancer.draft.journal": {
        "summary": "Get draft organizer journal",
        "description": (
            "Permission: workspace `team.create`. Returns the session's audit trail newest first -- "
            "picks, autopicks, overrides, clock extensions and every lifecycle move -- with the "
            "acting account's name resolved (null for the clock and other system actions). `limit` "
            "defaults to 100 and is clamped to 500."
        ),
    },
    "rpc.balancer.draft.session_list": {
        "summary": "List tournament draft sessions",
        "description": "Permission: workspace `team.read`. Returns every draft session ever created for a tournament, newest first.",
    },
    "rpc.balancer.draft.session_delete": {
        "summary": "Delete draft session",
        "description": "Permission: workspace `team.create`. Permanently erases a draft session with its teams, pool, picks and audit trail; 409 while the draft is live or paused. Teams already exported to the tournament are kept.",
    },
    "rpc.balancer.draft.session_create": {
        "summary": "Create draft session",
        "description": "Permission: workspace `team.create`. Creates a new draft session for a tournament and publishes a session-updated realtime event.",
    },
    "rpc.balancer.draft.seed": {
        "summary": "Seed draft session",
        "description": "Permission: workspace `team.create`. Seeds a draft session with captains and players from the balancer pool; 422 when no pool captains are provided.",
    },
    "rpc.balancer.draft.session_patch": {
        "summary": "Patch draft session",
        "description": "Permission: workspace `team.create`. Updates mutable draft settings (pick time, autopick strategy, override flag, rounds, settings) before the draft starts.",
    },
    "rpc.balancer.draft.start": {
        "summary": "Start draft session",
        "description": "Permission: workspace `team.create`, and only a superuser may start outside the tournament's draft phase. Starts the draft and opens the first pick, publishing a pick-started realtime event with the clock deadline.",
    },
    "rpc.balancer.draft.pause": {
        "summary": "Pause draft session",
        "description": "Permission: workspace `team.create`. Pauses an in-progress draft and publishes a draft-paused realtime event.",
    },
    "rpc.balancer.draft.resume": {
        "summary": "Resume draft session",
        "description": "Permission: workspace `team.create`. Resumes a paused draft and publishes a draft-resumed realtime event.",
    },
    "rpc.balancer.draft.cancel": {
        "summary": "Cancel draft session",
        "description": "Permission: workspace `team.create`. Cancels the draft and publishes a draft-cancelled realtime event.",
    },
    "rpc.balancer.draft.rollback": {
        "summary": "Rollback draft pick",
        "description": "Permission: workspace `team.create`. Rolls back the most recent draft action and publishes a rollback realtime event.",
    },
    "rpc.balancer.draft.export": {
        "summary": "Export draft to teams",
        "description": "Permission: workspace `team.create`. Finalizes the drafted rosters into tournament teams and publishes a draft-completed realtime event.",
    },
    "rpc.balancer.draft.export_ranks": {
        "summary": "Re-export draft ranks",
        "description": (
            "Permission: workspace `team.create`. Updates the ranks of players already exported from "
            "this completed draft, leaving the tournament teams themselves untouched."
        ),
    },
    "rpc.balancer.draft.pick_select": {
        "summary": "Select draft pick",
        "description": "Permission: the on-clock captain of the pick's team, or a workspace admin. Makes a pick for the current slot, enforcing role fit and optimistic version, then broadcasts pick-made/next-pick events.",
    },
    "rpc.balancer.draft.pick_autopick": {
        "summary": "Autopick draft pick",
        "description": "Permission: workspace `team.create`. Auto-selects the best-fit available player for a pick using the session's autopick strategy and broadcasts the result.",
    },
    "rpc.balancer.draft.pick_extend": {
        "summary": "Extend draft pick clock",
        "description": "Permission: workspace `team.create`. Adds seconds to the current on-clock pick — to its deadline while the draft is live, to the frozen remainder while it is paused — and broadcasts the new deadline.",
    },
    "rpc.balancer.draft.pick_override": {
        "summary": "Override draft pick",
        "description": "Permission: workspace `team.create`. Overrides a pick to an arbitrary player, bypassing captain/clock constraints, and broadcasts a pick-made event.",
    },
    "rpc.balancer.custom.create": {
        "summary": "Create custom game",
        "description": (
            "Permission: workspace membership plus `custom_game.create`. "
            "Opens a pickup mix in the workspace and returns it with its roster; the caller becomes "
            "its host, and member_ids may be empty to start from an empty lineup. With "
            "clone_from_game_id the new mix starts from a "
            "previous mix of the same workspace -- its pool (everyone back in the pool), per-seat "
            "role setup, role shape, points per win, team names, solver overrides and co-hosts -- "
            "but never its balance result, rolled map, match history or status."
        ),
    },
    "rpc.balancer.custom.list": {
        "summary": "List custom games",
        "description": "Permission: public; no authentication required. Returns every mix in the workspace with its settings and host display name, but without rosters.",
    },
    "rpc.balancer.custom.get": {
        "summary": "Get custom game",
        "description": (
            "Permission: public; no authentication required. "
            "Returns one mix with its full lineup: each seat's participation state, role "
            "order, the ranks the balancer would use and which layer each came from. "
            "404 when the mix belongs to another workspace."
        ),
    },
    "rpc.balancer.custom.update_roster": {
        "summary": "Replace custom game roster",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Replaces the mix lineup with the given workspace_member ids (at most 100) and returns "
            "the refreshed mix. A member with no linked login account can be "
            "rostered here, unlike the host and co-host grants."
        ),
    },
    "rpc.balancer.custom.update_player": {
        "summary": "Update custom game player",
        "description": "Permission: workspace membership plus being the mix's host or co-host (or a superuser). Patches one seat's participation state, role order or flex flag and returns the refreshed mix; 404 when the member is not on this mix's roster.",
    },
    "rpc.balancer.custom.set_participation": {
        "summary": "Set custom game participation",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Moves several seats between must_play, pool and benched in one transaction -- the whole "
            "rotation verdict at once -- and returns the refreshed mix; 404 if "
            "any member is not on the roster."
        ),
    },
    "rpc.balancer.custom.balance": {
        "summary": "Balance custom game",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Balances the non-benched lineup, reading the host's own rank book above the workspace "
            "canon, stores the resulting options on the mix and returns it; "
            "422 when the lineup is empty or a seated player has no ranked role."
        ),
    },
    "rpc.balancer.custom.set_team_names": {
        "summary": "Set custom game team names",
        "description": "Permission: workspace membership plus being the mix's host or co-host (or a superuser). Renames the balanced teams by index and returns the refreshed mix.",
    },
    "rpc.balancer.custom.set_next_map": {
        "summary": "Set custom game next map",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Names the map the mix's next match is played on -- rolled or picked by a host ahead of "
            "the lobby -- or clears it with null. The next recorded match takes this map unless the "
            "outcome names one explicitly, and clears it either way. 404 when "
            "the map is not in the catalogue."
        ),
    },
    "rpc.balancer.custom.set_variant_index": {
        "summary": "Set custom game shown balance option",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Pages the mix to one of the balance options its last run produced, for every viewer at "
            "once -- the option on screen is a fact about the mix, not about one browser. "
            "404 when the index points past the stored options. Re-balancing resets it "
            "to the first option."
        ),
    },
    "rpc.balancer.custom.post_discord": {
        "summary": "Post custom game lineup to Discord",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Queues an embed of one balance option's teams, the next map and the points at stake "
            "to the workspace-wide mix channel and returns immediately -- delivery is the bot's, "
            "and nothing about the mix changes. 409 when the workspace has "
            "no mix channel configured and 404 when the balance option is missing."
        ),
    },
    "rpc.balancer.custom.transfer_host": {
        "summary": "Transfer custom game host",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Hands primary ownership to another signed-in member of the workspace, dropping their "
            "co-host grant if they held one. 404 when the target has no linked "
            "login account here, since a host is an auth.user id and not a roster member."
        ),
    },
    "rpc.balancer.custom.add_co_host": {
        "summary": "Add custom game co-host",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Grants another signed-in workspace member the same write access as the host. "
            "404 when the target has no linked login account here, and 422 once the "
            "mix is at its co-host limit."
        ),
    },
    "rpc.balancer.custom.remove_co_host": {
        "summary": "Remove custom game co-host",
        "description": "Permission: workspace membership plus being the mix's host or co-host (or a superuser). Revokes a co-host grant, including a co-host removing themselves, and returns the refreshed mix. An account that has since left the workspace stays revocable.",
    },
    "rpc.balancer.custom.swap_seats": {
        "summary": "Swap custom game seats",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Swaps two seated players between teams inside one balance option, same role only, and "
            "returns the refreshed mix. 404 when the option or either seat is "
            "missing, 422 when the seats hold different roles or sit on the same team."
        ),
    },
    "rpc.balancer.custom.record_outcome": {
        "summary": "Record custom game match",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Freezes one played match of a balance option into the mix's history, moving both teams' "
            "ranks in the host's book by points_per_win when a winner is given and redeeming every "
            "seat's must_play pin back to the pool. Repeatable until the "
            "mix is closed."
        ),
    },
    "rpc.balancer.custom.match_history": {
        "summary": "List custom game matches",
        "description": "Permission: public; no authentication required. Returns every match recorded for the mix, newest first, with team names, scores, winner and map.",
    },
    "rpc.balancer.custom.undo_match": {
        "summary": "Undo custom game match",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Deletes the mix's most recent match and gives back exactly the rank points it applied, "
            "read from the match itself rather than the mix's current points_per_win. "
            "404 when the match belongs to another mix and 409 when a newer match "
            "exists, since the rank book compounds. must_play pins the recording redeemed are not "
            "restored."
        ),
    },
    "rpc.balancer.custom.rotation": {
        "summary": "Get custom game rotation hints",
        "description": "Permission: public; no authentication required. Recommends who is owed the next seat and who should sit out, computed from this mix's own match history, read-only.",
    },
    "rpc.balancer.custom.stats": {
        "summary": "Get custom game statistics",
        "description": (
            "Permission: public; no authentication required. "
            "Per-member wins/losses/draws, win rate, current streak and the per-role split across "
            "every mix this workspace has run, best record first. The optional since query parameter "
            "(ISO 8601) narrows it to matches recorded on or after that moment; without it the whole "
            "history counts. Read-only."
        ),
    },
    "rpc.balancer.custom.close": {
        "summary": "Close custom game",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Marks the mix completed so no further writes land. Nothing is destroyed -- the mix and "
            "every match it recorded stay readable -- so this is the reversible end of a mix."
        ),
    },
    "rpc.balancer.custom.hard_delete": {
        "summary": "Delete custom game",
        "description": (
            "Permission: workspace membership plus the workspace `admin` or `owner` role (superuser "
            "counts). Permanently erases the mix together with its roster and every match it "
            "recorded, and returns the deleted id. Irreversible, and unlike close it is not open to "
            "the mix's own host and co-hosts."
        ),
    },
    "rpc.balancer.players.list": {
        "summary": "List workspace players",
        "description": (
            "Permission: workspace membership (any role); no resource grant is checked. "
            "Returns a page of the workspace roster carrying two rank dictionaries that are never "
            "merged: `ranks` is the workspace canon and `author_ranks` is one author's own book, "
            "which is what lets a row say whether a number is its own or inherited. Another "
            "organiser's book is readable through `author_user_id`."
        ),
    },
    "rpc.balancer.players.summary": {
        "summary": "Get workspace roster summary",
        "description": 'Permission: workspace membership (any role); no resource grant is checked. Returns the workspace roster size alongside how many of those members the read author has personally ranked, which is what the "My ranks" filter counts.',
    },
    "rpc.balancer.players.upsert": {
        "summary": "Upsert workspace player",
        "description": "Permission: workspace member holding team.create or custom_game.create (a mix host); setting display_name requires team.create. Creates or reuses a workspace member for a BattleTag and returns it shaped exactly like a roster row; 422 when battle_tag is missing or blank.",
    },
    "rpc.balancer.players.set_ranks": {
        "summary": "Set workspace player ranks",
        "description": (
            "Permission: workspace membership (any role); no resource grant is checked. "
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
        "description": "Permission: workspace membership (any role); no resource grant is checked. Returns everyone who has personally rank-corrected a member in this workspace, busiest first, with their display name and correction count.",
    },
    "rpc.balancer.teams.export_registered": {
        "summary": "Export registered teams",
        "description": (
            "Permission: admin-panel access plus workspace `team.create`. "
            "Materializes the tournament's complete registered teams into balancer teams, optionally "
            "narrowed to given team ids, and returns removed/imported/created counts plus every team "
            "skipped and why, and "
            "emits a teams-changed realtime event when anything was imported."
        ),
    },
    "rpc.balancer.prefs.get": {
        "summary": "Get my pickup mix preferences",
        "description": (
            "Permission: self-service -- any authenticated (active) account reads its own "
            "preferences only. "
            "Returns the signed-in account's own mix settings -- the rank-balance/role-comfort tilt, "
            "the per-role weights, how many balance options to keep, the roster shape its mixes "
            "field and how far a decided match moves its rank book -- plus roster_shape, the "
            "read-only resolution of that shape. A null value means the setting was never saved and "
            "the default applies."
        ),
    },
    "rpc.balancer.prefs.upsert": {
        "summary": "Set my pickup mix preferences",
        "description": (
            "Permission: self-service -- any authenticated (active) account writes its own "
            "preferences only. "
            "Replaces all five of the caller's mix settings at once and returns the stored result "
            "with the re-resolved roster_shape; a null clears one back to the default, and 0 points "
            "per win stores as unset. They apply to every mix this account hosts -- a mix runs on "
            "its host's preferences whoever presses the button. 422 on an impossible roster shape."
        ),
    },
    "rpc.balancer.draft.chat_history": {
        "summary": "Read the draft room chat",
        "description": (
            "Permission: optional authentication. Captains of the session's teams and the workspace's "
            "staff always read; anybody else reads while the room's `spectators_can_read` is on, which "
            "a draft room has ON by default (a draft is a show). A hidden tournament is visible only "
            "to its workspace's admins and its preview allowlist. The room is the SESSION, so a "
            "re-seed starts a new conversation. Returns the messages plus the room settings, the "
            "caller's own viewer rights and — for moderators only — the active mutes. `after_id` "
            "tails the room; `limit` pages it."
        ),
    },
    "rpc.balancer.draft.chat_post": {
        "summary": "Post to the draft room chat",
        "description": (
            "Permission: authenticated captain of one of the session's teams, or workspace staff; "
            "spectators never write, at any setting. The body is sanitized and capped at 500 "
            "characters. 403 with code `chat_muted` while the account is muted in this room, 429 past "
            "10 messages per 10 seconds. Returns the stored message, which is also fanned out to the "
            "room's realtime topic."
        ),
    },
    "rpc.balancer.draft.chat_delete": {
        "summary": "Delete a draft chat message",
        "description": (
            "Permission: the message's author, or a moderator of the room (workspace staff). "
            "Soft-deletes one message and publishes the removal to the room's subscribers. "
            "404 when the id is not a message of this room. Answers `{deleted: true}`."
        ),
    },
    "rpc.balancer.draft.chat_settings": {
        "summary": "Set draft chat visibility",
        "description": (
            "Permission: moderator of the room (workspace staff). Opens or closes the room to "
            "spectators and returns the stored setting. Closing it also revokes the spectators "
            "already subscribed to the room's realtime topic; a no-op toggle emits nothing."
        ),
    },
    "rpc.balancer.draft.chat_mute_set": {
        "summary": "Mute an account in the draft chat",
        "description": (
            "Permission: moderator of the room (workspace staff). Mutes one account in this room for "
            "`minutes` (1..10080), or until lifted when `minutes` is null, with an optional reason. "
            "422 on muting yourself. Returns the mute."
        ),
    },
    "rpc.balancer.draft.chat_mute_clear": {
        "summary": "Unmute an account in the draft chat",
        "description": (
            "Permission: moderator of the room (workspace staff). Lifts one account's mute in this "
            "room, idempotent. Answers `{deleted: true}`."
        ),
    },
}
