package stats

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/respcache"

// PublicCacheableReads opts stats-service PublicReadRoutes into the gateway's
// anonymous response cache (see internal/respcache).
//
// User profile reads (the /users/[slug] page) are the heaviest anonymous
// reads in the system — cold hero/compare stats legitimately run 20-30s (see
// edge.defaultRPCTimeout's rationale) — and change only when logs are parsed
// or standings recalculate. There is no per-user realtime signal, so they are
// TTLOnly: the Next Data Cache and the backend already accept 300s staleness
// for the same reads; the gateway TTL is far tighter. The three per-tournament
// user reads DO carry a tournament id in the path and get real event
// invalidation.
//
// Deliberately NOT cached:
//   - /achievements/* get surface — registered via edge.Subtree, where
//     ServeMux path values are not populated, so FromPathValue cannot see
//     them; the flat /achievements list is cheap and rarely anonymous-hot.
//   - /users/overview* — the users directory; large paginated surface with
//     attacker-controlled query space, low anonymous re-hit rate per exact URL.
var PublicCacheableReads = map[string]respcache.Rule{
	// Home page: champions / top-winrate cards, plus the /statistics almanac
	// (players table, records, maps). The statistics routes are AuthNone, so
	// RegisterCached also serves signed-in viewers from these entries.
	"/api/v1/statistics/champion":          {Extract: respcache.TTLOnly()},
	"/api/v1/statistics/winrate":           {Extract: respcache.TTLOnly()},
	"/api/v1/statistics/players":           {Extract: respcache.TTLOnly()},
	"/api/v1/statistics/records":           {Extract: respcache.TTLOnly()},
	"/api/v1/statistics/{discipline}/maps": {Extract: respcache.TTLOnly()},
	// /users/[slug] page: every profile tab (slug resolution is app-service's
	// /users/{name}, app.PublicCacheableReads). NO AuthedRead: several reads are
	// AuthOptional (characters, maps, tournaments) — the viewer reaches the
	// handler, so viewer-agnostic bodies are not guaranteed.
	"/api/v1/users/{id}/profile":         {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/draft-card":      {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/tournaments":     {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/maps":            {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/maps/summary":    {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/encounters":      {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/matches/summary": {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/characters":      {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/teammates":       {Extract: respcache.TTLOnly()},
	// Compare page: the most expensive anonymous reads (20-30s cold).
	"/api/v1/users/{id}/compare":            {Extract: respcache.TTLOnly()},
	"/api/v1/users/{id}/compare/characters": {Extract: respcache.TTLOnly()},
	// Per-tournament user reads have a real tournament id in the path -> full
	// event-driven invalidation, same as the tournament page routes.
	"/api/v1/users/{id}/tournaments/{tournament_id}":             {Extract: respcache.FromPathValue("tournament_id")},
	"/api/v1/users/{id}/tournaments/{tournament_id}/encounters":  {Extract: respcache.FromPathValue("tournament_id")},
	"/api/v1/users/{id}/tournaments/{tournament_id}/leaderboard": {Extract: respcache.FromPathValue("tournament_id")},
	// The tournament page's per-player stat ranks: the same leaderboards, all
	// players at once. AuthedRead: the viewer is used only in the visibility
	// gate (rpc/statistics.py), so the body is the same for every viewer.
	"/api/v1/tournaments/{id}/player-stats": {Extract: respcache.FromPathValue("id"), AuthedRead: true},
}
