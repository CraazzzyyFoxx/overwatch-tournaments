package tournament

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// RegistrationAdminRoutes are the bespoke admin registration + registration-status
// endpoints served by typed RPC methods in src/rpc/registration_admin.py. Each
// requires an authenticated user; the worker enforces the same per-resource
// workspace permission the original FastAPI dependency did.
//
// Mirrors src/routes/admin/registration.py (router prefix /balancer) and
// src/routes/admin/registration_status.py (router prefix /ws/{workspace_id}/
// balancer-statuses). The admin_router prefix is /admin and the app root_path is
// /api/v1, so the full external paths are /api/v1/admin/<prefix><route>.
//
// IDParam copies the path param to data["id"] (the worker reads it via _require_id).
// Path copies the named path params verbatim into the body (worker reads them by
// name): the status routes are workspace-scoped (workspace_id/status_id/scope/slug)
// and the rank-history route needs user_id + a workspace_id query param. The list
// endpoint forwards all query params (status/inclusion/source filters + include_deleted).
var RegistrationAdminRoutes = []edge.RouteSpec{
	// ── registration.py (/balancer) ──────────────────────────────────────
	// registration-form get/upsert (keyed by tournament_id).
	{Method: "GET", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/registration-form", Queue: "rpc.tournament.reg_form_get", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/registration-form", Queue: "rpc.tournament.reg_form_upsert", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	// list registrations (status/inclusion/source filters + include_deleted) -> AllQuery.
	{Method: "GET", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/registrations", Queue: "rpc.tournament.reg_list", IDParam: "tournament_id", AllQuery: true, Auth: edge.AuthRequired},
	// create manual registration (201).
	{Method: "POST", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/registrations", Queue: "rpc.tournament.reg_create_manual", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired, Success: 201},
	// per-registration mutations (keyed by registration_id).
	{Method: "PATCH", Pattern: "/api/v1/admin/balancer/registrations/{registration_id}", Queue: "rpc.tournament.reg_update", IDParam: "registration_id", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/balancer/registrations/{registration_id}/approve", Queue: "rpc.tournament.reg_approve", IDParam: "registration_id", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/balancer/registrations/{registration_id}/reject", Queue: "rpc.tournament.reg_reject", IDParam: "registration_id", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/balancer/registrations/{registration_id}/exclusion", Queue: "rpc.tournament.reg_exclusion", IDParam: "registration_id", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/balancer/registrations/{registration_id}/withdraw", Queue: "rpc.tournament.reg_withdraw", IDParam: "registration_id", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/balancer/registrations/{registration_id}/restore", Queue: "rpc.tournament.reg_restore", IDParam: "registration_id", Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/admin/balancer/registrations/{registration_id}", Queue: "rpc.tournament.reg_delete", IDParam: "registration_id", Auth: edge.AuthRequired, Success: 204},
	// bulk + balancer-status mutations.
	{Method: "POST", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/registrations/bulk-approve", Queue: "rpc.tournament.reg_bulk_approve", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/balancer/registrations/{registration_id}/balancer-status", Queue: "rpc.tournament.reg_set_balancer_status", IDParam: "registration_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/registrations/bulk-add-to-balancer", Queue: "rpc.tournament.reg_bulk_add_balancer", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	// rank-autofill preview/apply.
	{Method: "POST", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/registrations/rank-autofill/preview", Queue: "rpc.tournament.reg_rank_autofill_preview", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/registrations/rank-autofill/apply", Queue: "rpc.tournament.reg_rank_autofill_apply", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	// per-user rank history (path user_id + query workspace_id).
	{Method: "GET", Pattern: "/api/v1/admin/balancer/users/{user_id}/registration-rank-history", Queue: "rpc.tournament.reg_user_rank_history", Path: []string{"user_id"}, Query: []string{"workspace_id"}, Auth: edge.AuthRequired},
	// export approved registrations into users.
	{Method: "POST", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/registrations/export-users", Queue: "rpc.tournament.reg_export_users", IDParam: "tournament_id", Auth: edge.AuthRequired},
	// check-in toggle.
	{Method: "PATCH", Pattern: "/api/v1/admin/balancer/registrations/{registration_id}/check-in", Queue: "rpc.tournament.reg_check_in", IDParam: "registration_id", Body: true, Auth: edge.AuthRequired},

	// ── registration_status.py (/ws/{workspace_id}/balancer-statuses) ─────
	// All routes are workspace-scoped via the path workspace_id (copied verbatim).
	{Method: "GET", Pattern: "/api/v1/admin/ws/{workspace_id}/balancer-statuses/catalog", Queue: "rpc.tournament.regstatus_catalog", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/ws/{workspace_id}/balancer-statuses", Queue: "rpc.tournament.regstatus_list", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/ws/{workspace_id}/balancer-statuses/custom", Queue: "rpc.tournament.regstatus_create", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "PATCH", Pattern: "/api/v1/admin/ws/{workspace_id}/balancer-statuses/custom/{status_id}", Queue: "rpc.tournament.regstatus_update", Path: []string{"workspace_id", "status_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/admin/ws/{workspace_id}/balancer-statuses/custom/{status_id}", Queue: "rpc.tournament.regstatus_delete", Path: []string{"workspace_id", "status_id"}, Auth: edge.AuthRequired, Success: 204},
	{Method: "PUT", Pattern: "/api/v1/admin/ws/{workspace_id}/balancer-statuses/system/{scope}/{slug}", Queue: "rpc.tournament.regstatus_builtin_upsert", Path: []string{"workspace_id", "scope", "slug"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/admin/ws/{workspace_id}/balancer-statuses/system/{scope}/{slug}", Queue: "rpc.tournament.regstatus_builtin_reset", Path: []string{"workspace_id", "scope", "slug"}, Auth: edge.AuthRequired, Success: 204},
}
