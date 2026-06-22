package tournament

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// IntegrationsRoutes are the bespoke integration endpoints ported to typed RPC:
// the Challonge admin sync, the registration Google-Sheets admin tooling, and the
// PUBLIC division-grid catalog. Each maps 1:1 to an rpc.tournament.* queue served
// by src/rpc/integrations.py, which re-runs the original route's permission check
// in the worker.
//
//   - Challonge (prefix /api/v1/admin/challonge): global challonge.read / per-
//     tournament|encounter challonge.sync permission, enforced in the worker.
//   - Sheets (prefix /api/v1/admin/balancer): per-tournament team.read /
//     team.import / player.read permission, enforced in the worker.
//   - Division grids (prefix /api/v1/division-grids): PUBLIC subtree, but every
//     route still requires an authenticated user (the HTTP service gated all of
//     them on get_current_active_user), so Auth is AuthRequired throughout; the
//     finer division_grid.<action> workspace permission is enforced in the worker.
var IntegrationsRoutes = []edge.RouteSpec{
	// ── Challonge (admin) ─────────────────────────────────────────────────
	{Method: "GET", Pattern: "/api/v1/admin/challonge/tournament", Queue: "rpc.tournament.challonge_fetch_tournament", Query: []string{"tournament_slug"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/challonge/participants", Queue: "rpc.tournament.challonge_fetch_participants", Query: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/challonge/matches", Queue: "rpc.tournament.challonge_fetch_matches", Query: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/challonge/sync/import/{tournament_id}", Queue: "rpc.tournament.challonge_import", IDParam: "tournament_id", Query: []string{"dry_run"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/challonge/sync/export/{tournament_id}", Queue: "rpc.tournament.challonge_export", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/challonge/sync/push-result/{encounter_id}", Queue: "rpc.tournament.challonge_push_result", IDParam: "encounter_id", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/challonge/sync/log/{tournament_id}", Queue: "rpc.tournament.challonge_sync_log", IDParam: "tournament_id", Query: []string{"limit"}, Auth: edge.AuthRequired},

	// ── Registration Google Sheets (admin) ────────────────────────────────
	{Method: "GET", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/sheet", Queue: "rpc.tournament.sheet_get", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/sheet", Queue: "rpc.tournament.sheet_upsert", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/sheet/sync", Queue: "rpc.tournament.sheet_sync", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/sheet/mapping-catalog", Queue: "rpc.tournament.sheet_mapping_catalog", IDParam: "tournament_id", Query: []string{"include_headers"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/sheet/suggest-mapping", Queue: "rpc.tournament.sheet_suggest_mapping", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/sheet/preview", Queue: "rpc.tournament.sheet_preview", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/balancer/tournaments/{tournament_id}/players/export", Queue: "rpc.tournament.sheet_players_export", IDParam: "tournament_id", Auth: edge.AuthRequired},
}

// DivisionGridRoutes are the public division-grid endpoints. Their patterns are
// ambiguous under the stdlib ServeMux (/{grid_id}/versions vs /by-workspace/{id}
// vs /versions/{id} vs /mappings/...), so they are served via edge.Subtree
// (ordered match, first wins) mounted at /api/v1/division-grids/. Order matters:
// literal-prefix routes first, the wildcard-first /{grid_id}/versions LAST.
var DivisionGridRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/division-grids/by-workspace/{workspace_id}/marketplace/workspaces", Queue: "rpc.tournament.grid_marketplace_workspaces", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/division-grids/by-workspace/{workspace_id}/marketplace/import", Queue: "rpc.tournament.grid_marketplace_import", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "GET", Pattern: "/api/v1/division-grids/by-workspace/{workspace_id}/marketplace", Queue: "rpc.tournament.grid_marketplace_grids", Path: []string{"workspace_id"}, Query: []string{"source_workspace_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/division-grids/by-workspace/{workspace_id}", Queue: "rpc.tournament.grid_workspace_list", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/division-grids/by-workspace/{workspace_id}", Queue: "rpc.tournament.grid_workspace_create", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "POST", Pattern: "/api/v1/division-grids/versions/{version_id}/publish", Queue: "rpc.tournament.grid_version_publish", IDParam: "version_id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/division-grids/versions/{version_id}/clone", Queue: "rpc.tournament.grid_version_clone", IDParam: "version_id", Auth: edge.AuthRequired, Success: 201},
	{Method: "GET", Pattern: "/api/v1/division-grids/versions/{version_id}", Queue: "rpc.tournament.grid_version_get", IDParam: "version_id", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/division-grids/versions/{version_id}", Queue: "rpc.tournament.grid_version_update", IDParam: "version_id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/division-grids/versions/{version_id}", Queue: "rpc.tournament.grid_version_delete", IDParam: "version_id", Auth: edge.AuthRequired, Success: 204},
	{Method: "GET", Pattern: "/api/v1/division-grids/mappings/{source_version_id}/{target_version_id}", Queue: "rpc.tournament.grid_mapping_get", Path: []string{"source_version_id", "target_version_id"}, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/v1/division-grids/mappings/{source_version_id}/{target_version_id}", Queue: "rpc.tournament.grid_mapping_put", Path: []string{"source_version_id", "target_version_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/division-grids/{grid_id}/versions", Queue: "rpc.tournament.grid_versions_list", IDParam: "grid_id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/division-grids/{grid_id}/versions", Queue: "rpc.tournament.grid_version_create", IDParam: "grid_id", Body: true, Auth: edge.AuthRequired, Success: 201},
}
