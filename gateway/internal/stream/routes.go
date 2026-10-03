// Package stream holds the gateway route table for stream-service, translated
// to typed RPC via the shared edge.Dispatcher. The table is data; the
// dispatcher is generic.
//
// The whole /api/v1/streams/* namespace is typed RPC — there is no HTTP
// stream-service to proxy to; unmatched paths get the REST mux's 404 catch-all
// in cmd/gateway/main.go.
package stream

import (
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

// publicReadTimeout bounds the spectator read's RPC. It is a Redis hash read
// plus two queries, so the 120s edge default (reserved for writes, imports and
// exports) only means one thing here: during a burst each shed-adjacent call
// pins one of the queue's 64 in-flight slots — and one x-deadline-ms worth of
// stream-svc prefetch — for two minutes after the viewer's tab gave up. Same
// value and same reason as balancer's fastReadTimeout.
const publicReadTimeout = 15 * time.Second

// PublicRoutes is the spectator read: which channels are live for a
// tournament. Anonymous-friendly, but AuthOptional rather than AuthNone: the
// handler gates with assert_tournament_viewable, and that gate needs the viewer
// (`c.optional_actor`). Under AuthNone the dispatcher never injects
// data["identity"], so a hidden tournament answered 404 for EVERY viewer —
// including the workspace admin and the preview allowlist who can see the page
// itself. Same mode as every other public tournament read (tournament.routes).
var PublicRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/streams/tournament/{tournament_id}", Queue: "rpc.stream.tournament_streams", Path: []string{"tournament_id"}, AllQuery: true, Auth: edge.AuthOptional, Timeout: publicReadTimeout},
}

// AdminRoutes carries the operator surfaces:
//
//   - poller health — why nothing is live. The tick swallows every Helix failure
//     so an outage cannot kill the scheduler, which means a broken poller and a
//     working one look identical from outside; this read names the difference.
//     Gated by a GLOBAL stream.read in the handler, not a workspace-scoped one:
//     there is one poller for the whole platform. The ticks read is the same
//     outcome for the last few hundred ticks, under the same gate.
//   - re-poll — force the next heartbeat to run a tick instead of waiting out the
//     configured interval. Gated by stream.update; 202 because the work happens on
//     the poller's own schedule, not in this request.
var AdminRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/streams/health", Queue: "rpc.stream.health", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/streams/health/ticks", Queue: "rpc.stream.ticks", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/streams/tournament/{tournament_id}/repoll", Queue: "rpc.stream.repoll", Path: []string{"tournament_id"}, Query: []string{"workspace_id"}, Auth: edge.AuthRequired, Success: 202},
}
