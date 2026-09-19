package stream

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/respcache"

// PublicCacheableReads opts the spectator read into the gateway's anonymous
// response cache (see internal/respcache): a tournament page open in many tabs
// collapses to one upstream RPC per TTL window instead of one per view.
//
// NO AuthedRead: the entry is shared read-only by anonymous requests only. The
// body is viewer-agnostic after the gate, but the surface is cheap enough that
// the extra grant buys nothing worth re-verifying against the handler.
//
// ponytail: TTLOnly, not tournament-scoped invalidation. respcache only parses
// tournament:{id}:bracket|draft topics and keys its invalidation index by
// tournament_id, so an invalidated stream route would cost a new reason case in
// respcache.go plus a matching one in realtime_commit.py — three files in two
// languages to shave seconds off a cold load, on a surface where the WS signal
// already gives open pages immediacy. Upgrade path: Extract:
// respcache.FromPathValue("tournament_id") + case "stream_changed".
var PublicCacheableReads = map[string]respcache.Rule{
	"/api/v1/streams/tournament/{tournament_id}": {Extract: respcache.TTLOnly()},
}
