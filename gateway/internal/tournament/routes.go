// Package tournament holds the gateway route table for tournament-service,
// translated to typed RPC via the shared edge.Dispatcher. The table is data; the
// dispatcher is generic. Specific patterns here win over the /api/v1 reverse
// proxy by ServeMux specificity, so endpoints cut over to RPC incrementally.
package tournament

import (
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

// publicReadTimeout bounds every public read below (pattern: balancer's
// fastReadTimeout). At the 120s edge default a request the browser abandoned
// kept its x-deadline-ms far in the future, so the worker could neither drop it
// nor cancel it while it queued for a handler permit or a pool connection.
const publicReadTimeout = 30 * time.Second

// PublicReadRoutes are the migrated read endpoints (typed RPC). Mirrors the
// public routes in src/routes/{tournament,encounter,match,team}.py.
// Auth: single-tournament reads are AuthOptional so the worker can 404 hidden
// tournaments for ineligible viewers (issue #115) while staying public for
// everyone else; workspace-scoped aggregates (lookup/statistics) stay
// AuthNone; saved-views require a logged-in user.
var PublicReadRoutes = []edge.RouteSpec{
	// tournament.py
	{Method: "GET", Pattern: "/api/v1/tournaments", Queue: "rpc.tournament.list_tournaments", AllQuery: true, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/tournaments/lookup", Queue: "rpc.tournament.lookup_tournaments", Query: []string{"workspace_id", "is_league", "discipline"}, Auth: edge.AuthNone, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/tournaments/statistics/history", Queue: "rpc.tournament.statistics_history", Query: []string{"workspace_id"}, Auth: edge.AuthNone, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/tournaments/statistics/division", Queue: "rpc.tournament.statistics_division", Query: []string{"workspace_id", "discipline"}, Auth: edge.AuthNone, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/tournaments/statistics/overall", Queue: "rpc.tournament.statistics_overall", Query: []string{"workspace_id"}, Auth: edge.AuthNone, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/tournaments/facets", Queue: "rpc.tournament.tournaments_facets", Query: []string{"workspace_id", "status", "is_league", "discipline", "query"}, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/tournaments/{id}", Queue: "rpc.tournament.get_tournament", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/tournaments/{id}/stages", Queue: "rpc.tournament.get_stages", IDParam: "id", Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/tournaments/{id}/standings", Queue: "rpc.tournament.get_standings", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	// Every hero ban a spectator may see and every picked/banned map of the
	// tournament's pick-ban rooms, in one read (the tournament page's ban and
	// map tables). Same gating as standings.
	{Method: "GET", Pattern: "/api/v1/tournaments/{id}/pick-ban/outcomes", Queue: "rpc.tournament.pick_ban_outcomes", IDParam: "id", Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	// FFA league: one stage's lobby tables, and one lobby's own. AuthOptional
	// like the reads above — the worker 404s a hidden tournament for an
	// ineligible viewer and computes the body viewer-agnostically.
	{Method: "GET", Pattern: "/api/v1/tournaments/{id}/stages/{stage_id}/ffa", Queue: "rpc.tournament.ffa_stage", IDParam: "id", Path: []string{"stage_id"}, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	// The bracket an elimination stage with no matches yet would generate,
	// read-only. Same gating; the worker also 404s another tournament's stage.
	{Method: "GET", Pattern: "/api/v1/tournaments/{id}/stages/{stage_id}/bracket-preview", Queue: "rpc.tournament.stage_bracket_preview_public", IDParam: "id", Path: []string{"stage_id"}, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	// encounter.py
	{Method: "GET", Pattern: "/api/v1/encounters", Queue: "rpc.tournament.list_encounters", AllQuery: true, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/encounters/overview", Queue: "rpc.tournament.encounters_overview", AllQuery: true, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/encounters/insights", Queue: "rpc.tournament.encounters_insights", AllQuery: true, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/encounters/views", Queue: "rpc.tournament.saved_views", Query: []string{"workspace_id"}, Auth: edge.AuthRequired, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/encounters/{id}", Queue: "rpc.tournament.get_encounter", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/encounters/{encounter_id}/ffa", Queue: "rpc.tournament.ffa_lobby", IDParam: "encounter_id", Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	// match.py
	{Method: "GET", Pattern: "/api/v1/matches", Queue: "rpc.tournament.list_matches", AllQuery: true, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/matches/{id}", Queue: "rpc.tournament.get_match", IDParam: "id", Query: []string{"entities", "workspace_id"}, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/matches/{id}/kill-feed", Queue: "rpc.tournament.get_match_kill_feed", IDParam: "id", Query: []string{"workspace_id"}, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	// team.py
	{Method: "GET", Pattern: "/api/v1/teams", Queue: "rpc.tournament.list_teams", AllQuery: true, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
	{Method: "GET", Pattern: "/api/v1/teams/{id}", Queue: "rpc.tournament.get_team", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
}
