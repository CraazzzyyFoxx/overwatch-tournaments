// Package principal resolves the authenticated identity for a request by calling
// identity-svc's rpc.identity.validate_token (the gateway is the only auth
// authority), caching the result briefly. The resolved RBAC payload is injected
// into downstream RPC calls; headless workers rehydrate it without a DB hit.
package principal

import (
	"container/list"
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"time"

	"golang.org/x/sync/singleflight"

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

// cacheItem is what the LRU list elements hold: the entry plus its own token,
// so eviction of the list tail can delete the map key without a reverse index.
type cacheItem struct {
	token string
	entry
}

// Resolver validates bearer tokens via identity-svc and caches the RBAC payload.
//
// The cache is a TTL'd LRU: hits refresh recency, and when it is full the
// least-recently-used token is evicted — a flood of one-off tokens can no
// longer wipe every active session's entry at once (the old behavior dropped
// the whole map on overflow). Concurrent misses for the same token are
// collapsed into a single validate_token RPC via singleflight.
type Resolver struct {
	rpc    RPCCaller
	now    func() time.Time
	flight singleflight.Group
	mu     sync.Mutex
	cache  map[string]*list.Element // token -> element in order (holds *cacheItem)
	order  *list.List               // most recently used at the front
}

// New builds a resolver over the shared RPC client.
func New(caller RPCCaller) *Resolver {
	return &Resolver{rpc: caller, now: time.Now, cache: make(map[string]*list.Element), order: list.New()}
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

	if e, ok := r.lookup(token); ok {
		return e.payload, e.ok, nil
	}

	// Collapse concurrent misses for the same token into one RPC: a burst of
	// requests from one session (page load fans out N API calls) used to fire
	// N identical validate_token calls until the first reply landed in the
	// cache. DoChan (not Do) so each waiter still honors its own request
	// context instead of blocking past its client's disconnect.
	ch := r.flight.DoChan(token, func() (any, error) {
		return r.validate(req.Context(), token)
	})
	select {
	case res := <-ch:
		if res.Err != nil {
			return nil, false, res.Err
		}
		e := res.Val.(entry)
		return e.payload, e.ok, nil
	case <-req.Context().Done():
		return nil, false, req.Context().Err()
	}
}

// validate performs the validate_token RPC and stores the judged result. It
// runs at most once per token per flight; the result is shared by every
// concurrent waiter, so it detaches from the winning request's cancellation
// (one impatient client must not fail validation for the others) while keeping
// its context values (trace/correlation) and the validateTimeout deadline —
// which still drives the AMQP TTL via rpc/deadline.go.
func (r *Resolver) validate(ctx context.Context, token string) (entry, error) {
	body, _ := json.Marshal(map[string]any{"token": token})
	ctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), validateTimeout)
	defer cancel()

	raw, err := r.rpc.Call(ctx, validateQueue, body)
	if err != nil {
		// Transport failure: the token was never actually judged by identity-svc,
		// so we must not cache ok=false here — that would keep a valid session
		// "logged out" for cacheTTL after a single hiccup (shed/disconnect/timeout).
		return entry{}, err
	}

	var payload map[string]any
	ok := false
	var env rpc.Envelope
	if json.Unmarshal(raw, &env) == nil && env.OK && len(env.Data) > 0 {
		if json.Unmarshal(env.Data, &payload) == nil {
			ok = true
		}
	}

	e := entry{payload: payload, ok: ok, exp: r.now().Add(cacheTTL)}
	r.store(token, e)
	return e, nil
}

// lookup returns the cached entry for token if present and unexpired,
// refreshing its LRU recency. Expired entries are removed eagerly.
func (r *Resolver) lookup(token string) (entry, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	el, ok := r.cache[token]
	if !ok {
		return entry{}, false
	}
	it := el.Value.(*cacheItem)
	if !r.now().Before(it.exp) {
		delete(r.cache, token)
		r.order.Remove(el)
		return entry{}, false
	}
	r.order.MoveToFront(el)
	return it.entry, true
}

func (r *Resolver) store(token string, e entry) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if el, ok := r.cache[token]; ok {
		el.Value.(*cacheItem).entry = e
		r.order.MoveToFront(el)
		return
	}
	// Bound memory: evict the least-recently-used entry instead of dropping
	// the cache wholesale, so active sessions survive a flood of one-offs.
	for len(r.cache) >= maxCacheEntries {
		back := r.order.Back()
		if back == nil {
			break
		}
		it := back.Value.(*cacheItem)
		delete(r.cache, it.token)
		r.order.Remove(back)
	}
	r.cache[token] = r.order.PushFront(&cacheItem{token: token, entry: e})
}

func bearer(r *http.Request) string {
	scheme, creds, found := strings.Cut(r.Header.Get("Authorization"), " ")
	if found && strings.EqualFold(scheme, "bearer") {
		return strings.TrimSpace(creds)
	}
	return ""
}
