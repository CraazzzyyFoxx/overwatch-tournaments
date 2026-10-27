package balancer

import (
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/respcache"
)

// draftReadTTL backstops a live draft read when its frame is missed (Redis
// pub/sub is fire-and-forget), and bounds how long the tournament lookup keeps
// pointing at a session that is no longer the active one.
const draftReadTTL = 5 * time.Second

// DraftCacheableReads opts the draft room's hot reads into the gateway's
// anonymous response cache (see internal/respcache): a room of spectators
// joining or reconnecting at once costs one upstream build per session state
// instead of one per client. Entries are scoped to the draft SESSION — any
// frame on draft:{session_id}:board drops its boards, any frame on
// draft:{session_id}:chat drops its chat pages — and never to a tournament.
//
//   - Both boards are AuthNone, so RegisterCached grants AuthedRead and
//     captains share the spectators' entry: build_board takes no viewer. The
//     tournament lookup learns its session from the body (null = no draft,
//     never stored).
//   - The chat history is AuthOptional: a bearer gets its own role, can_write
//     and mute state, so only anonymous requests (one identical spectator
//     envelope) use the cache and a bearer bypasses it both ways. limit and
//     after_id stay in the key.
var DraftCacheableReads = map[string]respcache.Rule{
	"/api/v1/balancer/draft/sessions/{session_id}/board": {
		Extract: respcache.FromPathValue("session_id"), Scope: respcache.ScopeDraftBoard, TTL: draftReadTTL,
	},
	"/api/v1/balancer/draft/tournaments/{tournament_id}/draft": {
		ExtractFromBody: respcache.ExtractSessionIDFromJSONBody(), Scope: respcache.ScopeDraftBoard, TTL: draftReadTTL,
	},
	"/api/v1/balancer/draft/sessions/{session_id}/chat": {
		Extract: respcache.FromPathValue("session_id"), Scope: respcache.ScopeDraftChat, TTL: draftReadTTL,
	},
}
