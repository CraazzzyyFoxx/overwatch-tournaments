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
        "description": "Creates or updates the per-tournament balancer config (requires workspace team-import) and emits a balancer config-changed realtime event.",
    },
    "rpc.balancer.admin.balance_get": {
        "summary": "Get saved balance",
        "description": "Returns the saved team balance for a tournament for admins with workspace team-read permission, or null when none exists.",
    },
    "rpc.balancer.admin.balance_save": {
        "summary": "Save tournament balance",
        "description": "Persists a computed team balance for the tournament (requires workspace team-import) and emits a balance-saved realtime event.",
    },
    "rpc.balancer.admin.balance_export": {
        "summary": "Export balance to teams",
        "description": "Materializes a saved balance into tournament teams, returning removed/imported counts and emitting a teams-changed realtime event.",
    },
    "rpc.balancer.admin.workspace_config_get": {
        "summary": "Get workspace balancer config",
        "description": "Returns the workspace-level balancer config (rank-delta threshold and pool-hide flag) for members with workspace read permission.",
    },
    "rpc.balancer.admin.workspace_config_upsert": {
        "summary": "Upsert workspace balancer config",
        "description": "Creates or updates the workspace-level rank-delta threshold and hide-from-pool settings, requiring workspace admin permission.",
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
    "rpc.balancer.draft.session_create": {
        "summary": "Create draft session",
        "description": "Creates a new draft session for a tournament (requires workspace team-import) and publishes a session-updated realtime event.",
    },
    "rpc.balancer.draft.seed": {
        "summary": "Seed draft session",
        "description": "Seeds a draft session with captains and players from the balancer pool or a manual list (requires team-import); 422 if neither is provided.",
    },
    "rpc.balancer.draft.session_patch": {
        "summary": "Patch draft session",
        "description": "Updates mutable draft settings (pick time, autopick strategy, override flag, rounds, settings) before the draft starts, requiring team-import.",
    },
    "rpc.balancer.draft.start": {
        "summary": "Start draft session",
        "description": "Starts the draft and opens the first pick (requires team-import), publishing a pick-started realtime event with the clock deadline.",
    },
    "rpc.balancer.draft.pause": {
        "summary": "Pause draft session",
        "description": "Pauses an in-progress draft (requires team-import) and publishes a draft-paused realtime event.",
    },
    "rpc.balancer.draft.resume": {
        "summary": "Resume draft session",
        "description": "Resumes a paused draft (requires team-import) and publishes a draft-resumed realtime event.",
    },
    "rpc.balancer.draft.cancel": {
        "summary": "Cancel draft session",
        "description": "Cancels the draft (requires team-import) and publishes a draft-cancelled realtime event.",
    },
    "rpc.balancer.draft.rollback": {
        "summary": "Rollback draft pick",
        "description": "Rolls back the most recent draft action (requires team-import) and publishes a rollback realtime event.",
    },
    "rpc.balancer.draft.export": {
        "summary": "Export draft to teams",
        "description": "Finalizes the drafted rosters into tournament teams (requires team-import) and publishes a draft-completed realtime event.",
    },
    "rpc.balancer.draft.pick_select": {
        "summary": "Select draft pick",
        "description": "Makes a pick for the current slot as the on-clock captain (or admin), enforcing role fit and optimistic version, then broadcasts pick-made/next-pick events.",
    },
    "rpc.balancer.draft.pick_autopick": {
        "summary": "Autopick draft pick",
        "description": "Auto-selects the best-fit available player for a pick using the session's autopick strategy (requires team-import) and broadcasts the result.",
    },
    "rpc.balancer.draft.pick_override": {
        "summary": "Override draft pick",
        "description": "Admin-overrides a pick to an arbitrary player (requires team-import), bypassing captain/clock constraints, and broadcasts a pick-made event.",
    },
}
