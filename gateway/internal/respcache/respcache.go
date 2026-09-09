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
// Bounds: entries are LRU-evicted past maxEntries or past maxTotalBytes
// aggregate stored size, and individual bodies larger than maxBodyBytes are
// served but never stored. The key space is derived from request URLs, which
// an anonymous client controls (arbitrary query strings), so the LRU bound is
// what keeps a query-string flood from growing the map — the same posture as
// principal.Resolver's token LRU.
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
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/sync/singleflight"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apiver"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

const (
	// maxEntries bounds the LRU. Anonymous clients control the key space
	// (query strings), so the cache must never grow without bound.
	maxEntries = 4096
	// maxBodyBytes: responses larger than this are proxied through but not
	// stored (the RPC reply is already fully in memory, so recording adds no
	// extra buffering — only storing is capped). Raised from the original
	// 1 MiB after a real profile (/api/v1/users/{id}/tournaments, a veteran
	// player with 40+ tournaments of nested encounters) measured ~1.045 MiB
	// and silently never cached — every page view paid the full upstream RPC
	// forever. 3 MiB gives headroom for larger histories; maxTotalBytes below
	// keeps the aggregate footprint bounded regardless of this per-entry cap.
	maxBodyBytes = 3 << 20
	// maxTotalBytes bounds the sum of stored entry bodies. Without this, a
	// cache full of maxBodyBytes-sized entries could reach maxEntries *
	// maxBodyBytes (12 GiB) — wildly past the gateway container's 256 MiB
	// limit (docker-compose.production.yml). 32 MiB is 32x the profile that
	// motivated the raise above, comfortably covers realistic concurrent
	// large-profile traffic (most cached bodies are a few KB), and still
	// leaves ~87% of the hard memory limit for the Go runtime, connection
	// buffers, and the gateway's other in-memory caches.
	maxTotalBytes = 32 << 20
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

// ExtractIDFromJSONBody resolves the invalidation scope from the JSON
// response body's top-level "id" field. Pairs with Rule.ExtractFromBody for a
// route whose path segment can be either a numeric id or an opaque slug
// (FromPathValue fails to parse the slug case) but whose response always
// echoes the canonical numeric id.
func ExtractIDFromJSONBody() func(body []byte) (int64, bool) {
	return func(body []byte) (int64, bool) {
		var payload struct {
			ID int64 `json:"id"`
		}
		if err := json.Unmarshal(body, &payload); err != nil || payload.ID <= 0 {
			return 0, false
		}
		return payload.ID, true
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
	ttl      time.Duration
	max      int
	maxBytes int64
	log      *slog.Logger
	now      func() time.Time
	flight   singleflight.Group

	mu         sync.Mutex
	keys       map[string]*list.Element // key -> element (holds *entry)
	lru        *list.List               // front = most recently used
	byID       map[int64]map[string]struct{}
	totalBytes int64 // sum of len(entry.body) for all stored entries
}

// New returns a Cache with the given staleness backstop, or nil (disabled)
// when ttl <= 0.
func New(ttl time.Duration, log *slog.Logger) *Cache {
	if ttl <= 0 {
		return nil
	}
	return newCache(ttl, maxEntries, maxTotalBytes, log)
}

func newCache(ttl time.Duration, max int, maxBytes int64, log *slog.Logger) *Cache {
	return &Cache{
		ttl:      ttl,
		max:      max,
		maxBytes: maxBytes,
		log:      log,
		now:      time.Now,
		keys:     make(map[string]*list.Element),
		lru:      list.New(),
		byID:     make(map[int64]map[string]struct{}),
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
	// AuthedRead lets bearer-carrying requests use the shared cache: they READ
	// entries on a hit, and on a miss they JOIN the anonymized singleflight —
	// the upstream fetch runs without any identity, so its 200 is exactly the
	// universal body an anonymous request would produce, and it populates the
	// entry. Without the grant, bearer-carrying requests bypass the cache
	// entirely.
	//
	// A non-200 flight result is viewer-dependent territory (an allowlisted
	// viewer may see MORE than anonymous — a hidden tournament's preview — so
	// an anonymous 404 must never become their answer): authed waiters retry
	// upstream with their own identity instead of accepting it.
	//
	// Safe ONLY when both hold for the route, verified against the backend
	// handler:
	//   1. an anonymous 200 proves the resource is publicly visible (the
	//      handler gates with assert_tournament_viewable before reading);
	//   2. the body after the gate is viewer-agnostic (the backend computes
	//      or caches it with no viewer in the key).
	// Holds for rpc.tournament.get_tournament / get_stages / get_standings /
	// list_teams / reg_pub_list (viewer is used exclusively in the gate).
	// Holds for list_encounters EXCEPT scope=my_team (see AuthedReadUnless).
	// Does NOT hold for encounters_overview, whose body carries a per-viewer
	// my_team_count.
	AuthedRead bool
	// ExtractFromBody is a fallback used ONLY when Extract fails (ok=false):
	// resolves the invalidation scope from the just-fetched response body
	// instead of the request path. For a route whose path segment is
	// sometimes a slug (see ExtractIDFromJSONBody) rather than the numeric id
	// Extract expects -- without this, a slug request would never populate or
	// hit the cache at all, silently losing the optimization for what becomes
	// the primary URL form. nil for every route that never sees a slug.
	ExtractFromBody func(body []byte) (int64, bool)
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

// Wrap returns next guarded by the cache. GETs whose extractor resolves a
// scope are cached; authenticated requests bypass entirely unless
// rule.AuthedRead grants them shared-cache access (hit reads + anonymized
// miss flights — see Rule.AuthedRead). Everything else passes through
// untouched.
func (c *Cache) Wrap(next http.Handler, rule Rule) http.Handler {
	if c == nil {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// v2 wraps the body; sharing the v1 cache would serve unwrapped JSON.
		if apiver.Want(r) {
			next.ServeHTTP(w, r)
			return
		}
		// Bearer present -> viewer-dependent visibility; without an
		// applicable AuthedRead grant, never read or write the shared cache.
		authed := r.Header.Get("Authorization") != ""
		allowAuthedRead := rule.AuthedRead &&
			(rule.AuthedReadUnless == nil || !rule.AuthedReadUnless(r))
		if r.Method != http.MethodGet || (authed && !allowAuthedRead) {
			next.ServeHTTP(w, r)
			return
		}
		tid, tidOK := rule.Extract(r)
		if !tidOK && rule.ExtractFromBody == nil {
			next.ServeHTTP(w, r)
			return
		}
		key := cacheKey(r)

		if e := c.get(key); e != nil {
			writeEntry(w, e, "HIT")
			return
		}

		// Every miss — anonymous or AuthedRead-granted — shares ONE
		// anonymized flight per key: after each invalidation the whole herd
		// of logged-in viewers costs a single upstream rebuild instead of
		// one per client, and the 200 repopulates the entry even when no
		// anonymous viewer ever arrives (during a check-in window everyone
		// on the participants page is logged in).

		ch := c.flight.DoChan(key, func() (any, error) {
			rec := &recorder{header: make(http.Header), status: http.StatusOK}
			// Detach from the initiating client's lifetime; the edge
			// dispatcher's per-route RPC timeout still bounds the call.
			// Strip the caller's identity so the upstream answer is the
			// universal anonymous body (a no-op for anonymous initiators).
			req := r.Clone(context.WithoutCancel(r.Context()))
			req.Header.Del("Authorization")
			next.ServeHTTP(rec, req)
			resolvedID, resolvedOK := tid, tidOK
			if !resolvedOK && rule.ExtractFromBody != nil {
				resolvedID, resolvedOK = rule.ExtractFromBody(rec.body)
			}
			e := &entry{
				key:          key,
				tournamentID: resolvedID,
				status:       rec.status,
				header:       rec.header,
				body:         rec.body,
				exp:          c.now().Add(c.ttl),
			}
			// Only cache clean successes: errors and empty-but-odd statuses
			// must stay live. (Anonymous 404s for hidden tournaments are
			// deliberately not cached either — rare, and correctness-critical
			// around visibility flips.)
			if resolvedOK && e.status == http.StatusOK && len(e.body) <= maxBodyBytes {
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
			e := res.Val.(*entry)
			if authed && e.status != http.StatusOK {
				// The anonymous answer under-represents an allowlisted
				// viewer (hidden tournament preview): retry with their own
				// identity rather than serving them an anonymous 404/error.
				next.ServeHTTP(w, r)
				return
			}
			label := "MISS"
			if res.Shared {
				label = "COALESCED"
			}
			writeEntry(w, e, label)
		case <-r.Context().Done():
			// Client gone; the shared flight keeps running for the others.
		}
	})
}

// Invalidate drops cached responses for the tournament whose key contains any
// of patterns, or every response for the tournament when patterns is nil.
// Returns how many entries were removed.
func (c *Cache) Invalidate(tournamentID int64, patterns []string) int {
	if c == nil {
		return 0
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	keys := c.byID[tournamentID]
	// removeLocked deletes from this same set as we range (legal in Go).
	n := 0
	for k := range keys {
		if patterns != nil && !matchesAnyPattern(k, patterns) {
			continue
		}
		if el, ok := c.keys[k]; ok {
			c.removeLocked(el)
			n++
		}
	}
	return n
}

// bareTournamentDetailPattern is a sentinel matched by
// isBareTournamentDetailKey instead of literal substring containment: the
// bare tournament-detail route's path segment is either a numeric id or an
// opaque slug (see Rule.ExtractFromBody), so no fixed substring identifies it
// the way "/registration/list" does for its sibling route.
const bareTournamentDetailPattern = "\x00bare-tournament-detail"

func matchesAnyPattern(key string, patterns []string) bool {
	for _, pattern := range patterns {
		if pattern == bareTournamentDetailPattern {
			if isBareTournamentDetailKey(key) {
				return true
			}
			continue
		}
		if strings.Contains(key, pattern) {
			return true
		}
	}
	return false
}

// isBareTournamentDetailKey reports whether key is exactly the tournament
// detail route ("/api/v1/tournaments/{id-or-slug}?..."), not a sibling
// sub-route like /stages or /standings that shares the same prefix.
func isBareTournamentDetailKey(key string) bool {
	rest, ok := strings.CutPrefix(key, "/api/v1/tournaments/")
	if !ok {
		return false
	}
	segment, _, found := strings.Cut(rest, "?")
	return found && segment != "" && !strings.Contains(segment, "/")
}

// eventResources extracts the stale resources from an invalidation frame:
// {"op":"event","topic":...,"event":{"data":{"resources":[...]}}} — see
// shared/services/realtime/emit.py. A frame that does not parse, or names no
// resource, yields nil, and callers treat nil as "scope unknown, drop
// everything for it": over-invalidation costs a cache miss, under-invalidation
// serves a stale page.
func eventResources(payload []byte) []string {
	var frame struct {
		Event struct {
			Data struct {
				Resources []string `json:"resources"`
			} `json:"data"`
		} `json:"event"`
	}
	if err := json.Unmarshal(payload, &frame); err != nil {
		return nil
	}
	return frame.Event.Data.Resources
}

// patternsFor unions the URL substrings of every named resource.
//
// nil (drop everything for the scope) for: no resources at all (unparseable
// or pre-migration frame), or any resource this table does not know yet. A
// resource whose entry is an EMPTY slice contributes nothing, which is how
// "this cache holds nothing of that" is expressed — see resources.go.
func patternsFor(resources []string) []string {
	if len(resources) == 0 {
		return nil
	}
	patterns := make([]string, 0, len(resources))
	for _, resource := range resources {
		known, ok := resourcePatterns[resource]
		if !ok {
			return nil
		}
		patterns = append(patterns, known...)
	}
	return patterns
}

// Broadcast implements the events.Broadcaster shape so the cache rides the
// existing realtime subscription (events.Fanout(hub, cache)).
//
// ONLY `<scope>:invalidation` topics are consumed. Domain topics (:bracket,
// :draft, :balancer, :streams, :map-veto, ...) carry data for the UI and are
// ignored here by design: mixing the two is what produced both halves of the
// bug this rail replaced — a draft pick dropped the whole tournament while a
// balancer export, which really did rewrite team rows, dropped nothing.
//
// Only the tournament scope has anything cached here (this cache stores
// anonymous public reads); workspace/user invalidations parse fine and match
// no entry.
func (c *Cache) Broadcast(topic string, payload []byte) {
	if c == nil {
		return
	}
	rest, ok := strings.CutPrefix(topic, "tournament:")
	if !ok {
		return
	}
	rawID, sub, ok := strings.Cut(rest, ":")
	if !ok || sub != "invalidation" {
		return
	}
	id, ok := parseID(rawID)
	if !ok {
		return
	}
	patterns := patternsFor(eventResources(payload))
	if n := c.Invalidate(id, patterns); n > 0 {
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
	for len(c.keys) >= c.max || (c.lru.Len() > 0 && c.totalBytes+int64(len(e.body)) > c.maxBytes) {
		back := c.lru.Back()
		if back == nil {
			break
		}
		c.removeLocked(back)
	}
	el := c.lru.PushFront(e)
	c.keys[e.key] = el
	c.totalBytes += int64(len(e.body))
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
	c.totalBytes -= int64(len(e.body))
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
