package edge

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apierr"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/clientip"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
)

const (
	// defaultRPCTimeout matches the old Kong edge allowance (up to 120s). Some
	// stats-service reads (e.g. /users/{id}/compare, hero stats on a cold cache)
	// legitimately run ~20-30s; a tighter cap would turn slow-but-successful
	// responses into 504s that the HTTP edge returned as 200/500. The gateway
	// server has no write timeout for the same reason (long WS + long balancer
	// requests). Cheap reads override this per route via RouteSpec.Timeout.
	defaultRPCTimeout = 120 * time.Second
	maxBody           = 12 << 20 // 12 MiB request-body cap before buffering into the RPC message
)

// RPCCaller is the subset of rpc.Client the dispatcher needs (eases testing).
type RPCCaller interface {
	Call(ctx context.Context, queue string, body []byte) ([]byte, error)
}

// IdentityResolver returns the validated RBAC identity payload for a request
// (user_id/is_superuser/roles/permissions/workspaces), ok=false if absent, and
// a non-nil error when the identity backend itself was unavailable (shed,
// disconnected, or timed out). Callers must treat a non-nil error as a 503,
// never as "not authenticated".
type IdentityResolver func(r *http.Request) (map[string]any, bool, error)

// Identity is a validated principal as the dispatcher forwards it.
type Identity struct {
	// Payload is the validate_token payload exactly as identity-svc serialized
	// it. principal.Resolver caches these bytes with its verdict, so injecting
	// them costs no per-request re-marshal of a decoded map.
	Payload json.RawMessage
	// SoleWorkspaceID is the ONLY workspace the payload carries, 0 when it
	// carries none or several (see soleWorkspaceID).
	SoleWorkspaceID int64
}

// IdentitySource is IdentityResolver in the dispatcher's own form, with the
// same ok/error semantics.
type IdentitySource func(r *http.Request) (Identity, bool, error)

// Dispatcher turns RouteSpecs into http handlers that call RPC and relay the envelope.
type Dispatcher struct {
	rpc      RPCCaller
	log      *slog.Logger
	identity IdentitySource
}

// NewRaw builds a dispatcher over principal.Resolver.Identity's cached bytes.
// identity may be nil for fully-public route sets.
func NewRaw(caller RPCCaller, log *slog.Logger, identity IdentitySource) *Dispatcher {
	return &Dispatcher{rpc: caller, log: log, identity: identity}
}

// New builds a dispatcher over a map-valued IdentityResolver, the type the
// multipart binaries share; it re-marshals the payload on every request, so
// the gateway's own dispatchers use NewRaw. identity may be nil.
func New(caller RPCCaller, log *slog.Logger, identity IdentityResolver) *Dispatcher {
	if identity == nil {
		return NewRaw(caller, log, nil)
	}
	return NewRaw(caller, log, func(r *http.Request) (Identity, bool, error) {
		payload, ok, err := identity(r)
		if err != nil || !ok {
			return Identity{}, false, err
		}
		raw, err := json.Marshal(payload)
		return Identity{Payload: raw, SoleWorkspaceID: soleWorkspaceID(payload)}, true, err
	})
}

// Register wires every spec onto the mux (method-qualified pattern).
func (d *Dispatcher) Register(mux *http.ServeMux, specs []RouteSpec) {
	for _, s := range specs {
		mux.HandleFunc(s.Method+" "+s.Pattern, d.Handler(s))
	}
}

// Handler builds the http handler for one RouteSpec (ServeMux path params).
func (d *Dispatcher) Handler(spec RouteSpec) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		pp := map[string]string{}
		if spec.IDParam != "" {
			pp[spec.IDParam] = r.PathValue(spec.IDParam)
		}
		for _, p := range spec.Path {
			pp[p] = r.PathValue(p)
		}
		d.serve(w, r, spec, pp)
	}
}

