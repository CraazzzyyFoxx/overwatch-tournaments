// Package app holds the gateway route table for app-service (compose `backend`),
// translated to typed RPC via the shared edge.Dispatcher. The table is data; the
// dispatcher is generic. Specific patterns here win over the /api/v1/core reverse
// proxy by ServeMux specificity, so endpoints cut over to RPC incrementally.
//
// app-service is served externally under /api/v1/core/* (FastAPI root_path), so
// every pattern keeps that prefix verbatim — the frontend is unchanged.
//
// hero/map/gamemode/achievement get+list go through the shared CRUD read engine
// (rpc.app.read.{get,list} with Entity set, public_read=True). Everything else is
// a bespoke rpc.app.<domain>.<method> subscriber. All reads are public (AuthNone).
package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// ReadRoutes are flat (non-ambiguous) public read endpoints. Achievements' get
// surface is in AchievementsSubtreeRoutes (ServeMux can't disambiguate
// /{id}/users vs /user/{user_id}); the achievements *list* stays here.
var ReadRoutes = []edge.RouteSpec{
	// --- heroes -------------------------------------------------------------
	{Method: "GET", Pattern: "/api/v1/core/heroes/lookup", Queue: "rpc.app.heroes.lookup", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/heroes/statistics/playtime", Queue: "rpc.app.heroes.playtime", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/heroes/{hero_id}/leaderboard", Queue: "rpc.app.heroes.leaderboard", IDParam: "hero_id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/heroes/{id}", Queue: "rpc.app.read.get", Entity: "hero", Action: "get", IDParam: "id", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/heroes", Queue: "rpc.app.read.list", Entity: "hero", Action: "list", AllQuery: true, Auth: edge.AuthNone},
	// --- maps ---------------------------------------------------------------
	{Method: "GET", Pattern: "/api/v1/core/maps/lookup", Queue: "rpc.app.maps.lookup", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/maps/{id}", Queue: "rpc.app.read.get", Entity: "map", Action: "get", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/maps", Queue: "rpc.app.read.list", Entity: "map", Action: "list", AllQuery: true, Auth: edge.AuthNone},
	// --- gamemodes ----------------------------------------------------------
	{Method: "GET", Pattern: "/api/v1/core/gamemodes/lookup", Queue: "rpc.app.gamemodes.lookup", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/gamemodes/{id}", Queue: "rpc.app.read.get", Entity: "gamemode", Action: "get", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/gamemodes", Queue: "rpc.app.read.list", Entity: "gamemode", Action: "list", AllQuery: true, Auth: edge.AuthNone},
	// --- achievements (list only; get surface is the subtree) ---------------
	{Method: "GET", Pattern: "/api/v1/core/achievements", Queue: "rpc.app.read.list", Entity: "achievement", Action: "list", AllQuery: true, Auth: edge.AuthNone},
	// --- statistics ---------------------------------------------------------
	{Method: "GET", Pattern: "/api/v1/core/statistics/dashboard", Queue: "rpc.app.statistics.dashboard", Query: []string{"workspace_id"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/statistics/champion", Queue: "rpc.app.statistics.champion", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/statistics/winrate", Queue: "rpc.app.statistics.winrate", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/statistics/won-maps", Queue: "rpc.app.statistics.won_maps", AllQuery: true, Auth: edge.AuthNone},
	// --- workspaces (public reads; writes + members in Phase 2) -------------
	{Method: "GET", Pattern: "/api/v1/core/workspaces", Queue: "rpc.app.workspaces.list", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/workspaces/{id}", Queue: "rpc.app.workspaces.get", IDParam: "id", Auth: edge.AuthNone},
	// --- users (literals + /{id}/... + bare /{name} last) -------------------
	{Method: "GET", Pattern: "/api/v1/core/users", Queue: "rpc.app.users.list", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/search", Queue: "rpc.app.users.search", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/overview", Queue: "rpc.app.users.overview", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/overview/stats", Queue: "rpc.app.users.overview_stats", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/overview/catalog", Queue: "rpc.app.users.overview_catalog", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{id}/compare", Queue: "rpc.app.users.compare", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{id}/compare/heroes", Queue: "rpc.app.users.compare_heroes", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{id}/profile", Queue: "rpc.app.users.get_profile", IDParam: "id", Query: []string{"workspace_id"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{id}/tournaments", Queue: "rpc.app.users.tournaments", IDParam: "id", Query: []string{"workspace_id"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{id}/tournaments/{tournament_id}", Queue: "rpc.app.users.tournament", IDParam: "id", Path: []string{"tournament_id"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{id}/maps", Queue: "rpc.app.users.maps", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{id}/maps/summary", Queue: "rpc.app.users.maps_summary", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{id}/encounters", Queue: "rpc.app.users.encounters", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{id}/matches/summary", Queue: "rpc.app.users.matches_summary", IDParam: "id", Query: []string{"workspace_id"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{id}/heroes", Queue: "rpc.app.users.heroes", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{id}/teammates", Queue: "rpc.app.users.teammates", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/core/users/{name}", Queue: "rpc.app.users.by_name", Path: []string{"name"}, Query: []string{"entities"}, Auth: edge.AuthNone},
}
