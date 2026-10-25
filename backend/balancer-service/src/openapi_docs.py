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
            "and emitting a teams-changed realtime event. Returns advisories for format violations "
            "and names unresolved or duplicate members skipped by the export."
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
            "workspace-wide Discord channel for mix matchups. A newly set Discord id (mix channel, voice "
            "category, general voices) must be a text channel, category or voice channel of the "
            "workspace's own guild: 409 discord_guild_not_linked when the workspace has no guild, 422 "
            "discord_channel_not_in_guild, 503 discord_unavailable when Discord cannot be asked. "
            "Clearing a value or keeping it unchanged asks Discord nothing."
        ),
    },
    "rpc.balancer.admin.workspace_ranker_get": {
        "summary": "Get workspace mix ranker settings",
        "description": (
            "Permission: admin-panel access plus workspace `workspace.read`. "
            "Returns the mix ranker's knobs in force for this workspace (the defaults when never saved) "
            "and how many hidden ratings its members hold. The ranker implements mixtura-ranker by "
            "Dmitriy (@dmelackov), https://github.com/mixtura-dev/mixtura-ranker."
        ),
    },
    "rpc.balancer.admin.workspace_ranker_upsert": {
        "summary": "Set workspace mix ranker settings",
        "description": (
            "Permission: admin-panel access plus workspace `team.update`. "
            "Replaces all seven knobs at once. Changing rating_min, rating_max, rating_avg or sigma_init "
            "reinterprets every stored hidden rating, so the call rebuilds them from the workspace's "
            "recorded mix matches before answering. 422 unless rating_min < rating_avg < rating_max."
        ),
    },
    "rpc.balancer.admin.workspace_ranker_rebuild": {
        "summary": "Rebuild hidden mix ratings from history",
        "description": (
            "Permission: admin-panel access plus workspace `team.update`. "
            "Replays every recorded mix match of the workspace in order and replaces all hidden ratings "
            "with the result; open ranks are not touched. Returns how many matches were replayed and "
            "how many hidden ratings came out."
        ),
    },
    "rpc.balancer.admin.teams_import": {
        "summary": "Import teams file",
        "description": "Permission: admin-panel access plus workspace `team.create`. Bulk-imports tournament teams from a multipart JSON upload (atravkovs or internal format, auto-detected) and emits a teams-changed realtime event. Returns advisories for format violations and names skipped unresolved or duplicate members.",
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
        "description": "Permission: a tournament workspace's `team.read`, or the mix's hosts. Ranks the top five available players by fit for the current pick; 409 if the draft has no current pick.",
    },
    "rpc.balancer.draft.feasibility": {
        "summary": "Get draft feasibility",
        "description": "Permission: a tournament workspace's `team.read`, or the mix's hosts. Reports whether every remaining team-role slot can be filled.",
    },
    "rpc.balancer.draft.pick_options": {
        "summary": "Get safe draft pick options",
        "description": "Permission: the on-clock captain of the pick's team, or a workspace admin. Returns safe and blocked player-role choices for the current pick. A tournament's workspace admin or a mix's host may pick for whichever team is on the clock.",
    },
    "rpc.balancer.draft.player_role_edit": {
        "summary": "Preview or add a draft player role",
        "description": "Permission: whoever runs the session's owner -- a tournament workspace's `team.create`, or the mix's host or a co-host (or a superuser). Previews or commits an emergency role addition to the draft snapshot with optimistic versioning and private audit reason; 422 `role_edit_tournament_only` on a mix's draft, whose ranks are edited in the mix.",
    },
    "rpc.balancer.draft.team_fit": {
        "summary": "Get team fit scores",
        "description": (
            "Permission: that team's own captain, or whoever runs the draft. Scores every available "
            "player against every role this team can still seat, normalized 1..99 across the "
            "response (50 when all candidates tie). `role` is null under a role-less (all-flex) "
            "roster shape, where each player has exactly one entry. Empty once the team's roster is "
            "full or the draft is completed/cancelled."
        ),
    },
    "rpc.balancer.draft.queue_get": {
        "summary": "Get captain pick queue",
        "description": (
            "Permission: that team's own captain, or whoever runs the draft. Returns the team's "
            "private autopick priority in stored order, filtered to players still available, plus "
            "`autopick_preview` -- exactly what autopick would take -- while this team is on the "
            "clock. Never part of the public board."
        ),
    },
    "rpc.balancer.draft.queue_set": {
        "summary": "Set captain pick queue",
        "description": (
            "Permission: that team's own captain, or whoever runs the draft. Replaces the queue "
            "with the given order (max 60, duplicates collapsed to their first placement); 422 when "
            "an id is not an available non-captain player of this draft, 409 once the draft is "
            "completed or cancelled. Publishes no realtime event -- a queue is private to its team."
        ),
    },
    "rpc.balancer.draft.journal": {
        "summary": "Get draft organizer journal",
        "description": (
            "Permission: whoever runs the session's owner -- a tournament workspace's `team.create`, or the mix's host or a co-host (or a superuser). Returns the session's audit trail newest first -- "
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
        "description": "Permission: workspace `team.create`. Creates a new draft session for a tournament and publishes a session-updated realtime event. The draft format (and, for `custom`, its round rules) comes from the tournament's `draft_format_json`, not from the request.",
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
        "description": "Permission: whoever runs the session's owner -- a tournament workspace's `team.create`, or the mix's host or a co-host (or a superuser), and only a superuser may start a tournament's draft outside its draft phase (a mix draft has no phase). Starts the draft and opens the first pick, publishing a pick-started realtime event with the clock deadline.",
    },
    "rpc.balancer.draft.pause": {
        "summary": "Pause draft session",
        "description": "Permission: whoever runs the session's owner -- a tournament workspace's `team.create`, or the mix's host or a co-host (or a superuser). Pauses an in-progress draft and publishes a draft-paused realtime event.",
    },
    "rpc.balancer.draft.resume": {
        "summary": "Resume draft session",
        "description": "Permission: whoever runs the session's owner -- a tournament workspace's `team.create`, or the mix's host or a co-host (or a superuser). Resumes a paused draft and publishes a draft-resumed realtime event.",
    },
    "rpc.balancer.draft.cancel": {
        "summary": "Cancel draft session",
        "description": "Permission: whoever runs the session's owner -- a tournament workspace's `team.create`, or the mix's host or a co-host (or a superuser). Cancels the draft and publishes a draft-cancelled realtime event.",
    },
    "rpc.balancer.draft.rollback": {
        "summary": "Rollback draft pick",
        "description": "Permission: whoever runs the session's owner -- a tournament workspace's `team.create`, or the mix's host or a co-host (or a superuser). Rolls back the most recent draft action and publishes a rollback realtime event. A mix draft refuses to roll back the pick that seated its team's current captain (409 rollback_frees_captain): the host replaces the captain with a player who stays first.",
    },
    "rpc.balancer.draft.export": {
        "summary": "Export draft to teams",
        "description": "Permission: workspace `team.create`. Finalizes the drafted rosters into tournament teams and publishes a draft-completed realtime event. The returned session includes advisories for format violations and names skipped unresolved or duplicate members.",
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
        "description": "Permission: the on-clock captain of the pick's team, or a workspace admin. Makes a pick for the current slot, enforcing role fit and optimistic version, then broadcasts pick-made/next-pick events. A tournament's workspace admin or a mix's host may pick for whichever team is on the clock.",
    },
    "rpc.balancer.draft.pick_autopick": {
        "summary": "Autopick draft pick",
        "description": "Permission: whoever runs the session's owner -- a tournament workspace's `team.create`, or the mix's host or a co-host (or a superuser). Auto-selects the best-fit available player for a pick using the session's autopick strategy and broadcasts the result.",
    },
    "rpc.balancer.draft.pick_extend": {
        "summary": "Extend draft pick clock",
        "description": "Permission: whoever runs the session's owner -- a tournament workspace's `team.create`, or the mix's host or a co-host (or a superuser). Adds seconds to the current on-clock pick — to its deadline while the draft is live, to the frozen remainder while it is paused — and broadcasts the new deadline.",
    },
    "rpc.balancer.draft.pick_override": {
        "summary": "Override draft pick",
        "description": "Permission: whoever runs the session's owner -- a tournament workspace's `team.create`, or the mix's host or a co-host (or a superuser). Overrides a pick to an arbitrary player, bypassing captain/clock constraints, and broadcasts a pick-made event.",
    },
    "rpc.balancer.custom.create": {
        "summary": "Create custom game",
        "description": (
            "Permission: workspace membership plus `custom_game.create`. "
            "Opens a pickup mix of the requested game (`discipline`, required) in the workspace and returns it with "
            "its roster; the caller becomes "
            "its host, and member_ids may be empty to start from an empty lineup. With "
            "clone_from_game_id the new mix starts from a "
            "previous mix of the same workspace -- its pool (everyone back in the pool), per-seat "
            "role setup, role shape, points per win, team names, solver overrides and co-hosts -- "
            "but never its balance result, rolled map, match history or status."
        ),
    },
    "rpc.balancer.custom.list": {
        "summary": "List custom games",
        "description": (
            "Permission: public; no authentication required. One keyset page of the workspace's mixes, newest "
            "first: `{items, next_before_id}`. Each item carries the mix's settings and host display name (no "
            "roster), `players_count` (distinct members seated across its recorded matches), `roster_count`, the "
            "most recently played `maps` (at most 4, with `maps_count` for all of them) and every lobby's "
            "`matches_count`. Optional query: `discipline` (an installed game), `status` (`open` = draft or "
            "balanced, `history` = completed or cancelled; anything else is a 422), `q` (case-insensitive "
            "substring of the mix name or the host's display name), `limit` (1..100, default 30) and `before_id` "
            "(pass the previous page's `next_before_id`; null means there is no further page)."
        ),
    },
    "rpc.balancer.custom.get": {
        "summary": "Get custom game",
        "description": (
            "Permission: public; no authentication required. "
            "Returns one mix with its full lineup: each seat's participation state, role "
            "order, the ranks the balancer would use and which layer each came from. "
            "Resolves ownership from the mix id; an optional workspace_id restricts the read "
            "and returns 404 if the mix belongs to another workspace."
            " It carries the mix's hero_ban_preset (null = no bans)."
            " It carries hero_fearless (spec §11.4), and hero_ban_seconds / hero_pick_seconds (the hero room's clock"
            " per ban / per pick step in seconds; null = the preset's own)."
            " Each lobby carries state (idle | ready | pregame | live), live_seats (the live match's participations"
            " {id, slot, name}) and opener_index (the lineup team that bans first in the next match, null without"
            " bans)."
            " A lobby's `state` reads `draft_setup` / `draft_live` while its draft runs, with `draft_session_id`;"
            " a drafted lineup's document carries `source: \"draft\"`. A player in a drafting lobby's pool reads"
            " that lobby as `current_lobby`; an unpicked player who stepped away leaves the pool."
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
        "description": "Permission: workspace membership plus being the mix's host or co-host (or a superuser). Patches one seat's participation state, role order, flex flag or away flag and returns the refreshed mix; 404 when the member is not on this mix's roster. An away flag that flips reaches the lobby's running draft: a picked player stepping away, or a pool left unable to fill every role, pauses a live draft (a return never does), and its board re-reads the seats either way.",
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
    "rpc.balancer.custom.self_get": {
        "summary": "Get my mix seat",
        "description": (
            "Permission: any authenticated account; workspace membership is NOT required. "
            "Returns the caller's own seat in the mix (participation, role order, the ranks the "
            "host's book resolves for them) plus what they may do next: join, leave, edit roles, "
            "and the blocker code for each. `seat` is null when the caller is not on the roster."
        ),
    },
    "rpc.balancer.custom.self_current": {
        "summary": "Get my seat in the current mix",
        "description": (
            "Permission: any authenticated account; workspace membership is NOT required. "
            "Same answer as `self_get`, for the workspace's newest mix that is neither completed "
            "nor cancelled -- what `/mix` in Discord asks, where the player names no id. "
            "404 when the workspace is running nothing."
        ),
    },
    "rpc.balancer.custom.self_join": {
        "summary": "Join a mix myself",
        "description": (
            "Permission: any authenticated account with both Discord and Battle.net linked and "
            "`custom_game.self_join` not denied; workspace membership is created on the way in. "
            "Seats the caller according to the mix's signup mode (pool or bench) and returns the "
            "same state as the read. Idempotent: an existing row is left untouched, bench included. "
            "403 for an unlinked account, 409 when signup is closed, the mix is over or the roster "
            "is full."
        ),
    },
    "rpc.balancer.custom.self_leave": {
        "summary": "Leave a mix myself",
        "description": (
            "Permission: any authenticated account holding a seat in this mix -- the account links "
            "are deliberately NOT required, so unlinking one cannot trap somebody in a lineup. "
            "Removes the caller's own roster row; the stored balance is kept until the host "
            "re-balances. 404 when the caller has no seat, 409 once the mix is over."
        ),
    },
    "rpc.balancer.custom.self_update": {
        "summary": "Update my mix seat",
        "description": (
            "Permission: a seated account, while the host's 'players edit their own roles' switch "
            "is on. Re-orders the caller's own roles (null = every role they have a rank for) and "
            "flips their flex flag; participation and ranks stay the host's. The shown balance is "
            "not recomputed -- the change applies to the next one. 409 when the switch is off, 404 "
            "when the caller has no seat."
        ),
    },
    "rpc.balancer.custom.self_away": {
        "summary": "Step away from my mix",
        "description": (
            "Permission: a seated account; the account links are required as for a role edit, the host's 'players "
            "edit their own roles' switch is not. Sets or clears the caller's own away flag: an away player keeps "
            "their row, roles and must-play mark, but no balance, lobby split or rotation seats them until they are "
            "back, and every match recorded meanwhile counts them as busy (neither played nor sat out). It never "
            "clears itself. It reaches the lobby's running draft as the host's away flag does. 404 when the caller "
            "has no seat, 409 once the mix is over."
        ),
    },
    "rpc.balancer.custom.set_self_service": {
        "summary": "Set custom game self-service switches",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Sets whether players may seat themselves (closed, into the pool, or onto the bench) and "
            "whether a seated player may re-order their own roles, then returns the refreshed mix."
        ),
    },
    "rpc.balancer.custom.set_ban_preset": {
        "summary": "Set custom game ban preset",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Sets the hero ban preset the lobbies' next Start opens a room on -- a hero preset of the mix's own "
            "game that bans no player on map 1 (deadlock_hero_bans, deadlock_bans_pick, deadlock_bans_pick_turns, "
            "deadlock_two_phase_draft, lol_side_selection, lol_draft, lol_captains, the Overwatch hero presets) -- or "
            "null for no bans, and returns the refreshed mix. A live match keeps the room it started with. 422 "
            "unknown_ban_preset for any other code."
            " hero_fearless, when sent, turns Fearless on or off for the next room: a player cannot pick a hero they"
            " were recorded on earlier in the mix."
            " hero_ban_seconds / hero_pick_seconds, when sent, set the next room's clock in seconds (10..600; null ="
            " the preset's own) for every ban and protect step / every pick step -- an all-at-once pick is one step,"
            " so its clock is the whole pick's; a side pick or an assignment keeps the preset's clock."
        ),
    },
    "rpc.balancer.custom.set_draft_settings": {
        "summary": "Set custom game team formation",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Sets how the mix's lobbies form teams by default -- 'balance' (the solver) or 'draft' (a captain "
            "draft) -- and the draft's pick clock in seconds (10..600), then returns the refreshed mix. A running "
            "draft keeps its clock; both apply from the next formation. 422 for any other value."
        ),
    },
    "rpc.balancer.custom.draft_seed": {
        "summary": "Draft a custom game lobby",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). Re-forms one "
            "lobby (`lobby_index`) as a captain draft: its seated set -- present, non-benched players, must-play "
            "first, then rotation order, minus whoever another lobby plays; exactly whom a balance of the lobby "
            "would seat -- with the two strongest as captains, the weaker picking first, snake order on the mix's "
            "pick clock. The lobby's lineup is cleared and its running draft cancelled; it reads `draft_setup` "
            "until a host starts the draft (`POST /api/v1/balancer/draft/sessions/{session_id}/start`). The last "
            "pick writes the lobby's lineup; a finished mix draft is never paused or rolled back (409 "
            "mix_draft_completed: re-form instead). 409 match_live; 422 empty_lineup, missing_ranked_role or a split "
            "code."
        ),
    },
    "rpc.balancer.custom.draft_split": {
        "summary": "Split custom game pool into lobby drafts",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). Splits the "
            "seated set over every lobby by strength and seeds one captain draft per lobby, forming no team. Every "
            "running draft is cancelled and every lineup cleared. 422 single_lobby or a split code "
            "(not_enough_players, too_many_must_play, too_many_pinned, roles_infeasible); 409 match_live."
        ),
    },
    "rpc.balancer.custom.draft_captain": {
        "summary": "Replace a custom game draft captain",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). Before the "
            "draft starts, any present pool player (`player_id`, a draft player id) captains `team_id` and the "
            "draft re-seeds with the weaker captain picking first, leaving out whoever stepped away; during it, a "
            "player already on that team takes over its picks and its crown, and the picks made stand. 404 "
            "draft_not_found; 409 already_captain or not_in_pool; 422 captain_not_on_team."
        ),
    },
    "rpc.balancer.custom.draft_add_player": {
        "summary": "Add a waiting player to a custom game draft",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). Adds a present "
            "player no lobby seats to the lobby's draft as an available pick -- before the start too -- the way out "
            "of a draft short of a role. 404 not_on_roster or draft_not_found; 409 player_away or already_seated."
        ),
    },
    "rpc.balancer.custom.balance": {
        "summary": "Balance custom game",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            'With `scope="lobby"` (the default) balances the non-benched lineup of ONE lobby '
            "(`lobby_index`, default 0) -- everyone another lobby is already playing or holds a pin "
            'on is left out. With `scope="all"` it splits the whole pool into `lobby_count` equally '
            "strong lobbies and balances them all. Ranks come from the host's own book above the "
            "workspace canon. 422 when the lineup is empty, a seated player has no ranked role, the "
            "mix has one lobby (`single_lobby`) or the pool cannot be split (`not_enough_players`, "
            "`too_many_must_play`, `too_many_pinned`, `roles_infeasible`)."
            " 409 match_live when the lobby -- for scope all, any lobby -- has a live match."
            " An away player is never a candidate. A balanced lobby's running draft is cancelled."
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
            "Names the map the lobby's next match is played on -- rolled or picked by a host ahead of "
            "the lobby -- or clears it with null. The next recorded match takes this map unless the "
            "outcome names one explicitly, and clears it either way. The lobby_index field names which "
            "lobby's roll this is; a single-lobby mix leaves it at 0. 404 when "
            "the map is not in the catalogue."
            " 409 match_live while the lobby's match is live."
        ),
    },
    "rpc.balancer.custom.set_variant_index": {
        "summary": "Set custom game shown balance option",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Pages one lobby to one of the balance options its last run produced, for every viewer at "
            "once -- the option on screen is a fact about the lobby, not about one browser. "
            "404 when the index points past the stored options, and 409 seat_conflict when the option "
            "would seat somebody another of the mix's lobbies has already put on the floor. Re-balancing "
            "resets it to the first option."
            " 409 match_live while the lobby's match is live."
        ),
    },
    "rpc.balancer.custom.post_discord": {
        "summary": "Post custom game lineup to Discord",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Queues the lobby's lineup post -- the balance option the lobby is showing, the next map "
            "and the points at stake -- to the workspace-wide mix channel and returns immediately: "
            "discord-service renders the card, keeps it in step with the board and delivers it, and "
            "nothing about the mix changes. A multi-lobby mix names the lobby on the card and "
            "numbers the match within that lobby. 409 when the workspace has "
            "no mix channel configured and 404 when the balance option is missing."
        ),
    },
    "rpc.balancer.custom.post_signup": {
        "summary": "Open custom game signup in Discord",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Opens self-signup in the given mode (into the pool or onto the bench) and queues the "
            "signup card with Join / My roles / Leave buttons to the workspace-wide mix channel. "
            "discord-service renders it and keeps it in step with the roster; every click re-reads "
            "the mix, so it refuses correctly once signup closes or the mix ends. A mix has one "
            "signup card: posting again deletes the previous one from the channel first. 409 when "
            "the workspace has no mix channel configured."
        ),
    },
    "rpc.balancer.custom.delete_discord_post": {
        "summary": "Delete one custom game Discord post",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Asks the bot to delete one message this mix posted, named by its id from the mix's "
            "`discord_posts`, and returns the refreshed mix. 404 when the id belongs to another "
            "mix's message. Clicking twice is harmless; closing or cancelling a mix deletes nothing, "
            "its posts stay as history."
        ),
    },
    "rpc.balancer.custom.voice_options": {
        "summary": "List custom game voice channels",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Returns the voice channels of the workspace's mix voice category, split into `general` "
            "and `team` voices, each with the bot's `missing_permissions`. `error` is set instead of "
            "failing when Discord is unreachable or the category is gone (`category_not_found`); with "
            "no category configured both lists are empty."
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
            "returns the refreshed mix; a swap that moves a team's captain re-captains both teams. "
            "404 when the option or either seat is missing, 422 when the seats hold different roles or sit on the "
            "same team."
            " 409 match_live while the lobby's match is live."
        ),
    },
    "rpc.balancer.custom.set_captain": {
        "summary": "Make custom game captain",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Makes one seated player the captain of their team in the option the lobby is showing and returns the "
            "refreshed mix. A balance captains each team by its strongest seat; a swap that moves a captain "
            "re-captains both teams. 404 when that option does not seat the player."
            " 409 match_live while the lobby's match is live."
        ),
    },
    "rpc.balancer.custom.start_match": {
        "summary": "Start custom game match",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Starts the lobby's match on the option it is showing: an open encounter with both teams' rosters "
            "(captains flagged) and one game on the lobby's next map. The lineup is then frozen until the result is "
            "recorded or the match is cancelled. When the lobby has both team voices, its seated players are then "
            "moved into them (as voice_move; a Discord failure leaves the match started). 409 match_live when the lobby "
            "already has a live match, 404 when the shown option is gone, 422 unless it seats two teams."
            " Both seats are marked ready. With a hero ban preset the team that bans first (the last round's loser when"
            " the same two teams meet again, else the lower average rating; flip_opener swaps it) is seated in slot 1"
            " and tournament-service opens the ban room; the lobby reads pregame until the room is done."
        ),
    },
    "rpc.balancer.custom.cancel_match": {
        "summary": "Cancel custom game match",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Throws the lobby's live match away: its encounter is deleted with its game and rosters, nothing is "
            "recorded and no rank, pin or map moves; the lineup is ready to start again. 409 no_live_match when "
            "nothing was started."
        ),
    },
    "rpc.balancer.custom.record_outcome": {
        "summary": "Record custom game match",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Records the result of the lobby's live match -- the one Start match opened on the lineup it froze -- and "
            "completes its encounter, moving both teams' ranks in the host's book (by points_per_win when a winner is "
            "given, or seat by seat by the mix ranker when the host's rating_mode is 'ranker'), advancing the "
            "workspace's hidden ratings and redeeming every seat's must_play pin back to the pool. The match is "
            "stamped with its lobby and with whoever was playing another lobby at that moment, whom rotation then "
            "counts as neither played nor sat out. The lobby's next map is cleared. 409 no_live_match when nothing was "
            "started. Repeatable until the mix is closed. The winner names the lineup team (1 or 2), whichever slot "
            "Start seated it in."
        ),
    },
    "rpc.balancer.custom.match_history": {
        "summary": "List custom game matches",
        "description": (
            "Permission: public; no authentication required. Returns every round recorded for the mix, newest first: "
            "its two teams by slot (slot 1 banned first) with name and score, its hero bans {slot, item_id} in order, "
            "whose hero each pick was {slot, member_id, name, item_id} in pick order, "
            "the winning slot (null for a draw), lobby, map, recorder and the rank points it applied."
        ),
    },
    "rpc.balancer.custom.undo_match": {
        "summary": "Undo custom game match",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Deletes the lobby's most recent match and gives back exactly the rank points it applied, "
            "read from the match and its seats rather than the host's current settings, then rebuilds "
            "the workspace's hidden ratings from the remaining history. "
            "404 when the match belongs to another mix and 409 when a newer match of the SAME lobby "
            "exists, since the rank book compounds. must_play pins the recording redeemed are not "
            "restored."
        ),
    },
    "rpc.balancer.custom.rotation": {
        "summary": "Get custom game rotation hints",
        "description": (
            "Permission: public; no authentication required. Recommends who is owed the next seat and "
            "who should sit out, computed from this mix's own match history, read-only. The optional "
            "lobby_index query parameter ranks the candidates of one lobby -- whoever is seated in "
            "another lobby or pinned to one is left out -- and splits at that lobby's seat count."
        ),
    },
    "rpc.balancer.custom.stats": {
        "summary": "Get custom game statistics",
        "description": (
            "Permission: public; no authentication required. "
            "Per-member wins/losses/draws, win rate, current streak and the per-role split across "
            "the mixes this workspace has run, best record first. The optional `discipline` query parameter narrows "
            "it to one enabled game (422 `discipline_not_enabled` for another): seats, roles and `identity` (the "
            "member's handle for that game's identity provider) are that game's. Without it (or `all`) the "
            "scoreboard spans every game, `identity` is the member's first handle in any game's provider, and "
            "`by_role` is null -- role codes of different games are different roles. The optional since query "
            "parameter (ISO 8601) narrows it to matches played (started) on or after that moment; without it the "
            "whole history counts. Each member also carries `player_id` (the global player, null once the member is "
            "no longer on the roster) and `form`: their newest results first (in the order they were recorded), at "
            "most 10, each `{outcome, match_id, played_at, recorded_at}`. Top-level `mixes` and `matches` count the "
            "distinct mixes and recorded matches inside the same window. Read-only."
        ),
    },
    "rpc.balancer.custom.close": {
        "summary": "Close custom game",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Cancels every live match and every running draft, then marks the mix completed so no further writes "
            "land. Nothing is destroyed -- the mix and every match it recorded stay readable -- so this is the "
            "reversible end of a mix."
        ),
    },
    "rpc.balancer.custom.set_lobby_count": {
        "summary": "Set custom game lobby count",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Runs the mix as 1..6 lobbies. Growing opens the new lobbies empty, leaving the running "
            "ones untouched; shrinking deletes every lobby past the new count together with its "
            "stored matchup and clears the pins that named them. Matches already recorded for a "
            "deleted lobby stay in the history and in the statistics."
            " 409 match_live when a lobby it would drop has a live match."
        ),
    },
    "rpc.balancer.custom.rename": {
        "summary": "Rename custom game",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Replaces the mix's name (trimmed, 1-255 characters) and re-renders its live Discord "
            "signup card. Refused once the mix is closed."
        ),
    },
    "rpc.balancer.custom.hard_delete": {
        "summary": "Delete custom game",
        "description": (
            "Permission: workspace membership plus the workspace `admin` or `owner` role (superuser "
            "counts). Permanently erases the mix together with its roster, every match it "
            "recorded and every Discord message it posted, and returns the deleted id. "
            "Irreversible, and unlike close it is not open to the mix's own host and co-hosts."
        ),
    },
    "rpc.balancer.players.list": {
        "summary": "List workspace players",
        "description": (
            "Permission: workspace membership (any role); no resource grant is checked. "
            "Returns a page of the workspace roster carrying two rank dictionaries that are never "
            "merged: `ranks` is the workspace canon and `author_ranks` is one author's own book, "
            "which is what lets a row say whether a number is its own or inherited. Another "
            "organiser's book is readable through `author_user_id`. "
            "Optional `discipline` (query on reads, body on writes) picks whose rated roles the ranks "
            "are held on and whose identity provider names each row's `identity`; omitted, the workspace's "
            "first enabled discipline (422 `discipline_not_enabled` for another). Observation-only anchors "
            "are not roster members and never listed."
        ),
    },
    "rpc.balancer.players.summary": {
        "summary": "Get workspace roster summary",
        "description": 'Permission: workspace membership (any role); no resource grant is checked. Returns the workspace roster size alongside how many of those members the read author has personally ranked, which is what the "My ranks" filter counts.',
    },
    "rpc.balancer.players.upsert": {
        "summary": "Upsert workspace player",
        "description": (
            "Permission: workspace member holding team.create or custom_game.create (a mix host); setting "
            "display_name requires team.create. Admits (or reuses) the workspace member a game identity "
            "denotes and returns it shaped exactly like a roster row. The body is "
            "`{discipline, identity: {provider, handle}, display_name?}`; `discipline` must be enabled for the "
            "workspace (422 `discipline_not_enabled`), `identity.provider` must be that discipline's identity "
            "provider (422 `identity.provider_mismatch`) and the handle must fit its grammar (422 with the "
            "provider's format code, e.g. `identity.riot.format`). Several distinct players carrying the handle "
            "is 409 `identity_conflict`; no player yet creates an unlinked one. Unknown keys (such as "
            "`battle_tag`) are 422."
        ),
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
            "workspace. The body's `discipline` is required (422 when omitted) and picks whose rated roles "
            "the ranks are held on; it must be enabled for the workspace (422 `discipline_not_enabled`). "
            "A role code outside that discipline's rated module roles -- `flex` included -- is 422 `unknown_role`."
        ),
    },
    "rpc.balancer.players.authors": {
        "summary": "List rank authors",
        "description": "Permission: workspace membership (any role); no resource grant is checked. Returns everyone who has personally rank-corrected a member in this workspace, busiest first, with their display name and correction count.",
    },
    "rpc.balancer.ranks.list": {
        "summary": "List all rank values in the workspace",
        "description": (
            "Permission: workspace member holding `team.update` -- the same grant writing the canon "
            "needs, because this read puts every author's private book on one screen. Read-only. "
            "One flat row per rank value across nine layers (canon, author, native, hidden, "
            "effective_tournament, effective_mix, registration, tournament, casual); the six current "
            "layers are the default. The two effective layers are computed in SQL and agree with the "
            "resolver the balancer runs on: effective_tournament is canon over the game's native rank on the "
            "workspace grid, effective_mix is the author's book over the canon over the native rank on the same "
            "workspace grid. "
            "`division` is resolved on the workspace's effective grid of the row's game. Filtering, "
            "sorting, the exact total and the page all run in the database. "
            "Optional `discipline` reads one enabled game (422 `discipline_not_enabled` for another); without it "
            "the rows are the union over every game the workspace runs, each tagged with its `discipline`, and "
            "`role`, `div_min`, `div_max` and `sort=rank_value|division` are a 422 (`<param> requires "
            "discipline`): those values live on different grids. A game with no grid here lists its rows with a "
            "null `division`, and a `div_min`/`div_max` on it is a 422 `division_grid_required`."
        ),
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
            "the per-role weights, the open-slot weight, how many balance options to keep, how far a "
            "decided match moves its rank book and whether the mix ranker moves it instead "
            "(rating_mode). A null value means the setting was never saved and the default applies. "
            "The team format is not here: it is frozen on each mix."
            " hero_ban_presets maps a game to the hero ban preset a new mix of it starts with."
            " formation_defaults maps a game to how a new mix of it forms teams (team_formation, draft_pick_seconds)."
        ),
    },
    "rpc.balancer.prefs.upsert": {
        "summary": "Set my pickup mix preferences",
        "description": (
            "Permission: self-service -- any authenticated (active) account writes its own "
            "preferences only. "
            "Replaces all eight of the caller's mix settings at once and returns the stored result, "
            "exactly what the next read returns; a null clears one back to the default, and 0 points "
            "per win stores as unset. They apply to every mix this account hosts -- a mix runs on "
            "its host's preferences whoever presses the button. 422 on an unknown field or an "
            "out-of-range value."
            " 422 when a hero_ban_presets entry is not a hero preset of its own game."
            " 422 when formation_defaults names a game that is not installed or a pick clock outside 10..600."
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
