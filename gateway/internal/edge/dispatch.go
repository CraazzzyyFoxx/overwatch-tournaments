package edge

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
)

const (
	rpcTimeout = 15 * time.Second
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

// Handler builds the http handler for one RouteSpec.
func (d *Dispatcher) Handler(spec RouteSpec) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
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
			data["id"] = r.PathValue(spec.IDParam)
		}
		for _, p := range spec.Path {
			data[p] = r.PathValue(p)
		}
		if spec.AllQuery || len(spec.Query) > 0 {
			values := r.URL.Query()
			q := map[string]any{}
			if spec.AllQuery {
				// Forward every query param (pagination/filter routes reconstruct the
				// route's query-params model on the service side).
				for k, vs := range values {
					if len(vs) > 0 {
						q[k] = vs
					}
				}
			} else {
				for _, k := range spec.Query {
					// Forward all values as a list so repeated params (e.g. ?entities=a&entities=b)
					// survive; the service side reads scalar-or-list uniformly.
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

	raw, err := d.rpc.Call(ctx, queue, body)
	if err != nil {
		if errors.Is(err, rpc.ErrNotConnected) || errors.Is(err, rpc.ErrDisconnected) {
			d.log.Error("rpc unavailable", "queue", queue, "err", err)
			writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
			return
		}
		d.log.Error("rpc failed", "queue", queue, "err", err)
		writeDetail(w, http.StatusGatewayTimeout, "service timeout")
		return
	}

	var env rpc.Envelope
	if err := json.Unmarshal(raw, &env); err != nil {
		d.log.Error("invalid rpc envelope", "queue", queue, "err", err)
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
	if success != http.StatusNoContent && len(env.Data) > 0 && string(env.Data) != "null" {
		_, _ = w.Write(env.Data)
	}
}

// writeDetail emits a FastAPI-style error body: {"detail": "..."}.
func writeDetail(w http.ResponseWriter, status int, detail string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"detail": detail})
}
