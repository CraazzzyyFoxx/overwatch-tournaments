package stream

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/respcache"

// PublicCacheableReads opts the spectator read into the gateway's anonymous
// response cache (see internal/respcache): a tournament page open in many tabs
// collapses to one upstream RPC per TTL window instead of one per view.
//
// AuthedRead: the two conditions hold, verified against the handler
// (stream-service src/rpc/reads.py tournament_streams): the viewer is used
// EXCLUSIVELY in assert_tournament_viewable, and build_tournament_streams then
// takes (session, redis, tournament_id) with no viewer at all — the body is
// identical for everyone the gate lets through. Without the grant every
// logged-in viewer of a live tournament page bypassed the cache entirely and
// paid one rpc.stream.tournament_streams call per page view, which is what
// saturated the queue's in-flight cap (Sentry OWT-TOURNAMENTS-23M: 990 sheds in
// 15 minutes, 2026-10-03 17:20-17:35) — and once the queue sheds, nothing is
// cached at all (only 200s are stored), so the herd never recovers on its own.
//
// ponytail: TTLOnly, not tournament-scoped invalidation. respcache only parses
// tournament:{id}:bracket|draft topics and keys its invalidation index by
// tournament_id, so an invalidated stream route would cost a new reason case in
// respcache.go plus a matching one in realtime_commit.py — three files in two
// languages to shave seconds off a cold load, on a surface where the WS signal
// already gives open pages immediacy. Upgrade path: Extract:
// respcache.FromPathValue("tournament_id") + case "stream_changed".
var PublicCacheableReads = map[string]respcache.Rule{
	"/api/v1/streams/tournament/{tournament_id}": {Extract: respcache.TTLOnly(), AuthedRead: true},
}
