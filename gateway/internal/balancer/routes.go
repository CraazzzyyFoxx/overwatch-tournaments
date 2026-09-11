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
	{Method: "GET", Pattern: "/api/balancer/tournaments/{tournament_id}/summary", Queue: "rpc.balancer.admin.tournament_summary_get", IDParam: "tournament_id", Auth: edge.AuthRequired, Timeout: fastReadTimeout},
	{Method: "GET", Pattern: "/api/balancer/tournaments/{tournament_id}/balance", Queue: "rpc.balancer.admin.balance_get", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/tournaments/{tournament_id}/balance", Queue: "rpc.balancer.admin.balance_save", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/balances/{balance_id}/export", Queue: "rpc.balancer.admin.balance_export", IDParam: "balance_id", Auth: edge.AuthRequired},
	// Rank-only re-export: updates the ranks of players the balance already
	// materialized, without touching the teams (so a live bracket survives).
	{Method: "POST", Pattern: "/api/balancer/balances/{balance_id}/export-ranks", Queue: "rpc.balancer.admin.balance_ranks_export", IDParam: "balance_id", Auth: edge.AuthRequired},
	// Materialize pre-formed registered teams (docs/plans/2026-08-20-team-registration.md §5).
	// `Body: true` carries the optional `team_ids` narrowing; an empty body exports
	// every complete team. Unlike balance_export this refuses when standings exist
	// for teams it does not own, so it cannot silently invalidate a live bracket.
	{Method: "POST", Pattern: "/api/balancer/tournaments/{tournament_id}/registered-teams/export", Queue: "rpc.balancer.teams.export_registered", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/balancer/workspaces/{workspace_id}/config", Queue: "rpc.balancer.admin.workspace_config_get", IDParam: "workspace_id", Auth: edge.AuthRequired, Timeout: fastReadTimeout},
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/config", Queue: "rpc.balancer.admin.workspace_config_upsert", IDParam: "workspace_id", Body: true, Auth: edge.AuthRequired},
}

