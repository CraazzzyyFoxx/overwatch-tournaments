// Package tournament holds the gateway route table for tournament-service,
// translated to typed RPC via the shared edge.Dispatcher. The table is data; the
// dispatcher is generic. Specific patterns here win over the /api/v1 reverse
// proxy by ServeMux specificity, so endpoints cut over to RPC incrementally.
package tournament

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// PublicReadRoutes are the migrated read endpoints (typed RPC). Mirrors the
// public routes in src/routes/{tournament,encounter,match,team}.py.
// Auth: most reads are public; encounters list/overview take optional identity
// (viewer-scoped fields); saved-views require a logged-in user.
var PublicReadRoutes = []edge.RouteSpec{
	// tournament.py
	{Method: "GET", Pattern: "/api/v1/tournaments", Queue: "rpc.tournament.list_tournaments", AllQuery: true, Auth: edge.AuthNone},
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
	// encounter.py
	{Method: "GET", Pattern: "/api/v1/encounters", Queue: "rpc.tournament.list_encounters", AllQuery: true, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/encounters/overview", Queue: "rpc.tournament.encounters_overview", AllQuery: true, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/encounters/views", Queue: "rpc.tournament.saved_views", Query: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/encounters/{id}", Queue: "rpc.tournament.get_encounter", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthNone},
	// match.py
	{Method: "GET", Pattern: "/api/v1/matches", Queue: "rpc.tournament.list_matches", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/matches/{id}", Queue: "rpc.tournament.get_match", IDParam: "id", Query: []string{"entities", "workspace_id"}, Auth: edge.AuthNone},
	// team.py
	{Method: "GET", Pattern: "/api/v1/teams", Queue: "rpc.tournament.list_teams", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/teams/{id}", Queue: "rpc.tournament.get_team", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthNone},
}
