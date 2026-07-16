// Package edge is a reusable, data-driven HTTP→RPC dispatcher shared by every
// service handler on the gateway. A service declares a []RouteSpec table and the
// generic Dispatcher translates each request into an RPC call (building the body
// from path/query/JSON params + the gateway-injected identity) and maps the
// {ok,data,error} envelope back to an HTTP response.
package edge

import (
	"net/http"
	"time"
)

// AuthMode declares a route's identity requirement.
type AuthMode int

const (
	// AuthNone forwards no identity (public, unauthenticated).
	AuthNone AuthMode = iota
	// AuthOptional injects identity when present, but allows anonymous.
	AuthOptional
	// AuthRequired rejects the request with 401 when no identity is present.
	AuthRequired
)

// RouteSpec declares one HTTP route and how to translate it into an RPC call.
type RouteSpec struct {
	Method   string        // "GET" | "POST" | "PATCH" | "PUT" | "DELETE"
	Pattern  string        // ServeMux pattern, e.g. "/api/v1/tournaments/{id}"
	Queue    string        // RPC queue, e.g. "rpc.tournament.get_tournament" or "rpc.tournament.admin.update"
	Entity   string        // generic-CRUD entity -> data["entity"] ("" for a typed method)
	Action   string        // generic-CRUD action -> data["action"] ("" for a typed method)
	IDParam  string        // path param copied to data["id"]
	Path     []string      // path params copied verbatim into the body (by name)
	Query    []string      // query params copied into data["query"]
	AllQuery bool          // forward ALL query params into data["query"] (for pagination/filter routes)
	Body     bool          // merge the JSON request body into data["payload"]
	Auth     AuthMode      // identity requirement
	Success  int           // success HTTP status (0 -> 200)
	Timeout  time.Duration // per-route RPC timeout (0 -> the 120s edge default)
}

func (s RouteSpec) successStatus() int {
	if s.Success == 0 {
		return http.StatusOK
	}
	return s.Success
}

// callTimeout returns the RPC timeout for this route: the per-route override
// when set, otherwise the blanket edge default. The value drives both the
// gateway-side context deadline and, through it, the AMQP per-message TTL +
// x-deadline-ms header (see rpc/deadline.go), so cheap reads stop occupying
// worker prefetch slots for up to 120s during incidents.
func (s RouteSpec) callTimeout() time.Duration {
	if s.Timeout <= 0 {
		return defaultRPCTimeout
	}
	return s.Timeout
}