// RosterRoutes are the workspace roster, its rank layers, and custom games (mixes).
var RosterRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/balancer/workspaces/{workspace_id}/players", Queue: "rpc.balancer.players.list", Path: []string{"workspace_id"}, AllQuery: true, Auth: edge.AuthRequired, Timeout: fastReadTimeout},
	{Method: "GET", Pattern: "/api/balancer/workspaces/{workspace_id}/players/summary", Queue: "rpc.balancer.players.summary", Path: []string{"workspace_id"}, AllQuery: true, Auth: edge.AuthRequired, Timeout: fastReadTimeout},
	{Method: "POST", Pattern: "/api/balancer/workspaces/{workspace_id}/players", Queue: "rpc.balancer.players.upsert", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	// One route for both rank layers: the body's `scope` picks workspace canon or
	// the caller's own book. A foreign author is never writable, so it is not a
	// path segment -- reading somebody else's book is a query param on the list.
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/players/{member_id}/ranks", Queue: "rpc.balancer.players.set_ranks", IDParam: "member_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/balancer/workspaces/{workspace_id}/players/authors", Queue: "rpc.balancer.players.authors", Path: []string{"workspace_id"}, Auth: edge.AuthRequired, Timeout: fastReadTimeout},
	// The five mix reads (list, stats, get, matches, rotation) are public:
	// AuthNone, like the draft spectating reads. A mix screen is a lobby board
	// a host reads out to players who may not hold an account here at all, and
	// none of these handlers looks at the caller -- the ranks they return are
	// the host's own book, resolved from the mix's host_user_id. Every write
	// below stays AuthRequired plus host-or-co-host in the worker.
	{Method: "GET", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games", Queue: "rpc.balancer.custom.list", Path: []string{"workspace_id"}, Auth: edge.AuthNone, Timeout: fastReadTimeout},
	{Method: "POST", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games", Queue: "rpc.balancer.custom.create", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	// Workspace-wide mix scoreboard, not a per-game read. ServeMux precedence
	// already gives this literal segment the win over {game_id} whatever the
	// order; it is listed above that row so the table reads the same way.
	{Method: "GET", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/stats", Queue: "rpc.balancer.custom.stats", Path: []string{"workspace_id"}, AllQuery: true, Auth: edge.AuthNone, Timeout: fastReadTimeout},
	{Method: "GET", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}", Queue: "rpc.balancer.custom.get", IDParam: "game_id", Path: []string{"workspace_id"}, Auth: edge.AuthNone, Timeout: fastReadTimeout},
	{Method: "POST", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/roster", Queue: "rpc.balancer.custom.update_roster", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/players/{workspace_member_id}", Queue: "rpc.balancer.custom.update_player", IDParam: "game_id", Path: []string{"workspace_id", "workspace_member_id"}, Body: true, Auth: edge.AuthRequired},
	// Whole-lineup participation write: the rotation hint moves several rows at
	// once, and one request keeps them in one transaction (and one realtime signal).
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/players", Queue: "rpc.balancer.custom.set_participation", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/team-names", Queue: "rpc.balancer.custom.set_team_names", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/role-mask", Queue: "rpc.balancer.custom.set_role_mask", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/points-per-win", Queue: "rpc.balancer.custom.set_points_per_win", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/next-map", Queue: "rpc.balancer.custom.set_next_map", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/discord-channel", Queue: "rpc.balancer.custom.set_discord_channel", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/discord/post", Queue: "rpc.balancer.custom.post_discord", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/balancer-config", Queue: "rpc.balancer.custom.set_balancer_config", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/host", Queue: "rpc.balancer.custom.transfer_host", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/co-hosts", Queue: "rpc.balancer.custom.add_co_host", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/co-hosts/{co_host_user_id}", Queue: "rpc.balancer.custom.remove_co_host", IDParam: "game_id", Path: []string{"workspace_id", "co_host_user_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/balance", Queue: "rpc.balancer.custom.balance", IDParam: "game_id", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/outcome", Queue: "rpc.balancer.custom.record_outcome", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/teams/swap", Queue: "rpc.balancer.custom.swap_seats", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/matches", Queue: "rpc.balancer.custom.match_history", IDParam: "game_id", Path: []string{"workspace_id"}, Auth: edge.AuthNone, Timeout: fastReadTimeout},
	{Method: "DELETE", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/matches/{match_id}", Queue: "rpc.balancer.custom.undo_match", IDParam: "game_id", Path: []string{"workspace_id", "match_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/rotation", Queue: "rpc.balancer.custom.rotation", IDParam: "game_id", Path: []string{"workspace_id"}, Auth: edge.AuthNone, Timeout: fastReadTimeout},
	{Method: "POST", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/close", Queue: "rpc.balancer.custom.close", IDParam: "game_id", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/balancer/workspaces/{workspace_id}/custom-games/{game_id}", Queue: "rpc.balancer.custom.hard_delete", IDParam: "game_id", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
}

// JobRoutes are the authenticated public job API reads (status poll + result)
// from src/routes/balancer.py, plus the tournament balance trigger. job_id is a
// uuid hex string (not int).
//
// The tournament trigger carries NO player payload: the xv-1 input is built
// server-side from shared.services.roster, the same engine the draft reads, so
// the browser can no longer hand the algorithm a different set of ranks than
// the draft sees. The multipart upload route (binary.go) stays for the
// bring-your-own-file case; the SSE stream is not migrated (dead code —
// progress flows over the WS topic).
var JobRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/balancer/jobs/{job_id}", Queue: "rpc.balancer.jobs.status", IDParam: "job_id", Auth: edge.AuthRequired, Timeout: fastReadTimeout},
	{Method: "GET", Pattern: "/api/balancer/jobs/{job_id}/result", Queue: "rpc.balancer.jobs.result", IDParam: "job_id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/tournaments/{tournament_id}/balance", Queue: "rpc.balancer.jobs.create_for_tournament", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired, Success: 202},
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
	{Method: "GET", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions", Queue: "rpc.balancer.draft.session_list", IDParam: "tournament_id", Auth: edge.AuthRequired, Timeout: fastReadTimeout},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions", Queue: "rpc.balancer.draft.session_create", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}", Queue: "rpc.balancer.draft.session_delete", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired, Success: 204},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/seed", Queue: "rpc.balancer.draft.seed", IDParam: "session_id", Path: []string{"tournament_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}", Queue: "rpc.balancer.draft.session_patch", IDParam: "session_id", Path: []string{"tournament_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/start", Queue: "rpc.balancer.draft.start", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/pause", Queue: "rpc.balancer.draft.pause", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/resume", Queue: "rpc.balancer.draft.resume", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/cancel", Queue: "rpc.balancer.draft.cancel", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/rollback", Queue: "rpc.balancer.draft.rollback", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/export", Queue: "rpc.balancer.draft.export", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	// Rank-only re-export: leaves the exported teams in place, refreshes their ranks.
	{Method: "POST", Pattern: "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}/export-ranks", Queue: "rpc.balancer.draft.export_ranks", IDParam: "session_id", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	// pick actions
	{Method: "POST", Pattern: "/api/balancer/draft/picks/{pick_id}/select", Queue: "rpc.balancer.draft.pick_select", IDParam: "pick_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/picks/{pick_id}/autopick", Queue: "rpc.balancer.draft.pick_autopick", IDParam: "pick_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/balancer/draft/picks/{pick_id}/override", Queue: "rpc.balancer.draft.pick_override", IDParam: "pick_id", Body: true, Auth: edge.AuthRequired},
}
