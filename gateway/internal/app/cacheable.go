package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/respcache"

// PublicCacheableReads opts app-service ReadRoutes into the gateway's
// anonymous response cache (see internal/respcache).
//
// User profile reads (the /users/[slug] page) are the heaviest anonymous
// reads in the system — cold hero/compare stats legitimately run 20-30s (see
// edge.defaultRPCTimeout's rationale) — and change only when logs are parsed
// or standings recalculate. There is no per-user realtime signal, so they are
// TTLOnly: the Next Data Cache and the backend already accept 300s staleness
// for the same reads; the gateway TTL is far tighter. The two per-tournament
// user reads DO carry a tournament id in the path and get real event
// invalidation.
//
// Deliberately NOT cached:
//   - /achievements/* get surface — registered via edge.Subtree, where
//     ServeMux path values are not populated, so FromPathValue cannot see
//     them; the flat /achievements list is cheap and rarely anonymous-hot.
//   - /users, /users/search, /users/overview* — the users directory; large
//     paginated surface with attacker-controlled query space, low anonymous
//     re-hit rate per exact URL.
//   - /workspaces/by-host — feeds tenant-origin resolution (middleware/SSO
//     paths); correctness there must never lag an admin domain change.
var PublicCacheableReads = map[string]respcache.Rule{
	// Home page: communities section + champions / top-winrate cards.
	"/api/v1/workspaces":          {Extract: respcache.TTLOnly()},
	"/api/v1/statistics/champion": {Extract: respcache.TTLOnly()},
	"/api/v1/statistics/winrate":  {Extract: respcache.TTLOnly()},
	// /users/[slug] page: slug resolution + every profile tab. NO AuthedRead:
	// several reads are AuthOptional (heroes, maps, tournaments) — the viewer
	// reaches the handler, so viewer-agnostic bodies are not guaranteed.
	"/api/v1/users/{name}":               {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/profile":         {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/tournaments":     {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/maps":            {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/maps/summary":    {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/encounters":      {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/matches/summary": {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/heroes":          {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/teammates":       {Extract: respcache.TTLOnly()},
	// Compare page: the most expensive anonymous reads (20-30s cold).
	"/api/v1/users/{id}/compare":        {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/compare/heroes": {Extract: respcache.TTLOnly()},
	// Per-tournament user reads have a real tournament id in the path -> full
	// event-driven invalidation, same as the tournament page routes.
	"/api/v1/users/{id}/tournaments/{tournament_id}":             {Extract: respcache.FromPathValue("tournament_id")},
	"/api/v1/users/{id}/tournaments/{tournament_id}/leaderboard": {Extract: respcache.FromPathValue("tournament_id")},
}
