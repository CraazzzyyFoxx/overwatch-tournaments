// Package balancer holds the gateway route table for balancer-service,
// translated to typed RPC via the shared edge.Dispatcher. The table is data; the
// dispatcher is generic. Specific patterns here win over the /api/balancer
// reverse proxy by ServeMux specificity, so endpoints cut over to RPC
// incrementally (the rest still proxies to balancer-service until decommission).
//
// External paths use the clean /api/balancer/* scheme. The worker's RPC queues
// are path-independent, so the legacy doubled /api/balancer/balancer/* (FastAPI
// root_path + admin router prefix) is gone. Un-migrated balancer endpoints still
// proxy to balancer-service on their original paths.
package balancer

import (
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

// Per-route RPC timeouts for the cheap point reads below. The 120s edge
// default exists for heavy balancer computations; config reads and draft
// board/status polling are indexed point lookups that should fail fast
// instead of pinning worker prefetch slots during an incident.
const fastReadTimeout = 15 * time.Second

// PublicRoutes need no auth (mirrors GET /config in src/routes/balancer.py).
var PublicRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/balancer/config", Queue: "rpc.balancer.config", Auth: edge.AuthNone, Timeout: fastReadTimeout},
}

// AdminRoutes are the workspace-scoped admin balancer endpoints from
// src/routes/admin/balancer.py. The router-level require_admin_panel_access()
// gate + per-endpoint workspace RBAC are enforced in the worker; the gateway only
// injects the resolved identity (AuthRequired). The teams-import multipart upload
// is handled separately (binary.go).
var AdminRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/balancer/tournaments/{tournament_id}/config", Queue: "rpc.balancer.admin.tournament_config_get", IDParam: "tournament_id", Auth: edge.AuthRequired, Timeout: fastReadTimeout},
	{Method: "PUT", Pattern: "/api/balancer/tournaments/{tournament_id}/config", Queue: "rpc.balancer.admin.tournament_config_upsert", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/balancer/tournaments/{tournament_id}/balance", Queue: "rpc.balancer.admin.balance_get", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/tournaments/{tournament_id}/balance", Queue: "rpc.balancer.admin.balance_save", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/balances/{balance_id}/export", Queue: "rpc.balancer.admin.balance_export", IDParam: "balance_id", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/balancer/workspaces/{workspace_id}/config", Queue: "rpc.balancer.admin.workspace_config_get", IDParam: "workspace_id", Auth: edge.AuthRequired, Timeout: fastReadTimeout},
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/config", Queue: "rpc.balancer.admin.workspace_config_upsert", IDParam: "workspace_id", Body: true, Auth: edge.AuthRequired},
}

// JobRoutes are the authenticated public job API reads (status poll + result)
// from src/routes/balancer.py. job_id is a uuid hex string (not int). Job
// creation is a multipart upload handled separately (binary.go); the SSE stream
// is not migrated (dead code — progress flows over the WS topic).
var JobRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/balancer/jobs/{job_id}", Queue: "rpc.balancer.jobs.status", IDParam: "job_id", Auth: edge.AuthRequired, Timeout: fastReadTimeout},
	{Method: "GET", Pattern: "/api/balancer/jobs/{job_id}/result", Queue: "rpc.balancer.jobs.result", IDParam: "job_id", Auth: edge.AuthRequired},
}

// DraftReadRoutes are the public draft spectating reads (no auth), from
// src/routes/admin/draft.py.
var DraftReadRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/draft", Queue: "rpc.balancer.draft.tournament_board", IDParam: "tournament_id", Auth: edge.AuthNone, Timeout: fastReadTimeout},
	{Method: "GET", Pattern: "/api/balancer/draft/sessions/{session_id}", Queue: "rpc.balancer.draft.session_get", IDParam: "session_id", Auth: edge.AuthNone, Timeout: fastReadTimeout},
	{Method: "GET", Pattern: "/api/balancer/draft/sessions/{session_id}/board", Queue: "rpc.balancer.draft.session_board", IDParam: "session_id", Auth: edge.AuthNone, Timeout: fastReadTimeout},
}

// DraftRoutes are the authenticated draft endpoints: suggestions (draft-session
// read), admin lifecycle (keyed by tournament_id for the permission, session_id
// for the action), and pick actions (keyed by pick_id). Permissions + captain
// identity for /select are enforced in the worker. The path segments
// (tournaments/sessions/picks) are distinct, so no subtree matcher is needed.
var DraftRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/balancer/draft/sessions/{session_id}/suggestions", Queue: "rpc.balancer.draft.suggestions", IDParam: "session_id", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/balancer/draft/sessions/{session_id}/feasibility", Queue: "rpc.balancer.draft.feasibility", IDParam: "session_id", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/balancer/draft/picks/{pick_id}/options", Queue: "rpc.balancer.draft.pick_options", IDParam: "pick_id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/sessions/{session_id}/players/{player_id}/roles", Queue: "rpc.balancer.draft.player_role_edit", IDParam: "player_id", Path: []string{"session_id"}, Body: true, Auth: edge.AuthRequired},
	// lifecycle
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions", Queue: "rpc.balancer.draft.session_create", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/seed", Queue: "rpc.balancer.draft.seed", IDParam: "session_id", Path: []string{"tournament_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}", Queue: "rpc.balancer.draft.session_patch", IDParam: "session_id", Path: []string{"tournament_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/start", Queue: "rpc.balancer.draft.start", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/pause", Queue: "rpc.balancer.draft.pause", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/resume", Queue: "rpc.balancer.draft.resume", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/cancel", Queue: "rpc.balancer.draft.cancel", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/rollback", Queue: "rpc.balancer.draft.rollback", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/export", Queue: "rpc.balancer.draft.export", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	// pick actions
	{Method: "POST", Pattern: "/api/balancer/draft/picks/{pick_id}/select", Queue: "rpc.balancer.draft.pick_select", IDParam: "pick_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/picks/{pick_id}/autopick", Queue: "rpc.balancer.draft.pick_autopick", IDParam: "pick_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/picks/{pick_id}/override", Queue: "rpc.balancer.draft.pick_override", IDParam: "pick_id", Body: true, Auth: edge.AuthRequired},
}
