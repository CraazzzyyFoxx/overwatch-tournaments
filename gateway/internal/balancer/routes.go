// Package balancer holds the gateway route table for balancer-service,
// translated to typed RPC via the shared edge.Dispatcher. The table is data; the
// dispatcher is generic. Specific patterns here win over the /api/balancer
// reverse proxy by ServeMux specificity, so endpoints cut over to RPC
// incrementally (the rest still proxies to balancer-service until decommission).
//
// Paths keep the external /api/balancer/* scheme verbatim (Kong strip_path:false
// + FastAPI root_path="/api/balancer" + admin router prefix /balancer), which
// yields the doubled /api/balancer/balancer/* for the admin routes. The frontend
// is unchanged.
package balancer

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// PublicRoutes need no auth (mirrors GET /config in src/routes/balancer.py).
var PublicRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/balancer/config", Queue: "rpc.balancer.config", Auth: edge.AuthNone},
}

// AdminRoutes are the workspace-scoped admin balancer endpoints from
// src/routes/admin/balancer.py. The router-level require_admin_panel_access()
// gate + per-endpoint workspace RBAC are enforced in the worker; the gateway only
// injects the resolved identity (AuthRequired). The teams-import multipart upload
// is handled separately (binary.go).
var AdminRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/balancer/balancer/tournaments/{tournament_id}/config", Queue: "rpc.balancer.admin.tournament_config_get", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/balancer/tournaments/{tournament_id}/config", Queue: "rpc.balancer.admin.tournament_config_upsert", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/balancer/balancer/tournaments/{tournament_id}/balance", Queue: "rpc.balancer.admin.balance_get", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/balancer/tournaments/{tournament_id}/balance", Queue: "rpc.balancer.admin.balance_save", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/balancer/balances/{balance_id}/export", Queue: "rpc.balancer.admin.balance_export", IDParam: "balance_id", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/balancer/balancer/workspaces/{workspace_id}/config", Queue: "rpc.balancer.admin.workspace_config_get", IDParam: "workspace_id", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/balancer/workspaces/{workspace_id}/config", Queue: "rpc.balancer.admin.workspace_config_upsert", IDParam: "workspace_id", Body: true, Auth: edge.AuthRequired},
}