// serve builds the RPC request from a RouteSpec + resolved path params and calls it.
func (d *Dispatcher) serve(w http.ResponseWriter, r *http.Request, spec RouteSpec, pp map[string]string) {
	data := map[string]any{}
	if spec.Entity != "" {
		data["entity"] = spec.Entity
	}
	if spec.Action != "" {
		data["action"] = spec.Action
	}

	var id Identity
	if spec.Auth != AuthNone {
		var ok bool
		var err error
		if d.identity != nil {
			id, ok, err = d.identity(r)
		}
		switch {
		case err != nil:
			// Identity backend unavailable (shed/disconnected/timeout): this is
			// a 503, not a 401 — treating it as "not authenticated" makes
			// clients drop valid sessions and retry-storm during overload.
			httplog.From(r.Context()).Error("identity resolution unavailable", "err", err)
			w.Header().Set("Retry-After", "1")
			writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
			return
		case ok:
			data["identity"] = id.Payload
		case spec.Auth == AuthRequired:
			writeDetail(w, http.StatusUnauthorized, "Not authenticated")
			return
		}
	}

	if spec.IDParam != "" {
		data["id"] = pp[spec.IDParam]
	}
	for _, p := range spec.Path {
		data[p] = pp[p]
	}
	if spec.AllQuery || len(spec.Query) > 0 {
		values := r.URL.Query()
		q := map[string]any{}
		if spec.AllQuery {
			for k, vs := range values {
				if len(vs) > 0 {
					q[k] = vs
				}
			}
		} else {
			for _, k := range spec.Query {
				if vs, ok := values[k]; ok && len(vs) > 0 {
					q[k] = vs
				}
			}
		}
		// A credential pinned to exactly ONE workspace already names its scope,
		// but domain reads fail closed without workspace_id
		// (shared/services/workspace_scope.py) — so an API-key client had to
		// repeat in the query string what its own token already says, and got a
		// 400 on every read until it did. Fill it in from the identity instead.
		// An explicitly sent value always wins, and an ambiguous credential
		// (two or more workspaces) is left alone: guessing would silently scope
		// the read to the wrong tenant, so the fail-closed 400 stands.
		if _, sent := q["workspace_id"]; !sent && id.SoleWorkspaceID > 0 && (spec.AllQuery || slices.Contains(spec.Query, "workspace_id")) {
			q["workspace_id"] = []string{strconv.FormatInt(id.SoleWorkspaceID, 10)}
		}
		if len(q) > 0 {
			data["query"] = q
		}
	}
	if spec.Body {
		payload, ok := readPayload(w, r)
		if !ok {
			return
		}
		data["payload"] = payload
	}

	// The trusted origin of this request, under the exact keys every worker's
	// record_audit call already reads. Until this was here, the identity
	// handlers were the only ones stamping it (setClientMeta), so every audit
	// row written from app-service or tournament-service -- the whole CRUD
	// engine, every registration mutation -- stored NULL for both columns and
	// the journal could not say where a change came from.
	//
	// TOP LEVEL, never inside data["payload"]: the request body lands there, so
	// a caller cannot forge the recorded origin of its own mutation. Set after
	// the body is decoded for the same reason.
	//
	// Unconditional rather than write-only: it is two short strings on an AMQP
	// message, and no route has to remember to opt in. Cache keys are the URL
	// (respcache.cacheKey), not the RPC body, so this cannot fragment the
	// shared response cache.
	data["ip_address"] = clientip.From(r)
	data["user_agent"] = clientip.UserAgent(r)

	raw, _ := json.Marshal(data)
	d.call(w, r, spec.Queue, raw, spec.successStatus(), spec.callTimeout())
}

// readPayload returns the request's JSON body verbatim for data["payload"],
// or writes the error response itself and returns false.
//
// The bytes are relayed as-is instead of decoded into map[string]any and
// re-marshaled: that round trip rounded every integer past 2^53 through
// float64. The accepted shapes are unchanged — an object, a literal null, or
// an empty body (sent as {}) — but nothing may follow the value: a lone Decode
// accepted `{"name":"X"} garbage` and ran the mutation. Over maxBody is a 413;
// the old LimitReader truncated silently, so an oversized object failed as
// malformed (400) and an oversized tail after a small object was never read.
func readPayload(w http.ResponseWriter, r *http.Request) (json.RawMessage, bool) {
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxBody))
	var body json.RawMessage
	err := dec.Decode(&body)
	switch {
	case errors.Is(err, io.EOF):
		return json.RawMessage(`{}`), true
	case err == nil && (body[0] == '{' || string(body) == "null"):
		if _, err = dec.Token(); errors.Is(err, io.EOF) { // only whitespace left
			return body, true
		}
	}
	var tooLarge *http.MaxBytesError
	if errors.As(err, &tooLarge) {
		writeDetail(w, http.StatusRequestEntityTooLarge, "Request body too large")
	} else {
		writeDetail(w, http.StatusBadRequest, "Invalid request body")
	}
	return nil, false
}

// Subtree returns an http.Handler that matches an ORDERED list of RouteSpecs by
// method + path template (first match wins, like FastAPI) — for subtrees whose
// patterns are ambiguous under the stdlib ServeMux (e.g. /{id}/x vs /literal/{y}).
// Register it on the mux at the subtree prefix, e.g. mux.Handle("/api/v1/x/", h).
func (d *Dispatcher) Subtree(routes []RouteSpec) http.Handler {
	return &subtree{d: d, routes: routes}
}

type subtree struct {
	d      *Dispatcher
	routes []RouteSpec
}

