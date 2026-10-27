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
// directions, unless the route grants Rule.AuthedRead — which every
// edge.AuthNone route gets implicitly (RegisterCached): the dispatcher never
// resolves or forwards an identity there, so the bearer cannot change the
// body.
//
// Why per-tournament invalidation works without new backend code: every
// public-data-changing write in tournament-service lands (via the
// transactional outbox) on the worker's tournament_changed consumer, which —
// after invalidating the backend Redis cache — publishes a realtime event on
// the Redis channel "realtime:tournament:{id}:bracket". The gateway already
// PSUBSCRIBEs to realtime:* for WebSocket fan-out (internal/events); this
// cache is simply a second consumer of that same worker-emitted signal:
// events.Fanout(hub, cache). A live draft's reads are cached under their
// SESSION, never a tournament: any frame on "draft:{session_id}:board" or
// "draft:{session_id}:chat" means that session's board or chat moved, so it
// drops exactly those entries (a pick writes no public row; what a draft does
// stale — its export — arrives as a tournament invalidation). The balancer
// topic is deliberately ignored — it carries ephemeral presence heartbeats
// that would otherwise keep the cache permanently cold for any tournament
// with an open balancer session.
//
// The TTL is a staleness backstop, not the primary mechanism: some writes
// (e.g. public registration create → participants_count) do not emit
// tournament_changed at all — the backend's own 300s read cache already
// accepts that staleness; the short gateway TTL adds a bounded sliver on top.
//
// Redis pub/sub is fire-and-forget: a gateway that is briefly disconnected
// misses invalidations. The subscriber Resets the cache once it has
// re-subscribed (see Reset), and the TTL bounds anything it cannot see.
//
// Bounds: entries are LRU-evicted past maxEntries or past maxTotalBytes
// aggregate stored size (key + body + its gzip copy), individual bodies
// larger than maxBodyBytes are served but never stored, and URLs whose key
// exceeds maxKeyBytes bypass the cache. The key space is derived from request
// URLs, which an anonymous client controls (arbitrary query strings), so the
// LRU bound is what keeps a query-string flood from growing the map — the
// same posture as principal.Resolver's token LRU.
//
// Compression: a stored body is gzipped once, so a replay to a client that
// accepts gzip costs no per-request compression here or at nginx (which
// leaves an already-encoded response alone). Measured on the 195 KB draft
// board: ~0.5 ms once per fill instead of ~0.7 ms of nginx's 0.5 CPU per
// request.
//
// Concurrent misses for one key are collapsed via singleflight so a cold or
// just-invalidated hot key costs ONE upstream RPC, not one per waiting client.
// The shared fetch runs on a context detached from the initiating client
// (context.WithoutCancel): one impatient client closing its tab must not fail
// the fetch for everyone behind it; the edge dispatcher's own per-route RPC
// timeout still bounds it.
package respcache

import (
	"bytes"
	"compress/gzip"
	"container/list"
	"context"
	"encoding/json"
	"io"
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
	// maxTotalBytes bounds the sum of stored entry sizes (entry.size: key,
	// body and gzip copy). Without this, a cache full of maxBodyBytes-sized
	// entries could reach maxEntries * maxBodyBytes (12 GiB) — wildly past
	// the gateway container's 256 MiB limit (docker-compose.production.yml).
	// 32 MiB is 32x the profile that motivated the raise above, comfortably
	// covers realistic concurrent large-profile traffic (most cached bodies
	// are a few KB), and still leaves ~87% of the hard memory limit for the
	// Go runtime, connection buffers, and the gateway's other in-memory
	// caches.
	maxTotalBytes = 32 << 20
	// maxKeyBytes: a URL whose cache key is longer bypasses the cache. The
	// key is client-chosen (any query string), and no real public read comes
	// near it; without the cap 4096 keys of a few KiB each sat outside every
	// byte bound.
	maxKeyBytes = 2 << 10
	// gzipMinBytes: smaller bodies are stored identity-only — a few hundred
	// bytes gain nothing worth a second copy and a client-side inflate.
	gzipMinBytes = 1 << 10
	// upstreamSettle caps the life of an entry filled shortly after an
	// invalidation of its tournament. The event lands here right after the
	// writer's commit, and the services caching the same read have already
	// missed it by then (the commit bumps their shared cache generations) —
	// unless that bump failed, in which case they miss only when the outbox
	// relay re-bumps (a 1s tick). A fill in that gap is the upstream's
	// pre-write copy, and with no event left to evict it, it would live a full
	// TTL. ponytail: fixed window; an upstream lagging past it (broker outage)
	// is still TTL-bounded.
	upstreamSettle = 10 * time.Second
)

