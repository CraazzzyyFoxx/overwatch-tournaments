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
	// encounter.py — bulk takes encounter_ids from the body (no path id).
	{Method: "PATCH", Pattern: "/api/v1/admin/encounters/bulk", Queue: "rpc.tournament.encounter_bulk_update", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/encounters/matches/{match_id}", Queue: "rpc.tournament.encounter_update_match", IDParam: "match_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/confirm-result", Queue: "rpc.tournament.encounter_confirm_result", IDParam: "encounter_id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/map-pool", Queue: "rpc.tournament.encounter_assign_map_pool", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	// map veto (docs/plans/map-veto-redesign.md) — config CRUD keyed by tournament
	// (upsert key = tournament/stage/round in the body) plus per-encounter session
	// reset and admin-forced actions. Worker enforces workspace "match"/"update".
	{Method: "GET", Pattern: "/api/v1/admin/tournaments/{tournament_id}/veto-configs", Queue: "rpc.tournament.admin_veto_config_list", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/v1/admin/tournaments/{tournament_id}/veto-configs", Queue: "rpc.tournament.admin_veto_config_upsert", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/admin/veto-configs/{config_id}", Queue: "rpc.tournament.admin_veto_config_delete", IDParam: "config_id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/veto-session/reset", Queue: "rpc.tournament.admin_veto_session_reset", IDParam: "encounter_id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/veto-act", Queue: "rpc.tournament.admin_veto_act", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
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
