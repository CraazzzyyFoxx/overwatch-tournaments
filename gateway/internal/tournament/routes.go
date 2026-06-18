// Package tournament holds the gateway route table for tournament-service,
// translated to typed RPC via the shared edge.Dispatcher. The table is data; the
// dispatcher is generic. Specific patterns here win over the /api/v1 reverse
// proxy by ServeMux specificity, so endpoints cut over to RPC incrementally.
package tournament

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// PublicReadRoutes are the migrated public read endpoints (typed RPC, no auth).
// Mirrors src/routes/tournament.py. The paginated list (GET /api/v1/tournaments)
// is intentionally still proxied — it migrates with the other paginated reads.
var PublicReadRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/tournaments/lookup", Queue: "rpc.tournament.lookup_tournaments", Query: []string{"workspace_id", "is_league"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/tournaments/statistics/history", Queue: "rpc.tournament.statistics_history", Query: []string{"workspace_id"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/tournaments/statistics/division", Queue: "rpc.tournament.statistics_division", Query: []string{"workspace_id"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/tournaments/statistics/overall", Queue: "rpc.tournament.statistics_overall", Query: []string{"workspace_id"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/tournaments/league/seasons", Queue: "rpc.tournament.owal_seasons", Query: []string{"workspace_id"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/tournaments/league/results", Queue: "rpc.tournament.owal_results", Query: []string{"workspace_id", "season"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/tournaments/league/stacks", Queue: "rpc.tournament.owal_stacks", Query: []string{"workspace_id", "season"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/tournaments/{id}", Queue: "rpc.tournament.get_tournament", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/tournaments/{id}/stages", Queue: "rpc.tournament.get_stages", IDParam: "id", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/tournaments/{id}/standings", Queue: "rpc.tournament.get_standings", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthNone},
}
