// Package analytics holds the gateway route table for analytics-service,
// translated to typed RPC via the shared edge.Dispatcher. The table is data;
// the dispatcher is generic. Specific patterns here win over the /api/v1/analytics
// reverse proxy by ServeMux specificity, so endpoints cut over to RPC
// incrementally.
//
// External paths use the clean /api/v1/analytics/* scheme. The worker's RPC queues
// are path-independent, so the legacy doubled /api/v1/analytics/analytics/* and the
// /api/v1/analytics/v2/* version split are gone. Un-migrated analytics endpoints
// still proxy to analytics-service on their original paths.
package analytics

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// ReadRoutes are the migrated read endpoints (typed RPC).
//
// Rating reads (/analytics algorithms, standings, streaks) are public
// (AuthNone); ML + job reads require a global analytics.read permission
// (AuthRequired here + has_permission in the handler).
var ReadRoutes = []edge.RouteSpec{
	// rating reads (public)
	{Method: "GET", Pattern: "/api/v1/analytics/algorithms", Queue: "rpc.analytics.list_algorithms", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/analytics/algorithms/{id}", Queue: "rpc.analytics.get_algorithm", IDParam: "id", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/analytics", Queue: "rpc.analytics.get_analytics", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/analytics/streaks", Queue: "rpc.analytics.get_streaks", AllQuery: true, Auth: edge.AuthNone},
	// ML reads (require analytics.read)
	{Method: "GET", Pattern: "/api/v1/analytics/performance", Queue: "rpc.analytics.performance", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/analytics/standings/distribution", Queue: "rpc.analytics.standings", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/analytics/match-quality", Queue: "rpc.analytics.match_quality", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/analytics/player-anomalies", Queue: "rpc.analytics.player_anomalies", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/analytics/player-anomalies/feedback", Queue: "rpc.analytics.feedback_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/analytics/explain/player/{player_id}/tournament/{tournament_id}", Queue: "rpc.analytics.explain", Path: []string{"player_id", "tournament_id"}, AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/analytics/artifacts", Queue: "rpc.analytics.artifacts", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/analytics/jobs/active", Queue: "rpc.analytics.jobs_active", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/analytics/jobs", Queue: "rpc.analytics.jobs_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/analytics/jobs/{job_id}", Queue: "rpc.analytics.jobs_get", IDParam: "job_id", Auth: edge.AuthRequired},
}

// WriteRoutes are mutations + job-control (typed RPC).
//
// recalculate/points return 202 (now async compute jobs, not the legacy
// synchronous 200); openskill returns 410 (gone). All require auth + the same
// permission gate as their routes (enforced in the handler).
var WriteRoutes = []edge.RouteSpec{
	// rating writes
	{Method: "POST", Pattern: "/api/v1/analytics/recalculate", Queue: "rpc.analytics.recalculate", Body: true, AllQuery: true, Auth: edge.AuthRequired, Success: 202},
	{Method: "POST", Pattern: "/api/v1/analytics/points", Queue: "rpc.analytics.points", AllQuery: true, Auth: edge.AuthRequired, Success: 202},
	{Method: "POST", Pattern: "/api/v1/analytics/openskill", Queue: "rpc.analytics.openskill", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/analytics/shift", Queue: "rpc.analytics.shift", Body: true, Auth: edge.AuthRequired},
	// ML + jobs
	{Method: "POST", Pattern: "/api/v1/analytics/player-anomalies/feedback", Queue: "rpc.analytics.feedback_submit", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/analytics/train", Queue: "rpc.analytics.train", Body: true, Auth: edge.AuthRequired, Success: 202},
	{Method: "POST", Pattern: "/api/v1/analytics/infer", Queue: "rpc.analytics.infer", Body: true, Auth: edge.AuthRequired, Success: 202},
	{Method: "POST", Pattern: "/api/v1/analytics/jobs", Queue: "rpc.analytics.create_job", Body: true, AllQuery: true, Auth: edge.AuthRequired, Success: 202},
}
