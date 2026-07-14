// Package principal resolves the authenticated identity for a request by calling
// identity-svc's rpc.identity.validate_token (the gateway is the only auth
// authority), caching the result briefly. The resolved RBAC payload is injected
// into downstream RPC calls; headless workers rehydrate it without a DB hit.
package principal

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
)

const (
	validateQueue   = "rpc.identity.validate_token"
	validateTimeout = 5 * time.Second
	cacheTTL        = 30 * time.Second
	maxCacheEntries = 4096
)

// RPCCaller is the subset of rpc.Client the resolver needs.
type RPCCaller interface {
	Call(ctx context.Context, queue string, body []byte) ([]byte, error)
}

type entry struct {
	payload map[string]any
	ok      bool
	exp     time.Time
}

// Resolver validates bearer tokens via identity-svc and caches the RBAC payload.
type Resolver struct {
	rpc   RPCCaller
	now   func() time.Time
	mu    sync.Mutex
	cache map[string]entry
}

// New builds a resolver over the shared RPC client.
func New(caller RPCCaller) *Resolver {
	return &Resolver{rpc: caller, now: time.Now, cache: make(map[string]entry)}
}

// Resolve implements edge.IdentityResolver: bearer token -> RBAC payload.
//
// A non-nil error means the identity backend was unavailable (the RPC
// bulkhead shed the call, the client was disconnected, or the call timed
// out) — the caller should respond 503, not 401. Anonymous requests (no
// bearer token) never produce an error.
func (r *Resolver) Resolve(req *http.Request) (map[string]any, bool, error) {
	token := bearer(req)
	if token == "" {
		return nil, false, nil
	}

	now := r.now()
	r.mu.Lock()
	if e, ok := r.cache[token]; ok && now.Before(e.exp) {
		r.mu.Unlock()
		return e.payload, e.ok, nil
	}
	r.mu.Unlock()

	body, _ := json.Marshal(map[string]any{"token": token})
	ctx, cancel := context.WithTimeout(req.Context(), validateTimeout)
	defer cancel()

	raw, err := r.rpc.Call(ctx, validateQueue, body)
	if err != nil {
		// Transport failure: the token was never actually judged by identity-svc,
		// so we must not cache ok=false here — that would keep a valid session
		// "logged out" for cacheTTL after a single hiccup (shed/disconnect/timeout).
		return nil, false, err
	}

	var payload map[string]any
	ok := false
	var env rpc.Envelope
	if json.Unmarshal(raw, &env) == nil && env.OK && len(env.Data) > 0 {
		if json.Unmarshal(env.Data, &payload) == nil {
			ok = true
		}
	}

	r.store(token, entry{payload: payload, ok: ok, exp: now.Add(cacheTTL)})
	return payload, ok, nil
}

func (r *Resolver) store(token string, e entry) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.cache) >= maxCacheEntries {
		now := r.now()
		for k, v := range r.cache {
			if !now.Before(v.exp) {
				delete(r.cache, k)
			}
		}
		if len(r.cache) >= maxCacheEntries {
			r.cache = make(map[string]entry) // bound memory: drop the cache wholesale
		}
	}
	r.cache[token] = e
}

func bearer(r *http.Request) string {
	scheme, creds, found := strings.Cut(r.Header.Get("Authorization"), " ")
	if found && strings.EqualFold(scheme, "bearer") {
		return strings.TrimSpace(creds)
	}
	return ""
}
