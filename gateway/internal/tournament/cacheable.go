package tournament

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/respcache"

// PublicCacheableReads opts specific PublicReadRoutes (and the GET reads of
// PublicWriteRoutes) into the gateway's anonymous response cache (see
// internal/respcache): pattern -> invalidation scope. Tournament-scoped
// entries are dropped by the worker's realtime tournament-changed signal;
// TTLOnly entries (aggregates with no single owning tournament) expire
// strictly by the configured TTL.
//
// Deliberately NOT cached:
//   - /encounters/{id}, /matches/{id}(+kill-feed), /teams/{id} — the path id
//     is an encounter/match/team id, not a tournament id; unmappable to the
//     invalidation index. The match endpoints also ride a short (30s)
//     backend TTL with no targeted invalidation at all.
//   - /tournaments/{tournament_id}/registration/form — admin form edits emit
//     no bracket-topic event; a stale form could reject valid submissions.
var PublicCacheableReads = map[string]respcache.Rule{
	// The /tournaments/[id] page shell: overview (layout + metadata), stages,
	// standings. AuthedRead: the backend handlers (rpc.tournament
	// get_tournament/get_stages/get_standings) use the viewer EXCLUSIVELY in
	// the visibility gate and compute the body viewer-agnostically, so an
	// anonymous-written 200 is byte-identical to what any authorized viewer
	// would receive — logged-in spectators share the anonymous entries
	// read-only (misses still go upstream with their own identity).
	"/api/v1/tournaments/{id}":           {Extract: respcache.FromPathValue("id"), AuthedRead: true},
	"/api/v1/tournaments/{id}/stages":    {Extract: respcache.FromPathValue("id"), AuthedRead: true},
	"/api/v1/tournaments/{id}/standings": {Extract: respcache.FromPathValue("id"), AuthedRead: true},
	// Bracket/matches/teams tabs: list reads carry tournament_id as a query
	// param; requests without it (admin-style global lists) bypass the cache.
	//
	// list_encounters uses the viewer only for the scope=my_team filter
	// (encounter/service.py _apply_encounter_filters); every other query
	// shape is viewer-agnostic after the visibility gate, so logged-in
	// spectators share the anonymous entries — EXCEPT my_team requests,
	// whose anonymous body is hardcoded-empty (sa.false() without a viewer).
	"/api/v1/encounters": {
		Extract:          respcache.FromQuery("tournament_id"),
		AuthedRead:       true,
		AuthedReadUnless: respcache.QueryEquals("scope", "my_team"),
	},
	// NO AuthedRead: the overview body carries a per-viewer my_team_count
	// (encounter/service.py get_encounters_overview) — an anonymous entry
	// would always show 0 to logged-in players.
	"/api/v1/encounters/overview": {Extract: respcache.FromQuery("tournament_id")},
	// list_teams passes no viewer into the flow (reads.py) — gate-only, like
	// the page shell routes.
	"/api/v1/teams": {Extract: respcache.FromQuery("tournament_id"), AuthedRead: true},
	// Home page (LiveEventsSection + StatsGrid) and the /tournaments listing:
	// cross-tournament aggregates with no invalidation handle — TTL-bounded
	// staleness is the accepted trade (a tournament flipping live may take up
	// to one TTL to surface on the home page). NO AuthedRead: the tournament
	// list is visibility-filtered per viewer (hidden tournaments appear for
	// eligible viewers), so the anonymous body is not universal.
	"/api/v1/tournaments":                     {Extract: respcache.TTLOnly()},
	"/api/v1/tournaments/statistics/history":  {Extract: respcache.TTLOnly()},
	"/api/v1/tournaments/statistics/division": {Extract: respcache.TTLOnly()},
	"/api/v1/tournaments/statistics/overall":  {Extract: respcache.TTLOnly()},
}

// PublicWriteCacheableReads opts the GET reads living in PublicWriteRoutes
// into the cache. Split from PublicCacheableReads so each table is checked
// against its own route table.
//
// The participants list is the heaviest read of a registration-phase
// tournament AND the only one with zero backend caching (always-live in the
// service layer: per-registration tournament history + division grids on
// every call). Caching is sound because every public mutation
// (create/update/withdraw/check-in) registers an after-commit realtime
// update on the bracket topic (registration/service.py ->
// realtime_commit.py), which this cache consumes — entries drop within
// event-propagation latency of any signup. Admin-side status changes emit
// only on the balancer topic (ignored here); the TTL bounds that staleness.
//
// AuthedRead is a deliberate product decision: the body is viewer-agnostic
// (build_public_registration_list receives only tournament_id; the viewer is
// used exclusively in the visibility gate), so logged-in players share the
// anonymous entries too. Accepted trade: a player's own signup/check-in may
// race the invalidation event by milliseconds, so a refetch fired straight
// off the mutation response can briefly miss their row — their PERSONAL
// state stays live regardless via /registration/me (AuthRequired, never
// cached), and the entry is already dropped by the time the bracket-topic
// event reaches any realtime subscriber.
var PublicWriteCacheableReads = map[string]respcache.Rule{
	"/api/v1/tournaments/{tournament_id}/registration/list": {
		Extract:    respcache.FromPathValue("tournament_id"),
		AuthedRead: true,
	},
}
