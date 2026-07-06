package edge

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
)

const (
	// rpcTimeout matches the old Kong edge allowance (up to 120s). Some app-service
	// reads (e.g. /users/{id}/compare, hero stats on a cold cache) legitimately run
	// ~20-30s; a tighter cap would turn slow-but-successful responses into 504s that
	// the HTTP edge returned as 200/500. The gateway server has no write timeout for
	// the same reason (long WS + long balancer requests).
	rpcTimeout = 120 * time.Second
	maxBody    = 12 << 20 // 12 MiB request-body cap before buffering into the RPC message
)

// RPCCaller is the subset of rpc.Client the dispatcher needs (eases testing).
type RPCCaller interface {
	Call(ctx context.Context, queue string, body []byte) ([]byte, error)
}

// IdentityResolver returns the validated RBAC identity payload for a request
// (user_id/is_superuser/roles/permissions/workspaces), or ok=false if absent.
type IdentityResolver func(r *http.Request) (map[string]any, bool)

// Dispatcher turns RouteSpecs into http handlers that call RPC and relay the envelope.
type Dispatcher struct {
	rpc      RPCCaller
	log      *slog.Logger
	identity IdentityResolver
}

// New builds a dispatcher. identity may be nil for fully-public route sets.
func New(caller RPCCaller, log *slog.Logger, identity IdentityResolver) *Dispatcher {
	return &Dispatcher{rpc: caller, log: log, identity: identity}
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

	if spec.Auth != AuthNone {
		id, ok := d.resolveIdentity(r)
		switch {
		case ok:
			data["identity"] = id
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
		if len(q) > 0 {
			data["query"] = q
		}
	}
	if spec.Body {
		body := map[string]any{}
		if err := json.NewDecoder(io.LimitReader(r.Body, maxBody)).Decode(&body); err != nil && !errors.Is(err, io.EOF) {
			writeDetail(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		data["payload"] = body
	}

	raw, _ := json.Marshal(data)
	d.call(w, r, spec.Queue, raw, spec.successStatus())
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

func (d *Dispatcher) resolveIdentity(r *http.Request) (map[string]any, bool) {
	if d.identity == nil {
		return nil, false
	}
	return d.identity(r)
}

// call performs the RPC and maps the reply envelope to an HTTP response.
func (d *Dispatcher) call(w http.ResponseWriter, r *http.Request, queue string, body []byte, success int) {
	ctx, cancel := context.WithTimeout(r.Context(), rpcTimeout)
	defer cancel()

	log := httplog.From(r.Context())
	raw, err := d.rpc.Call(ctx, queue, body)
	if err != nil {
		if errors.Is(err, rpc.ErrNotConnected) || errors.Is(err, rpc.ErrDisconnected) {
			log.Error("rpc unavailable", "queue", queue, "err", err)
			writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
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
		status := http.StatusInternalServerError
		msg := "internal error"
		if env.Error != nil {
			status = rpc.StatusForCode(env.Error.Code)
			msg = env.Error.Message
		}
		writeDetail(w, status, msg)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(success)
	// Relay the envelope data as-is, including a literal JSON `null` for endpoints
	// whose response_model is `X | None` and resolved to None. Suppressing the
	// body here produced a 200 with content-length 0, which is not valid JSON and
	// made callers' response.json() throw "Unexpected end of JSON input". 204
	// genuinely carries no body and is still skipped.
	if success != http.StatusNoContent && len(env.Data) > 0 {
		_, _ = w.Write(env.Data)
	}
}

// writeDetail emits a FastAPI-style error body: {"detail": "..."}.
func writeDetail(w http.ResponseWriter, status int, detail string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"detail": detail})
}