// Extractor resolves the invalidation scope id for a request: a positive id
// in the rule's Scope (event-invalidated), 0 with ok=true for a deliberate
// TTL-only entry (see TTLOnly), or ok=false to skip caching — a scoped route
// whose id is missing must not produce an entry no event can reach.
type Extractor func(r *http.Request) (int64, bool)

// Scope names the realtime topic family whose frames invalidate a route's
// entries. The zero value is the tournament scope every non-draft rule uses.
type Scope uint8

const (
	// ScopeTournament entries drop on tournament:{id}:invalidation, narrowed
	// to the frame's stale resources (see resources.go).
	ScopeTournament Scope = iota
	// ScopeDraftBoard entries drop on any frame on draft:{session_id}:board.
	ScopeDraftBoard
	// ScopeDraftChat entries drop on any frame on draft:{session_id}:chat.
	ScopeDraftChat
)

// scopeKey is an entry's invalidation handle. A session id and a tournament
// id can be numerically equal; the kind keeps their entries apart.
type scopeKey struct {
	kind Scope
	id   int64
}

// FromPathValue extracts the scope id from a ServeMux path parameter, e.g.
// "id" in "/api/v1/tournaments/{id}".
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

// ExtractSessionIDFromJSONBody resolves a draft scope from the response
// body's "session.id": the tournament draft lookup is addressed by tournament
// but changes with its active session. A tournament with no draft answers
// null, which resolves nothing and is never stored.
func ExtractSessionIDFromJSONBody() func(body []byte) (int64, bool) {
	return func(body []byte) (int64, bool) {
		var payload struct {
			Session struct {
				ID int64 `json:"id"`
			} `json:"session"`
		}
		if err := json.Unmarshal(body, &payload); err != nil || payload.Session.ID <= 0 {
			return 0, false
		}
		return payload.Session.ID, true
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
	key    string
	scope  scopeKey
	status int
	header http.Header
	body   []byte
	gz     []byte // body gzipped once at fill (gzipBody), or nil
	exp    time.Time
}

// size is what an entry counts against maxBytes: its client-chosen key plus
// both encodings of the body.
func (e *entry) size() int64 { return int64(len(e.key) + len(e.body) + len(e.gz)) }

// invalidation is a scope's latest invalidate: its position in the
// Cache.invalidations sequence and its wall time.
type invalidation struct {
	seq uint64
	at  time.Time
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
	byID       map[scopeKey]map[string]struct{}
	totalBytes int64 // sum of entry.size() for all stored entries
	// invalidations counts invalidate calls; invalidated holds each scope's
	// latest one (ids only come from the internal bus). A flight snapshots
	// the count before going upstream: a body read before a write committed
	// must neither be stored after that write's invalidation — which found
	// nothing to evict yet — nor be handed to a request arriving after it.
	// fills counts the flights in progress by that snapshot, so sweepLocked
	// keeps every record one of them may still be refused by; reset is the
	// last Reset, an invalidation of every scope at once.
	invalidations uint64
	invalidated   map[scopeKey]invalidation
	fills         map[uint64]int
	reset         invalidation
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
		byID:     make(map[scopeKey]map[string]struct{}),

		invalidated: make(map[scopeKey]invalidation),
		fills:       make(map[uint64]int),
	}
}

// HandlerBuilder is the subset of edge.Dispatcher RegisterCached needs.
type HandlerBuilder interface {
	Handler(spec edge.RouteSpec) http.HandlerFunc
}

