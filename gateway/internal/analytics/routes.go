// Package analytics holds the gateway route table for analytics-service,
// translated to typed RPC via the shared edge.Dispatcher. The table is data;
// the dispatcher is generic. Specific patterns here win over the /api/analytics
// reverse proxy by ServeMux specificity, so endpoints cut over to RPC
// incrementally.
//
// External paths use the clean /api/analytics/* scheme. The worker's RPC queues
// are path-independent, so the legacy doubled /api/analytics/analytics/* and the
// /api/analytics/v2/* version split are gone. Un-migrated analytics endpoints
// still proxy to analytics-service on their original paths.
package analytics

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// ReadRoutes are the migrated read endpoints (typed RPC). Mirrors the public +
// authenticated reads in src/routes/{analytics_read,v2}.py.
//
// v1 reads (/analytics/*) are public (AuthNone); v2 + job reads require a global
// analytics.read permission (AuthRequired here + has_permission in the handler).
var ReadRoutes = []edge.RouteSpec{
	// analytics_read.py (public)
	{Method: "GET", Pattern: "/api/analytics/algorithms", Queue: "rpc.analytics.list_algorithms", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/analytics/algorithms/{id}", Queue: "rpc.analytics.get_algorithm", IDParam: "id", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/analytics", Queue: "rpc.analytics.get_analytics", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/analytics/streaks", Queue: "rpc.analytics.get_streaks", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/analytics/balance-quality", Queue: "rpc.analytics.balance_quality", AllQuery: true, Auth: edge.AuthNone},
	// v2.py (require analytics.read)
	{Method: "GET", Pattern: "/api/analytics/performance", Queue: "rpc.analytics.v2_performance", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/analytics/standings/distribution", Queue: "rpc.analytics.v2_standings", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/analytics/match-quality", Queue: "rpc.analytics.v2_match_quality", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/analytics/player-anomalies", Queue: "rpc.analytics.v2_player_anomalies", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/analytics/player-anomalies/feedback", Queue: "rpc.analytics.v2_feedback_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/analytics/explain/player/{player_id}/tournament/{tournament_id}", Queue: "rpc.analytics.v2_explain", Path: []string{"player_id", "tournament_id"}, AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/analytics/artifacts", Queue: "rpc.analytics.v2_artifacts", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/analytics/jobs/active", Queue: "rpc.analytics.jobs_active", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/analytics/jobs", Queue: "rpc.analytics.jobs_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/analytics/jobs/{job_id}", Queue: "rpc.analytics.jobs_get", IDParam: "job_id", Auth: edge.AuthRequired},
}

// WriteRoutes are mutations + job-control (typed RPC). Mirrors the writes in
// src/routes/{analytics,v2}.py.
//
// recalculate/points return 202 (now async compute jobs, not the legacy
// synchronous 200); openskill returns 410 (gone). All require auth + the same
// permission gate as their routes (enforced in the handler).
var WriteRoutes = []edge.RouteSpec{
	// analytics.py
	{Method: "POST", Pattern: "/api/analytics/recalculate", Queue: "rpc.analytics.recalculate", Body: true, AllQuery: true, Auth: edge.AuthRequired, Success: 202},
	{Method: "POST", Pattern: "/api/analytics/points", Queue: "rpc.analytics.points", AllQuery: true, Auth: edge.AuthRequired, Success: 202},
	{Method: "POST", Pattern: "/api/analytics/openskill", Queue: "rpc.analytics.openskill", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/analytics/shift", Queue: "rpc.analytics.shift", Body: true, Auth: edge.AuthRequired},
	// v2.py
	{Method: "POST", Pattern: "/api/analytics/player-anomalies/feedback", Queue: "rpc.analytics.feedback_submit", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/analytics/train", Queue: "rpc.analytics.train", Body: true, Auth: edge.AuthRequired, Success: 202},
	{Method: "POST", Pattern: "/api/analytics/infer", Queue: "rpc.analytics.infer", Body: true, Auth: edge.AuthRequired, Success: 202},
	{Method: "POST", Pattern: "/api/analytics/jobs", Queue: "rpc.analytics.create_job", Body: true, AllQuery: true, Auth: edge.AuthRequired, Success: 202},
}
