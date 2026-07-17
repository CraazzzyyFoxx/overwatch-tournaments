// Package respcache is a small in-memory response cache for ANONYMOUS public
// tournament reads, with event-driven invalidation off the worker's realtime
// bus.
//
// Why anonymous-only: tournament visibility is viewer-dependent (hidden
// tournaments, preview allowlists, workspace scoping — the backend gates every
// read with assert_tournament_viewable BEFORE its own cache). A URL-keyed
// cache shared across viewers would leak hidden tournaments. Anonymous viewers
// are one equivalence class — they all see exactly the public surface — so for
// requests WITHOUT an Authorization header the same URL always means the same
// response. Authenticated requests bypass the cache entirely, in both
// directions. This mirrors ratelimit.WrapAnon's bearer-presence convention.
//
// Why per-tournament invalidation works without new backend code: every
// public-data-changing write in tournament-service lands (via the
// transactional outbox) on the worker's tournament_changed consumer, which —
// after invalidating the backend Redis cache — publishes a realtime event on
// the Redis channel "realtime:tournament:{id}:bracket". The gateway already
// PSUBSCRIBEs to realtime:* for WebSocket fan-out (internal/events); this
// cache is simply a second consumer of that same worker-emitted signal:
// events.Fanout(hub, cache). Draft events ("tournament:{id}:draft") change
// team compositions mid-draft, so they invalidate too. The balancer topic is
// deliberately ignored — it carries ephemeral presence heartbeats that would
// otherwise keep the cache permanently cold for any tournament with an open
// balancer session.
//
// The TTL is a staleness backstop, not the primary mechanism: some writes
// (e.g. public registration create → participants_count) do not emit
// tournament_changed at all — the backend's own 300s read cache already
// accepts that staleness; the short gateway TTL adds a bounded sliver on top.
//
// Redis pub/sub is fire-and-forget: a gateway that is briefly disconnected
// misses invalidations. The TTL bounds that damage window too.
//
// Bounds: entries are LRU-evicted past maxEntries, and bodies larger than
// maxBodyBytes are served but never stored. The key space is derived from
// request URLs, which an anonymous client controls (arbitrary query strings),
// so the LRU bound is what keeps a query-string flood from growing the map —
// the same posture as principal.Resolver's token LRU.
//
// Concurrent misses for one key are collapsed via singleflight so a cold or
// just-invalidated hot key costs ONE upstream RPC, not one per waiting client.
// The shared fetch runs on a context detached from the initiating client
// (context.WithoutCancel): one impatient client closing its tab must not fail
// the fetch for everyone behind it; the edge dispatcher's own per-route RPC
// timeout still bounds it.
package respcache