func (s *subtree) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	segs := splitPath(r.URL.Path)
	for _, spec := range s.routes {
		if spec.Method != r.Method {
			continue
		}
		if pp, ok := matchPattern(spec.Pattern, segs); ok {
			s.d.serve(w, r, spec, pp)
			return
		}
	}
	writeDetail(w, http.StatusNotFound, "Not Found")
}

func splitPath(path string) []string {
	out := []string{}
	for _, s := range strings.Split(path, "/") {
		if s != "" {
			out = append(out, s)
		}
	}
	return out
}

// matchPattern matches a ServeMux-style pattern ("/a/{id}/b") against path
// segments, capturing {param} values. Supports a trailing "{name...}" wildcard.
func matchPattern(pattern string, segs []string) (map[string]string, bool) {
	psegs := splitPath(pattern)
	pp := map[string]string{}
	for i, ps := range psegs {
		if len(ps) > 3 && ps[0] == '{' && ps[len(ps)-4:] == "...}" {
			pp[ps[1:len(ps)-4]] = strings.Join(segs[i:], "/")
			return pp, true
		}
		if i >= len(segs) {
			return nil, false
		}
		if len(ps) >= 2 && ps[0] == '{' && ps[len(ps)-1] == '}' {
			pp[ps[1:len(ps)-1]] = segs[i]
			continue
		}
		if ps != segs[i] {
			return nil, false
		}
	}
	if len(psegs) != len(segs) {
		return nil, false
	}
	return pp, true
}

// call performs the RPC and maps the reply envelope to an HTTP response.
func (d *Dispatcher) call(w http.ResponseWriter, r *http.Request, queue string, body []byte, success int, timeout time.Duration) {
	ctx, cancel := context.WithTimeout(r.Context(), timeout)
	defer cancel()

	log := httplog.From(r.Context())
	raw, err := d.rpc.Call(ctx, queue, body)
	if err != nil {
		if rpc.IsUnavailable(err) {
			log.Error("rpc unavailable", "queue", queue, "err", err)
			w.Header().Set("Retry-After", "1")
			writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
			return
		}
		// The caller disconnected before the RPC completed: r.Context() was
		// canceled and propagated through the timeout ctx as context.Canceled
		// (our own per-route deadline surfaces as context.DeadlineExceeded instead).
		// This is not a server fault — the client is gone, so no response can
		// be delivered and there is nothing to fix. Log at info (stdout/Loki
		// only, never a Sentry Issue) and skip the 504.
		if errors.Is(err, context.Canceled) {
			log.Info("rpc canceled by client", "queue", queue)
			return
		}
		log.Error("rpc failed", "queue", queue, "err", err)
		writeDetail(w, http.StatusGatewayTimeout, "service timeout")
		return
	}

	var env rpc.Envelope
	if err := json.Unmarshal(raw, &env); err != nil {
		log.Error("invalid rpc envelope", "queue", queue, "err", err)
		writeDetail(w, http.StatusBadGateway, "invalid service response")
		return
	}
	if !env.OK {
		apierr.WriteEnvelopeError(w, env.Error)
		return
	}
	apierr.WriteOK(w, success, env)
}

// writeDetail emits the gateway's error body (see internal/apierr) for the
// dispatcher's OWN failures. Upstream envelope errors go through
// apierr.WriteEnvelopeError instead, so their code, structured details and
// Retry-After survive.
func writeDetail(w http.ResponseWriter, status int, detail string, code ...string) {
	c := ""
	if len(code) > 0 {
		c = code[0]
	}
	apierr.WriteError(w, status, detail, c, nil)
}

// soleWorkspaceID returns the id of the ONLY workspace an identity payload
// carries, and 0 for anything else — zero workspaces, or two or more
// (ambiguous). An API key is always pinned to exactly one workspace, so this is
// the common case for machine clients; a session user who belongs to one
// workspace gets the same convenience the frontend already gives itself by
// injecting workspace_id client-side.
//
// It only ever names a workspace the credential already holds, so it cannot
// widen authority: the worker still runs its own permission check for that
// workspace.
func soleWorkspaceID(payload map[string]any) int64 {
	list, ok := payload["workspaces"].([]any)
	if !ok || len(list) != 1 {
		return 0
	}
	ws, ok := list[0].(map[string]any)
	if !ok {
		return 0
	}
	// encoding/json decodes numbers as float64; ids have historically also
	// arrived stringly-typed, so accept both (mirrors principal.asInt64).
	switch v := ws["workspace_id"].(type) {
	case float64:
		return max(int64(v), 0)
	case string:
		n, _ := strconv.ParseInt(v, 10, 64)
		return max(n, 0)
	}
	return 0
}
