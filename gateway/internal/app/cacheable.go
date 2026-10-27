package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/respcache"

// PublicCacheableReads opts app-service ReadRoutes into the gateway's
// anonymous response cache (see internal/respcache). The player statistics,
// profile and achievement reads are stats-service's, cached by
// stats.PublicCacheableReads.
//
// Deliberately NOT cached:
//   - /users, /users/search — the users directory; large paginated surface
//     with attacker-controlled query space, low anonymous re-hit rate per
//     exact URL.
//   - /workspaces/by-host — feeds tenant-origin resolution (middleware/SSO
//     paths); correctness there must never lag an admin domain change.
var PublicCacheableReads = map[string]respcache.Rule{
	// Home page: communities section.
	"/api/v1/workspaces": {Extract: respcache.TTLOnly()},
	// The workspace page's staff block. TTLOnly like the directory above: the
	// resource manifest publishes nothing for workspace membership or RBAC
	// (see respcache/resources.go), so there is no invalidation signal to key
	// on and a role change surfaces within the TTL.
	"/api/v1/workspaces/{workspace_id}/staff": {Extract: respcache.TTLOnly()},
	// /users/[slug] page: slug resolution (the profile tabs are
	// stats.PublicCacheableReads). TTLOnly: there is no per-user realtime signal.
	"/api/v1/users/{name}": {Extract: respcache.TTLOnly()},
}

// AnnouncementCacheableReads opts the site banner (AnnouncementPublicRoutes)
// into the same cache; split from PublicCacheableReads so each table is
// checked against its own route table. The anonymous answer is the global set,
// identical for every visitor (app-service active_announcements reads no
// identity and nothing host-dependent for it). TTLOnly: publishing or
// retiring an announcement emits no realtime signal. NO AuthedRead: a
// signed-in body drops the rows that viewer already dismissed.
var AnnouncementCacheableReads = map[string]respcache.Rule{
	"/api/v1/announcements/active": {Extract: respcache.TTLOnly()},
}