import (
	"container/list"
	"context"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/sync/singleflight"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

const (
	// maxEntries bounds the LRU. Anonymous clients control the key space
	// (query strings), so the cache must never grow without bound.
	maxEntries = 4096
	// maxBodyBytes: responses larger than this are proxied through but not
	// stored (the RPC reply is already fully in memory, so recording adds no
	// extra buffering — only storing is capped).
	maxBodyBytes = 1 << 20
)

// Extractor resolves the invalidation scope for a request: a positive
// tournament id (event-invalidated), 0 with ok=true for a deliberate TTL-only
// entry (see TTLOnly), or ok=false to skip caching — a tournament-scoped
// route whose id is missing must not produce an entry Invalidate cannot
// reach.
type Extractor func(r *http.Request) (int64, bool)

// FromPathValue extracts the tournament id from a ServeMux path parameter,
// e.g. "id" in "/api/v1/tournaments/{id}".
func FromPathValue(name string) Extractor {
	return func(r *http.Request) (int64, bool) {
		return parseID(r.PathValue(name))
	}
}

// FromQuery extracts the tournament id from a query parameter, e.g.
// "tournament_id" in "/api/v1/encounters?tournament_id=72".
func FromQuery(name string) Extractor {
	return func(r *http.Request) (int64, bool) {
		return parseID(r.URL.Query().Get(name))
	}
}

func parseID(raw string) (int64, bool) {
	id, err := strconv.ParseInt(raw, 10, 64)
	return id, err == nil && id > 0
}

// TTLOnly caches a route with no tournament invalidation handle: the entry is
// stored under the reserved id 0, which no realtime topic can ever name
// (parseID rejects non-positive ids), so it expires strictly by TTL. For
// routes whose data has no single owning tournament (home-page aggregates,
// user profiles) a bounded TTL staleness is the accepted trade — the backend
// and the Next Data Cache already accept 300s for the same reads; the gateway
// TTL is far tighter.
func TTLOnly() Extractor {
	return func(*http.Request) (int64, bool) { return 0, true }
}

// QueryEquals is an AuthedReadUnless predicate: true when the named query
// parameter equals value.
func QueryEquals(name, value string) func(r *http.Request) bool {
	return func(r *http.Request) bool {
		return r.URL.Query().Get(name) == value
	}
}

type entry struct {
	key          string
	tournamentID int64
	status       int
	header       http.Header
	body         []byte
	exp          time.Time
}

// Cache is the bounded LRU store plus the singleflight herd-collapse. A nil
// *Cache is valid and inert (Wrap returns next unchanged, Broadcast is a
// no-op), so callers can wire it unconditionally and disable via config.
type Cache struct {
	ttl    time.Duration
	max    int
	log    *slog.Logger
	now    func() time.Time
	flight singleflight.Group

	mu   sync.Mutex
	keys map[string]*list.Element // key -> element (holds *entry)
	lru  *list.List               // front = most recently used
	byID map[int64]map[string]struct{}
}

// New returns a Cache with the given staleness backstop, or nil (disabled)
// when ttl <= 0.
func New(ttl time.Duration, log *slog.Logger) *Cache {
	if ttl <= 0 {
		return nil
	}
	return newCache(ttl, maxEntries, log)
}

func newCache(ttl time.Duration, max int, log *slog.Logger) *Cache {
	return &Cache{
		ttl:  ttl,
		max:  max,
		log:  log,
		now:  time.Now,
		keys: make(map[string]*list.Element),
		lru:  list.New(),
		byID: make(map[int64]map[string]struct{}),
	}
}

// HandlerBuilder is the subset of edge.Dispatcher RegisterCached needs.
type HandlerBuilder interface {
	Handler(spec edge.RouteSpec) http.HandlerFunc
}

// Rule is one route's caching contract.
type Rule struct {
	// Extract resolves the invalidation scope (see Extractor).
	Extract Extractor
	// AuthedRead lets bearer-carrying requests READ entries — which are only
	// ever WRITTEN by anonymous requests — instead of bypassing the cache
	// entirely. Authenticated requests still never populate an entry and
	// never join a singleflight: on a miss they go upstream with their own
	// identity (an allowlisted viewer may see MORE than anonymous — a hidden
	// tournament's preview — so an anonymous 404 or in-flight result must
	// never become their answer).
	//
	// Safe ONLY when both hold for the route, verified against the backend
	// handler:
	//   1. an anonymous 200 proves the resource is publicly visible (the
	//      handler gates with assert_tournament_viewable before reading);
	//   2. the body after the gate is viewer-agnostic (the backend computes
	//      or caches it with no viewer in the key).
	// Holds for rpc.tournament.get_tournament / get_stages / get_standings /
	// list_teams (viewer is used exclusively in the gate). Holds for
	// list_encounters EXCEPT scope=my_team (see AuthedReadUnless). Does NOT
	// hold for encounters_overview, whose body carries a per-viewer
	// my_team_count.
	AuthedRead bool
	// AuthedReadUnless, when non-nil, revokes AuthedRead for requests it
	// matches: such requests bypass the cache entirely, like any authed
	// request on a non-AuthedRead route. Used for query shapes whose body IS
	// viewer-dependent on an otherwise viewer-agnostic route — e.g.
	// scope=my_team on the encounters list, where the anonymous entry is a
	// hardcoded-empty result (the backend filters by sa.false() without a
	// viewer) and must never be served to a logged-in player. Ignored for
	// anonymous requests, which may safely cache those shapes.
	AuthedReadUnless func(r *http.Request) bool
}

// RegisterCached wires specs onto the mux like edge.Dispatcher.Register, but
// wraps every GET route that has a Rule in rules with the cache. With a nil
// cache (disabled) it degrades to plain registration.
func RegisterCached(mux *http.ServeMux, b HandlerBuilder, specs []edge.RouteSpec, rules map[string]Rule, c *Cache) {
	for _, s := range specs {
		var h http.Handler = b.Handler(s)
		if rule, ok := rules[s.Pattern]; ok && s.Method == http.MethodGet {
			h = c.Wrap(h, rule)
		}
		mux.Handle(s.Method+" "+s.Pattern, h)
	}
}

// Wrap returns next guarded by the cache. Anonymous GETs whose extractor
// resolves a scope are cached (200s small enough to store); authenticated
// requests bypass entirely unless rule.AuthedRead grants them read-only
// access. Everything else passes through untouched.
func (c *Cache) Wrap(next http.Handler, rule Rule) http.Handler {
	if c == nil {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Bearer present -> viewer-dependent visibility; without an
		// applicable AuthedRead grant, never read or write the shared cache.
		authed := r.Header.Get("Authorization") != ""
		allowAuthedRead := rule.AuthedRead &&
			(rule.AuthedReadUnless == nil || !rule.AuthedReadUnless(r))
		if r.Method != http.MethodGet || (authed && !allowAuthedRead) {
			next.ServeHTTP(w, r)
			return
		}
		tid, ok := rule.Extract(r)
		if !ok {
			next.ServeHTTP(w, r)
			return
		}
		key := cacheKey(r)

		if e := c.get(key); e != nil {
			writeEntry(w, e, "HIT")
			return
		}

		if authed {
			// Read-only grant: a miss goes upstream with the caller's own
			// identity, populates nothing, and joins no flight (see
			// Rule.AuthedRead).
			next.ServeHTTP(w, r)
			return
		}

		ch := c.flight.DoChan(key, func() (any, error) {
			rec := &recorder{header: make(http.Header), status: http.StatusOK}
			// Detach from the initiating client's lifetime; the edge
			// dispatcher's per-route RPC timeout still bounds the call.
			next.ServeHTTP(rec, r.Clone(context.WithoutCancel(r.Context())))
			e := &entry{
				key:          key,
				tournamentID: tid,
				status:       rec.status,
				header:       rec.header,
				body:         rec.body,
				exp:          c.now().Add(c.ttl),
			}
			// Only cache clean successes: errors and empty-but-odd statuses
			// must stay live. (Anonymous 404s for hidden tournaments are
			// deliberately not cached either — rare, and correctness-critical
			// around visibility flips.)
			if e.status == http.StatusOK && len(e.body) <= maxBodyBytes {
				c.store(e)
			}
			return e, nil
		})

		select {
		case res := <-ch:
			if res.Err != nil {
				// Defensive: the flight fn never returns an error today.
				next.ServeHTTP(w, r)
				return
			}
			label := "MISS"
			if res.Shared {
				label = "COALESCED"
			}
			writeEntry(w, res.Val.(*entry), label)
		case <-r.Context().Done():
			// Client gone; the shared flight keeps running for the others.
		}
	})
}

