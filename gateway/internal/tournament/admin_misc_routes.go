package tournament

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// AdminMiscRoutes are the bespoke (non-CRUD) admin endpoints served by typed RPC
// methods in src/rpc/admin_misc.py. Each requires an authenticated user; the
// worker enforces the same per-resource workspace permission (and superuser gates
// for finish / forced status transitions) the original FastAPI dependency did.
//
// Mirrors src/routes/admin/{encounter,tournament,standing,computation}.py. The
// admin_router prefix is /admin; sub-routers add /encounters, /tournaments,
// /standings, /tournament-jobs.
var AdminMiscRoutes = []edge.RouteSpec{
	{Method: "PATCH", Pattern: "/api/v1/admin/encounters/matches/{match_id}", Queue: "rpc.tournament.encounter_update_match", IDParam: "match_id", Body: true, Auth: edge.AuthRequired},
	// The single admin result write: score + status + result_status + audit row
	// move together, so a dispute can never be left half-resolved. reopen is the
	// only way out of a dispute an admin does not want to force-confirm.
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/result", Queue: "rpc.tournament.encounter_set_result", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/result/reopen", Queue: "rpc.tournament.encounter_reopen_result", IDParam: "encounter_id", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/encounters/{encounter_id}/result-audit", Queue: "rpc.tournament.encounter_result_audit", IDParam: "encounter_id", Auth: edge.AuthRequired},
	// Bracket drag-and-drop: exchange the teams two slots hold (same encounter +
	// other slot = a home/away flip). Seeding only — the worker refuses a settled
	// or live encounter.
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/swap-slot", Queue: "rpc.tournament.encounter_swap_slot", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	// captain reports — cross-tournament, workspace-scoped (?workspace_id=). Both
	// carry the same filter set, so both take AllQuery. The /stats literal is
	// listed first: this table is scanned in order and a later bare-collection
	// pattern must never shadow a more specific literal under it.
	{Method: "GET", Pattern: "/api/v1/admin/encounter-reports/stats", Queue: "rpc.tournament.admin_encounter_reports_stats", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/encounter-reports", Queue: "rpc.tournament.admin_encounter_reports_list", AllQuery: true, Auth: edge.AuthRequired},
	// parsed matches — one row per played map, workspace-scoped (?workspace_id=).
	// The literal collection is registered before the {match_id} pattern so a
	// bare /matches can never be swallowed as an id.
	{Method: "GET", Pattern: "/api/v1/admin/matches", Queue: "rpc.tournament.admin_matches_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/matches/{match_id}", Queue: "rpc.tournament.admin_match_get", IDParam: "match_id", AllQuery: true, Auth: edge.AuthRequired},
	// pick-ban live-session admin overrides (docs/plans/2026-08-09-generic-pickban-engine.md).
	// Config CRUD moved to the generic pick-ban-configs routes below. `kind`
	// (map|hero) travels in the body, one route pair for both. Worker enforces
	// workspace "match"/"result" — these run ONE match in progress, the same
	// staff that records its result.
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/pick-ban-session/reset", Queue: "rpc.tournament.admin_pick_ban_session_reset", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/pick-ban-act", Queue: "rpc.tournament.admin_pick_ban_act", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/pick-ban-elect-opener", Queue: "rpc.tournament.admin_pick_ban_elect_opener", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	// Ruleset v2 (docs/plans/2026-09-28-pick-ban-constructor.md §8): submit a
	// BLIND step's draft for an absent captain, and reopen the last revealed
	// step (the organizer's dispute, without the attempt budget).
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/pick-ban-submit", Queue: "rpc.tournament.admin_pick_ban_submit", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/pick-ban-reopen", Queue: "rpc.tournament.admin_pick_ban_reopen", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	// The room's emergency controls: freeze its clock, hand the open step more
	// time, drop a session the series cannot play out, and record a walkover.
	// A paused session refuses every CAPTAIN write (409) while these same admin
	// routes keep working — that is the point of the pause.
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/pick-ban-pause", Queue: "rpc.tournament.admin_pick_ban_pause", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/pick-ban-extend", Queue: "rpc.tournament.admin_pick_ban_extend", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/pick-ban-cancel", Queue: "rpc.tournament.admin_pick_ban_cancel", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	// A technical loss IS a result write (same `match.result` gate, same bracket
	// and source-correction guards as /result), so it answers the result shape.
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/technical-loss", Queue: "rpc.tournament.admin_encounter_technical_loss", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	// Captain readiness, forced by an organizer: `{side, ready}`. Worker enforces
	// the same "match"/"result" gate; `ready: false` is a 409 once a pick-ban
	// session exists (readiness gates session creation only — reset instead).
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/readiness", Queue: "rpc.tournament.admin_encounter_readiness_set", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	// encounter_game correction — one series position's result, admin-decided and
	// always reasoned (spec §6.5). Same worker-side "match"/"result" gate.
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/games/{game_id}/result", Queue: "rpc.tournament.admin_game_result", IDParam: "encounter_id", Path: []string{"game_id"}, Body: true, Auth: edge.AuthRequired},
	// FFA lobby results (src/rpc/ffa.py) — one game of a lobby is identified by
	// its POSITION, like the duel game correction above: a lobby may replay a
	// cancelled position, and only the position tells the two plays apart. The
	// games count is the lobby's own best_of. Same worker-side
	// "match"/"update" gate as every other result write.
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/ffa/games/{position}/results", Queue: "rpc.tournament.ffa_game_results_set", IDParam: "encounter_id", Path: []string{"position"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/ffa/games/{position}/cancel", Queue: "rpc.tournament.ffa_game_cancel", IDParam: "encounter_id", Path: []string{"position"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/ffa/games-count", Queue: "rpc.tournament.ffa_games_count_set", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	// The organizer's view of the same lobby tables the public route answers,
	// with the columns marked non-public still on them — that is what the entry
	// dialog fills in. NOT listed in cacheable.go: the values behind a hidden
	// column must not sit in a shared response cache.
	{Method: "GET", Pattern: "/api/v1/admin/tournaments/{id}/stages/{stage_id}/ffa", Queue: "rpc.tournament.ffa_stage_admin", IDParam: "id", Path: []string{"stage_id"}, Auth: edge.AuthRequired},
	// generic pick-ban config CRUD (map + hero, docs/plans/2026-08-09-generic-pickban-engine.md).
	// Same cascade key as the veto-configs routes above, additionally partitioned
	// by `kind` in the body/response.
	{Method: "GET", Pattern: "/api/v1/admin/tournaments/{tournament_id}/pick-ban-configs", Queue: "rpc.tournament.admin_pick_ban_config_list", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/v1/admin/tournaments/{tournament_id}/pick-ban-configs", Queue: "rpc.tournament.admin_pick_ban_config_upsert", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/admin/pick-ban-configs/{config_id}", Queue: "rpc.tournament.admin_pick_ban_config_delete", IDParam: "config_id", Auth: edge.AuthRequired},
	// The tournament-wide pre-game rooms board: one row per encounter whose room
	// can exist, with its phase and attention flags. Read-only (the worker never
	// creates a session for it) and gated on workspace "match"/"read". NOT in
	// cacheable.go: it is a live operations view, stale by the second.
	{Method: "GET", Pattern: "/api/v1/admin/tournaments/{tournament_id}/pregame-rooms", Queue: "rpc.tournament.admin_pregame_rooms", IDParam: "tournament_id", Auth: edge.AuthRequired},
	// One room's journal: the pre-game events merged with the encounter's result
	// audit, newest first. Same "match"/"read" gate as the board above, and the
	// same reason to stay out of cacheable.go — it is read while the room runs.
	{Method: "GET", Pattern: "/api/v1/admin/encounters/{encounter_id}/room-history", Queue: "rpc.tournament.admin_pregame_room_history", IDParam: "encounter_id", Query: []string{"limit"}, Auth: edge.AuthRequired},
	// The constructor's two read-only engine probes: "would this ruleset save?"
	// and "what would a Bo5 of it look like?". Keyed by tournament_id because
	// they gate on the same workspace "match"/"update" as the upsert they
	// precede, not because they read the tournament.
	{Method: "POST", Pattern: "/api/v1/admin/tournaments/{tournament_id}/pick-ban-rules/validate", Queue: "rpc.tournament.admin_pick_ban_rules_validate", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/tournaments/{tournament_id}/pick-ban-rules/preview", Queue: "rpc.tournament.admin_pick_ban_rules_preview", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	// match report form (docs/plans/2026-08-04-configurable-match-report-form.md) —
	// the per-tournament captain-report field config. Worker enforces workspace
	// "match"/"read" for the get and "match"/"update" for the upsert.
	{Method: "GET", Pattern: "/api/v1/admin/tournaments/{tournament_id}/report-form", Queue: "rpc.tournament.report_form_get", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/v1/admin/tournaments/{tournament_id}/report-form", Queue: "rpc.tournament.report_form_upsert", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	// tournament.py — finish (legacy toggle), status transition, and phase schedule replace.
	{Method: "POST", Pattern: "/api/v1/admin/tournaments/{tournament_id}/finish", Queue: "rpc.tournament.tournament_finish", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/tournaments/{tournament_id}/status", Queue: "rpc.tournament.tournament_status", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/v1/admin/tournaments/{tournament_id}/schedule", Queue: "rpc.tournament.tournament_schedule_set", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	// standing.py — recalculate schedules a durable job (202 Accepted).
	{Method: "POST", Pattern: "/api/v1/admin/standings/recalculate/{tournament_id}", Queue: "rpc.tournament.standing_recalculate", IDParam: "tournament_id", Auth: edge.AuthRequired, Success: 202},
	// computation.py — read-only job get/list.
	{Method: "GET", Pattern: "/api/v1/admin/tournament-jobs/{job_id}", Queue: "rpc.tournament.job_get", IDParam: "job_id", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/tournament-jobs", Queue: "rpc.tournament.job_list", Query: []string{"tournament_id", "stage_id", "active_only", "limit"}, Auth: edge.AuthRequired},
	// preview access allowlist (hidden tournaments) — workspace-admin gated in the worker.
	{Method: "GET", Pattern: "/api/v1/admin/tournaments/{tournament_id}/preview-access", Queue: "rpc.tournament.preview_access_list", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/tournaments/{tournament_id}/preview-access", Queue: "rpc.tournament.preview_access_add", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "DELETE", Pattern: "/api/v1/admin/tournaments/{tournament_id}/preview-access/{auth_user_id}", Queue: "rpc.tournament.preview_access_remove", IDParam: "tournament_id", Path: []string{"auth_user_id"}, Auth: edge.AuthRequired, Success: 204},
}