// Rule is one route's caching contract.
type Rule struct {
	// Extract resolves the invalidation scope id (see Extractor). nil: the id
	// is known only from the response body (ExtractFromBody).
	Extract Extractor
	// Scope is the topic family the resolved id belongs to (zero value:
	// tournament).
	Scope Scope
	// TTL overrides the cache's staleness backstop for this route; 0 keeps
	// the cache default.
	TTL time.Duration
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
	// ExtractFromBody is a fallback used ONLY when Extract fails (ok=false) or
	// is nil: resolves the invalidation scope from the just-fetched response
	// body instead of the request path. For a route whose path segment is
	// sometimes a slug (see ExtractIDFromJSONBody) rather than the numeric id
	// Extract expects -- without this, a slug request would never populate or
	// hit the cache at all, silently losing the optimization for what becomes
	// the primary URL form -- or whose path names no id of its scope at all
	// (see ExtractSessionIDFromJSONBody).
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
//
// An edge.AuthNone route always gets AuthedRead: the dispatcher forwards no
// identity for it, so a bearer-carrying request reaches exactly the same
// handler input as an anonymous one. Without the grant, every signed-in page
// view of a public aggregate (home/statistics/workspace stats) bypassed the
// cache and cost a full RPC.
func RegisterCached(mux *http.ServeMux, b HandlerBuilder, specs []edge.RouteSpec, rules map[string]Rule, c *Cache) {
	for _, s := range specs {
		var h http.Handler = b.Handler(s)
		if rule, ok := rules[s.Pattern]; ok && s.Method == http.MethodGet {
			if s.Auth == edge.AuthNone {
				rule.AuthedRead = true
			}
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
	ttl := c.ttl
	if rule.TTL > 0 {
		ttl = rule.TTL
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
		var id int64
		idOK := false
		if rule.Extract != nil {
			id, idOK = rule.Extract(r)
		}
		if !idOK && rule.ExtractFromBody == nil {
			next.ServeHTTP(w, r)
			return
		}
		key := cacheKey(r)
		if len(key) > maxKeyBytes {
			next.ServeHTTP(w, r)
			return
		}

		if e := c.get(key); e != nil {
			writeEntry(w, r, e, "HIT", true)
			return
		}

		// Every miss — anonymous or AuthedRead-granted — shares ONE
		// anonymized flight per key: after each invalidation the whole herd
		// of logged-in viewers costs a single upstream rebuild instead of
		// one per client, and the 200 repopulates the entry even when no
		// anonymous viewer ever arrives (during a check-in window everyone
		// on the participants page is logged in).
		//
		// The flight key carries the scope's invalidation generation, so a
		// request arriving after an invalidation starts a fresh flight
		// instead of joining one that went upstream before the write.
		gen := c.generation(scopeKey{rule.Scope, id}, idOK)
		leader := false
		ch := c.flight.DoChan(key+"\x00"+strconv.FormatUint(gen, 10), func() (any, error) {
			leader = true // only the leader's own closure ever runs
			start := c.beginFill()
			defer c.endFill(start)
			rec := &recorder{header: make(http.Header), status: http.StatusOK}
			// Detach from the initiating client's lifetime; the edge
			// dispatcher's per-route RPC timeout still bounds the call.
			// Strip the caller's identity so the upstream answer is the
			// universal anonymous body (a no-op for anonymous initiators).
			req := r.Clone(context.WithoutCancel(r.Context()))
			req.Header.Del("Authorization")
			next.ServeHTTP(rec, req)
			resolvedID, resolvedOK := id, idOK
			if !resolvedOK && rule.ExtractFromBody != nil {
				resolvedID, resolvedOK = rule.ExtractFromBody(rec.body)
			}
			e := &entry{
				key:    key,
				scope:  scopeKey{rule.Scope, resolvedID},
				status: rec.status,
				header: rec.header,
				body:   rec.body,
				exp:    c.now().Add(ttl),
			}
			// Only cache clean successes: errors and empty-but-odd statuses
			// must stay live. (Anonymous 404s for hidden tournaments are
			// deliberately not cached either — rare, and correctness-critical
			// around visibility flips.)
			if resolvedOK && e.status == http.StatusOK && len(e.body) <= maxBodyBytes {
				if e.header.Get("Content-Encoding") == "" {
					e.gz = gzipBody(e.body)
				}
				c.store(e, start)
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
			// The leader's own answer keeps upstream's encoding; its
			// waiters, like hits, may take the stored gzip copy.
			writeEntry(w, r, e, label, !leader)
		case <-r.Context().Done():
			// Client gone; the shared flight keeps running for the others.
		}
	})
}

// invalidate drops the scope's cached responses whose key contains any of
// patterns, or all of them when patterns is nil. Returns how many entries
// were removed. It also records the invalidation even when nothing matched:
// a fetch already in flight has no entry yet, and store must still refuse
// its pre-write body.
func (c *Cache) invalidate(s scopeKey, patterns []string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := c.now()
	c.sweepLocked(now)
	c.invalidations++
	c.invalidated[s] = invalidation{seq: c.invalidations, at: now}
	keys := c.byID[s]
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

// sweepLocked drops the invalidation records nothing consults any more: past
// upstreamSettle (no fill's lifetime is capped by them) and no newer than
// the oldest fill still in flight (store refuses a body only for a record
// newer than its fill's start). Without it the map kept one record per
// tournament or draft session ever invalidated, for the process lifetime;
// now it holds the scopes invalidated within the window (or since the
// oldest running fill began).
func (c *Cache) sweepLocked(now time.Time) {
	oldest := c.invalidations
	for start := range c.fills {
		oldest = min(oldest, start)
	}
	for s, inv := range c.invalidated {
		if inv.seq <= oldest && !now.Before(inv.at.Add(upstreamSettle)) {
			delete(c.invalidated, s)
		}
	}
}

// Reset drops every entry and fences every fill in flight, as if each scope
// had just been invalidated (events.Resetter): the subscriber calls it after
// a lost Redis connection, when invalidations may have gone missing. A fill
// landing within upstreamSettle of it is capped like any post-invalidation
// fill. Every per-scope record is older than this fence and thus redundant.
func (c *Cache) Reset() {
	if c == nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.invalidations++
	c.reset = invalidation{seq: c.invalidations, at: c.now()}
	clear(c.invalidated)
	clear(c.keys)
	clear(c.byID)
	c.lru.Init()
	c.totalBytes = 0
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
// or pre-migration frame), or any resource whose table entry is nil — one
// that can change any page, or one this table does not know yet. A resource
// whose entry is an EMPTY slice contributes nothing, which is how "this cache
// holds nothing of that" is expressed — see resources.go.
func patternsFor(resources []string) []string {
	if len(resources) == 0 {
		return nil
	}
	patterns := make([]string, 0, len(resources))
	for _, resource := range resources {
		known := resourcePatterns[resource]
		if known == nil {
			return nil
		}
		patterns = append(patterns, known...)
	}
	return patterns
}

// Broadcast implements the events.Broadcaster shape so the cache rides the
// existing realtime subscription (events.Fanout(hub, cache)).
//
// Three topic shapes are consumed, each reaching only its own scope:
//   - tournament:{id}:invalidation drops that tournament's entries for the
//     frame's stale resources (see resources.go);
//   - draft:{session_id}:board drops that session's board entries;
//   - draft:{session_id}:chat drops that session's chat entries.
//
// A draft frame needs no resource parsing — any frame on the topic means the
// session's board or chat moved — and it never reaches a tournament: the
// previous rail let a reason-less draft frame drop the whole tournament,
// twice per pick, at peak spectating. Every other domain topic (:bracket,
// :balancer, :streams, :map-veto, ...) carries data for the UI and is
// ignored; workspace/user invalidations are ignored too, as this cache
// stores nothing of theirs.
func (c *Cache) Broadcast(topic string, payload []byte) {
	if c == nil {
		return
	}
	family, rest, _ := strings.Cut(topic, ":")
	rawID, sub, ok := strings.Cut(rest, ":")
	if !ok {
		return
	}
	var s scopeKey
	switch family + ":" + sub {
	case "tournament:invalidation":
		s.kind = ScopeTournament
	case "draft:board":
		s.kind = ScopeDraftBoard
	case "draft:chat":
		s.kind = ScopeDraftChat
	default:
		return
	}
	if s.id, ok = parseID(rawID); !ok {
		return
	}
	var patterns []string
	if s.kind == ScopeTournament {
		patterns = patternsFor(eventResources(payload))
	}
	if n := c.invalidate(s, patterns); n > 0 {
		c.log.Debug("response cache invalidated", "topic", topic, "entries", n)
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

// generation is a flight's join generation: its scope's latest invalidation,
// or the global count when the id is only known from the response body.
func (c *Cache) generation(s scopeKey, idOK bool) uint64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	if idOK {
		return c.lastInvalidationLocked(s).seq
	}
	return c.invalidations
}

// beginFill snapshots the invalidation count before a flight goes upstream
// (start, checked by store) and counts the flight in progress until endFill,
// which keeps sweepLocked from dropping a record store still needs.
func (c *Cache) beginFill() (start uint64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.fills[c.invalidations]++
	return c.invalidations
}

func (c *Cache) endFill(start uint64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.fills[start]--
	if c.fills[start] == 0 {
		delete(c.fills, start)
	}
}

// lastInvalidationLocked is the later of s's own latest invalidation and the
// last Reset; the zero value (never invalidated) refuses and caps nothing.
func (c *Cache) lastInvalidationLocked(s scopeKey) invalidation {
	if inv := c.invalidated[s]; inv.seq > c.reset.seq {
		return inv
	}
	return c.reset
}

// store keeps e unless its scope was invalidated after the flight's start
// snapshot (the body predates the write), and caps a fill landing within
// upstreamSettle of an invalidation at the end of that window.
func (c *Cache) store(e *entry, start uint64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	inv := c.lastInvalidationLocked(e.scope)
	if inv.seq > start {
		return
	}
	if settled := inv.at.Add(upstreamSettle); c.now().Before(settled) && settled.Before(e.exp) {
		e.exp = settled
	}
	if el, ok := c.keys[e.key]; ok {
		c.removeLocked(el)
	}
	for len(c.keys) >= c.max || (c.lru.Len() > 0 && c.totalBytes+e.size() > c.maxBytes) {
		back := c.lru.Back()
		if back == nil {
			break
		}
		c.removeLocked(back)
	}
	el := c.lru.PushFront(e)
	c.keys[e.key] = el
	c.totalBytes += e.size()
	ids, ok := c.byID[e.scope]
	if !ok {
		ids = make(map[string]struct{})
		c.byID[e.scope] = ids
	}
	ids[e.key] = struct{}{}
}

func (c *Cache) removeLocked(el *list.Element) {
	e := el.Value.(*entry)
	delete(c.keys, e.key)
	c.lru.Remove(el)
	c.totalBytes -= e.size()
	if ids, ok := c.byID[e.scope]; ok {
		delete(ids, e.key)
		if len(ids) == 0 {
			delete(c.byID, e.scope)
		}
	}
}

// writeEntry replays a recorded response, as its gzip copy when gzipOK, the
// entry has one and the client accepts it. Every replay carries Vary:
// Accept-Encoding — the same URL answers in either encoding, so a cache
// downstream must key on it. Entries are immutable after store, so the
// shared header/body are safe to serve concurrently.
func writeEntry(w http.ResponseWriter, r *http.Request, e *entry, label string, gzipOK bool) {
	h := w.Header()
	for k, vv := range e.header {
		for _, v := range vv {
			h.Add(k, v)
		}
	}
	h.Add("Vary", "Accept-Encoding")
	h.Set("X-Cache", label)
	body := e.body
	if gzipOK && e.gz != nil && acceptsGzip(r.Header.Values("Accept-Encoding")) {
		h.Set("Content-Encoding", "gzip")
		body = e.gz
	}
	w.WriteHeader(e.status)
	_, _ = w.Write(body)
}

// gzipWriters recycles compressors: a fresh BestSpeed writer allocates
// ~1.2 MB of state, paid per fill otherwise.
var gzipWriters = sync.Pool{New: func() any {
	zw, _ := gzip.NewWriterLevel(nil, gzip.BestSpeed) // valid level: never errs
	return zw
}}

// gzipBody compresses body once at fill time, or returns nil when it is
// under gzipMinBytes or does not shrink.
func gzipBody(body []byte) []byte {
	if len(body) < gzipMinBytes {
		return nil
	}
	var buf bytes.Buffer
	zw := gzipWriters.Get().(*gzip.Writer)
	zw.Reset(&buf)
	_, _ = zw.Write(body) // a bytes.Buffer write cannot fail
	_ = zw.Close()
	zw.Reset(io.Discard) // do not pin buf from the pool
	gzipWriters.Put(zw)
	if buf.Len() >= len(body) {
		return nil
	}
	return buf.Bytes()
}

// acceptsGzip reports whether Accept-Encoding admits gzip (RFC 9110
// §12.5.3): an explicit gzip (or its alias x-gzip) decides by its q-value,
// otherwise "*" does; q=0 means "not acceptable". No header gets identity.
func acceptsGzip(values []string) bool {
	star := false
	for _, v := range values {
		for coding := range strings.SplitSeq(v, ",") {
			name, params, _ := strings.Cut(coding, ";")
			name = strings.TrimSpace(name)
			switch {
			case strings.EqualFold(name, "gzip"), strings.EqualFold(name, "x-gzip"):
				return qAcceptable(params)
			case name == "*":
				star = qAcceptable(params)
			}
		}
	}
	return star
}

// qAcceptable reports whether a coding's parameters leave it acceptable: no
// q, or a q above zero. An unparsable q refuses — identity is always safe.
func qAcceptable(params string) bool {
	for p := range strings.SplitSeq(params, ";") {
		name, value, _ := strings.Cut(p, "=")
		if strings.EqualFold(strings.TrimSpace(name), "q") {
			q, err := strconv.ParseFloat(strings.TrimSpace(value), 64)
			return err == nil && q > 0
		}
	}
	return true
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