// Invalidate drops every cached response for the tournament, returning how
// many entries were removed.
func (c *Cache) Invalidate(tournamentID int64) int {
	if c == nil {
		return 0
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	keys := c.byID[tournamentID]
	// removeLocked deletes from this same set as we range (legal in Go), so
	// the count must be taken before the loop empties it.
	n := len(keys)
	for k := range keys {
		if el, ok := c.keys[k]; ok {
			c.removeLocked(el)
		}
	}
	return n
}

// Broadcast implements the events.Broadcaster shape so the cache can ride the
// existing realtime subscription (events.Fanout(hub, cache)). Any message on a
// tournament's bracket or draft topic — the worker publishes
// "tournament.updated" there from its tournament_changed consumer, and live
// score/draft events ride the same topics — invalidates that tournament.
// Over-invalidation is a cache miss; under-invalidation is a stale page, so
// unknown payloads err on the side of dropping.
func (c *Cache) Broadcast(topic string, _ []byte) {
	if c == nil {
		return
	}
	rest, ok := strings.CutPrefix(topic, "tournament:")
	if !ok {
		return
	}
	rawID, sub, ok := strings.Cut(rest, ":")
	if !ok || (sub != "bracket" && sub != "draft") {
		return
	}
	id, ok := parseID(rawID)
	if !ok {
		return
	}
	if n := c.Invalidate(id); n > 0 {
		c.log.Debug("response cache invalidated", "tournament_id", id, "entries", n, "topic", topic)
	}
}

// cacheKey canonicalizes the URL: query params are re-encoded sorted by key,
// so ?a=1&b=2 and ?b=2&a=1 share one entry. workspace_id rides as a query
// param (never a header), so workspace-scoped variants are keyed apart
// automatically.
func cacheKey(r *http.Request) string {
	return r.URL.Path + "?" + r.URL.Query().Encode()
}

func (c *Cache) get(key string) *entry {
	c.mu.Lock()
	defer c.mu.Unlock()
	el, ok := c.keys[key]
	if !ok {
		return nil
	}
	e := el.Value.(*entry)
	if !c.now().Before(e.exp) {
		c.removeLocked(el)
		return nil
	}
	c.lru.MoveToFront(el)
	return e
}

func (c *Cache) store(e *entry) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if el, ok := c.keys[e.key]; ok {
		c.removeLocked(el)
	}
	for len(c.keys) >= c.max {
		back := c.lru.Back()
		if back == nil {
			break
		}
		c.removeLocked(back)
	}
	el := c.lru.PushFront(e)
	c.keys[e.key] = el
	ids, ok := c.byID[e.tournamentID]
	if !ok {
		ids = make(map[string]struct{})
		c.byID[e.tournamentID] = ids
	}
	ids[e.key] = struct{}{}
}

func (c *Cache) removeLocked(el *list.Element) {
	e := el.Value.(*entry)
	delete(c.keys, e.key)
	c.lru.Remove(el)
	if ids, ok := c.byID[e.tournamentID]; ok {
		delete(ids, e.key)
		if len(ids) == 0 {
			delete(c.byID, e.tournamentID)
		}
	}
}

// writeEntry replays a recorded response. Entries are immutable after store,
// so the shared header/body are safe to serve concurrently.
func writeEntry(w http.ResponseWriter, e *entry, label string) {
	for k, vv := range e.header {
		for _, v := range vv {
			w.Header().Add(k, v)
		}
	}
	w.Header().Set("X-Cache", label)
	w.WriteHeader(e.status)
	_, _ = w.Write(e.body)
}

// recorder buffers one response. The edge dispatcher already holds the full
// RPC reply in memory before writing, so this adds no extra buffering class.
type recorder struct {
	header http.Header
	status int
	body   []byte
}

func (r *recorder) Header() http.Header { return r.header }

func (r *recorder) WriteHeader(code int) { r.status = code }

func (r *recorder) Write(b []byte) (int, error) {
	r.body = append(r.body, b...)
	return len(b), nil
}
