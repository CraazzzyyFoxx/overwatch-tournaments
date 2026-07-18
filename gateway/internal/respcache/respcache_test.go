package respcache

import (
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func testCache(t *testing.T) *Cache {
	t.Helper()
	return newCache(time.Minute, maxEntries, slog.Default())
}

// counting handler: JSON 200, upstream call counter.
func upstream(calls *atomic.Int64) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintf(w, `{"n":%d}`, calls.Load())
	})
}

func doGet(h http.Handler, target string, auth string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, target, nil)
	req.SetPathValue("id", "72")
	if auth != "" {
		req.Header.Set("Authorization", auth)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

// The core promise: two identical anonymous GETs cost one upstream call, and
// the second is served from the cache with X-Cache: HIT and the same body.
func TestAnonymousHitServesStoredResponse(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id")})

	first := doGet(h, "/api/v1/tournaments/72", "")
	second := doGet(h, "/api/v1/tournaments/72", "")

	if calls.Load() != 1 {
		t.Fatalf("upstream calls = %d, want 1", calls.Load())
	}
	if got := second.Header().Get("X-Cache"); got != "HIT" {
		t.Fatalf("X-Cache = %q, want HIT", got)
	}
	if first.Body.String() != second.Body.String() {
		t.Fatalf("cached body diverged: %q vs %q", first.Body.String(), second.Body.String())
	}
	if got := second.Header().Get("Content-Type"); got != "application/json" {
		t.Fatalf("Content-Type not replayed: %q", got)
	}
}

// Visibility is viewer-dependent: without AuthedRead, a bearer-carrying
// request must neither be served from the shared cache nor populate it.
func TestAuthorizedRequestsBypassCache(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id")})

	doGet(h, "/api/v1/tournaments/72", "") // seeds the anonymous entry
	authed := doGet(h, "/api/v1/tournaments/72", "Bearer tok")
	if authed.Header().Get("X-Cache") != "" {
		t.Fatal("authenticated request must not touch the cache")
	}
	if calls.Load() != 2 {
		t.Fatalf("authenticated request must hit upstream, calls = %d", calls.Load())
	}

	// And it must not have poisoned/refreshed the anonymous entry either:
	// the anonymous entry still serves call #1's body.
	hit := doGet(h, "/api/v1/tournaments/72", "")
	if hit.Body.String() != `{"n":1}` {
		t.Fatalf("anonymous entry overwritten by authed pass: %q", hit.Body.String())
	}
}

// AuthedRead (the /tournaments/[id] shell routes): an anonymous-written 200
// is byte-identical for any allowed viewer, so bearer-carrying requests may
// READ it — logged-in spectators stop costing one RPC per page view.
func TestAuthedReadServesAnonymousEntry(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id"), AuthedRead: true})

	doGet(h, "/api/v1/tournaments/72", "") // anonymous seeds the entry
	authed := doGet(h, "/api/v1/tournaments/72", "Bearer tok")
	if got := authed.Header().Get("X-Cache"); got != "HIT" {
		t.Fatalf("X-Cache = %q, want HIT for AuthedRead route", got)
	}
	if calls.Load() != 1 {
		t.Fatalf("authed read hit upstream: calls = %d, want 1", calls.Load())
	}
}

// An AuthedRead miss populates the shared cache via the anonymized flight:
// the upstream fetch carries no identity, so its 200 is the universal
// anonymous body and later viewers (anonymous or authed) hit the entry.
// During a check-in window every viewer is logged in — without this, each
// invalidation cost one full rebuild PER connected client.
func TestAuthedMissPopulatesViaAnonymizedFlight(t *testing.T) {
	var calls atomic.Int64
	var sawAuth atomic.Bool
	c := testCache(t)
	h := c.Wrap(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Header.Get("Authorization") != "" {
			sawAuth.Store(true)
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	}), Rule{Extract: FromPathValue("id"), AuthedRead: true})

	authed := doGet(h, "/api/v1/tournaments/72", "Bearer tok") // MISS, anonymized flight
	if got := authed.Header().Get("X-Cache"); got != "MISS" {
		t.Fatalf("X-Cache = %q, want MISS", got)
	}
	if sawAuth.Load() {
		t.Fatal("flight leaked the caller's Authorization header upstream")
	}
	anon := doGet(h, "/api/v1/tournaments/72", "")
	if got := anon.Header().Get("X-Cache"); got != "HIT" {
		t.Fatalf("authed miss did not populate the cache: X-Cache = %q", got)
	}
	if calls.Load() != 1 {
		t.Fatalf("calls = %d, want 1", calls.Load())
	}
}

// AuthedReadUnless (encounters scope=my_team): the matching query shape is
// viewer-dependent, so an authed request bypasses the cache entirely there,
// while other shapes on the same route keep the AuthedRead grant. Anonymous
// requests cache both shapes.
func TestAuthedReadUnlessRevokesGrantPerRequest(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstream(&calls), Rule{
		Extract:          FromQuery("tournament_id"),
		AuthedRead:       true,
		AuthedReadUnless: QueryEquals("scope", "my_team"),
	})

	// Anonymous seeds both shapes (my_team included — its anonymous body is
	// legitimate FOR anonymous readers).
	doGet(h, "/api/v1/encounters?tournament_id=72", "")
	doGet(h, "/api/v1/encounters?tournament_id=72&scope=my_team", "")

	// Authed on the plain shape: HIT via AuthedRead.
	plain := doGet(h, "/api/v1/encounters?tournament_id=72", "Bearer tok")
	if plain.Header().Get("X-Cache") != "HIT" {
		t.Fatal("plain shape must honor AuthedRead")
	}
	// Authed on my_team: full bypass — never the anonymous (empty) body.
	mine := doGet(h, "/api/v1/encounters?tournament_id=72&scope=my_team", "Bearer tok")
	if mine.Header().Get("X-Cache") != "" {
		t.Fatal("my_team shape must bypass the cache for authed requests")
	}
	if calls.Load() != 3 {
		t.Fatalf("calls = %d, want 3 (two anon seeds + one authed my_team)", calls.Load())
	}
	// Anonymous my_team readers still get their cached entry.
	if rec := doGet(h, "/api/v1/encounters?tournament_id=72&scope=my_team", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("anonymous my_team entry must remain served to anonymous readers")
	}
}

// An authenticated miss joins the anonymous singleflight: N concurrent
// viewers after an invalidation cost exactly one upstream rebuild.
func TestAuthedMissJoinsFlight(t *testing.T) {
	var calls atomic.Int64
	release := make(chan struct{})
	c := testCache(t)
	h := c.Wrap(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		<-release
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{}`))
	}), Rule{Extract: FromPathValue("id"), AuthedRead: true})

	var wg sync.WaitGroup
	codes := make([]int, 2)
	wg.Add(2)
	go func() { defer wg.Done(); codes[0] = doGet(h, "/api/v1/tournaments/72", "").Code }()
	go func() { defer wg.Done(); codes[1] = doGet(h, "/api/v1/tournaments/72", "Bearer tok").Code }()
	// Give both goroutines time to reach the flight; only one may go upstream.
	deadline := time.After(2 * time.Second)
	for calls.Load() < 1 {
		select {
		case <-deadline:
			t.Fatal("no request reached upstream")
		case <-time.After(5 * time.Millisecond):
		}
	}
	time.Sleep(20 * time.Millisecond)
	if calls.Load() != 1 {
		t.Fatalf("authed miss did not coalesce into the flight (calls = %d)", calls.Load())
	}
	close(release)
	wg.Wait()
	if codes[0] != http.StatusOK || codes[1] != http.StatusOK {
		t.Fatalf("codes = %v, want both 200", codes)
	}
}

// A non-200 flight result must never become an authed viewer's answer (an
// allowlisted viewer may see a hidden tournament the anonymous fetch 404s
// on): the authed caller retries upstream with its own identity, and the
// error is not cached.
func TestAuthedMissFallsBackOnNon200(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Header.Get("Authorization") == "" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"hidden":true}`))
	}), Rule{Extract: FromPathValue("id"), AuthedRead: true})

	authed := doGet(h, "/api/v1/tournaments/72", "Bearer tok")
	if authed.Code != http.StatusOK {
		t.Fatalf("authed fallback code = %d, want 200 (own-identity retry)", authed.Code)
	}
	if authed.Body.String() != `{"hidden":true}` {
		t.Fatalf("authed fallback body = %q", authed.Body.String())
	}
	if calls.Load() != 2 {
		t.Fatalf("calls = %d, want 2 (anonymized 404 + identity retry)", calls.Load())
	}
	// The anonymous 404 must not have been stored.
	anon := doGet(h, "/api/v1/tournaments/72", "")
	if anon.Header().Get("X-Cache") == "HIT" {
		t.Fatal("non-200 flight result was cached")
	}
}

// A request whose extractor resolves no tournament id would be unreachable by
// Invalidate — it must never be cached.
func TestMissingTournamentIDPassesThrough(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstream(&calls), Rule{Extract: FromQuery("tournament_id")})

	for range 2 {
		rec := doGet(h, "/api/v1/encounters?page=1", "")
		if rec.Header().Get("X-Cache") != "" {
			t.Fatal("id-less request must bypass the cache")
		}
	}
	if calls.Load() != 2 {
		t.Fatalf("calls = %d, want 2 (no caching)", calls.Load())
	}
}

// Non-200 upstream answers must stay live: a transient 503 or a 404 cached
// for TTL seconds would outlive the incident/visibility flip.
func TestNon200NotStored(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		w.WriteHeader(http.StatusNotFound)
	}), Rule{Extract: FromPathValue("id")})

	doGet(h, "/api/v1/tournaments/72", "")
	rec := doGet(h, "/api/v1/tournaments/72", "")
	if calls.Load() != 2 {
		t.Fatalf("404 was cached: calls = %d, want 2", calls.Load())
	}
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

// Query canonicalization: parameter order must not fragment the cache.
func TestQueryOrderSharesOneEntry(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstream(&calls), Rule{Extract: FromQuery("tournament_id")})

	doGet(h, "/api/v1/encounters?tournament_id=72&page=1", "")
	rec := doGet(h, "/api/v1/encounters?page=1&tournament_id=72", "")
	if calls.Load() != 1 {
		t.Fatalf("reordered query missed the cache: calls = %d", calls.Load())
	}
	if rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("reordered query must be a HIT")
	}
	// Different param VALUES are different entries.
	doGet(h, "/api/v1/encounters?page=2&tournament_id=72", "")
	if calls.Load() != 2 {
		t.Fatalf("distinct query collapsed into one entry: calls = %d", calls.Load())
	}
}

// Invalidate must drop every entry for the tournament and leave others alone.
func TestInvalidateDropsOnlyThatTournament(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstream(&calls), Rule{Extract: FromQuery("tournament_id")})

	doGet(h, "/api/v1/encounters?tournament_id=72", "")
	doGet(h, "/api/v1/encounters?tournament_id=72&page=2", "")
	doGet(h, "/api/v1/encounters?tournament_id=73", "")

	if n := c.Invalidate(72); n != 2 {
		t.Fatalf("Invalidate(72) = %d, want 2", n)
	}

	// 73 still cached, 72 refetches.
	if rec := doGet(h, "/api/v1/encounters?tournament_id=73", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("tournament 73 must survive 72's invalidation")
	}
	doGet(h, "/api/v1/encounters?tournament_id=72", "")
	if calls.Load() != 4 {
		t.Fatalf("calls = %d, want 4 (72 refetched once)", calls.Load())
	}
}

// Broadcast: worker-published bracket/draft topics invalidate; the balancer
// topic (ephemeral presence heartbeats) and foreign topics must not.
func TestBroadcastTopicRouting(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id")})

	seed := func() {
		doGet(h, "/api/v1/tournaments/72", "")
		doGet(h, "/api/v1/tournaments/72", "") // ensure it is a HIT baseline
	}

	seed()
	before := calls.Load()

	for _, topic := range []string{"tournament:72:balancer", "workspace:1:logs", "encounter:72:map-veto", "tournament:xx:bracket"} {
		c.Broadcast(topic, nil)
		if rec := doGet(h, "/api/v1/tournaments/72", ""); rec.Header().Get("X-Cache") != "HIT" {
			t.Fatalf("topic %q must not invalidate", topic)
		}
	}
	if calls.Load() != before {
		t.Fatalf("non-matching topics caused refetches: %d -> %d", before, calls.Load())
	}

	for _, topic := range []string{"tournament:72:bracket", "tournament:72:draft"} {
		c.Broadcast(topic, nil)
		rec := doGet(h, "/api/v1/tournaments/72", "")
		if rec.Header().Get("X-Cache") == "HIT" {
			t.Fatalf("topic %q must invalidate", topic)
		}
		doGet(h, "/api/v1/tournaments/72", "") // re-seed HIT baseline
	}
}

// TTL is the staleness backstop for writes that emit no realtime event
// (e.g. registration counts).
func TestTTLExpiry(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	fake := time.Now()
	c.now = func() time.Time { return fake }
	h := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id")})

	doGet(h, "/api/v1/tournaments/72", "")
	fake = fake.Add(59 * time.Second)
	if rec := doGet(h, "/api/v1/tournaments/72", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("entry expired before its TTL")
	}
	fake = fake.Add(2 * time.Second)
	doGet(h, "/api/v1/tournaments/72", "")
	if calls.Load() != 2 {
		t.Fatalf("expired entry served: calls = %d, want 2", calls.Load())
	}
}

// TTLOnly entries (home aggregates, user profiles) are cached and expire by
// TTL, but no realtime tournament event may ever drop them — id 0 is
// unreachable from Broadcast, so live-match event storms cannot keep these
// hot aggregates permanently cold.
func TestTTLOnlyCachedButEventImmune(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	fake := time.Now()
	c.now = func() time.Time { return fake }
	h := c.Wrap(upstream(&calls), Rule{Extract: TTLOnly()})

	doGet(h, "/api/v1/statistics/champion", "")
	if rec := doGet(h, "/api/v1/statistics/champion", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("TTLOnly route must be cached")
	}

	// Realtime events for any tournament must not touch TTL-only entries.
	c.Broadcast("tournament:72:bracket", nil)
	c.Broadcast("tournament:0:bracket", nil) // malformed id 0 — must be ignored
	if rec := doGet(h, "/api/v1/statistics/champion", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("tournament events must not invalidate TTL-only entries")
	}
	if calls.Load() != 1 {
		t.Fatalf("upstream calls = %d, want 1", calls.Load())
	}

	// TTL still applies.
	fake = fake.Add(61 * time.Second)
	doGet(h, "/api/v1/statistics/champion", "")
	if calls.Load() != 2 {
		t.Fatalf("TTL-only entry never expired: calls = %d, want 2", calls.Load())
	}
}

// The LRU bound: a flood of distinct anonymous URLs must never grow the map
// past max, and must evict oldest-used first.
func TestLRUBound(t *testing.T) {
	var calls atomic.Int64
	c := newCache(time.Minute, 3, slog.Default())
	h := c.Wrap(upstream(&calls), Rule{Extract: FromQuery("tournament_id")})

	for i := 1; i <= 4; i++ {
		doGet(h, fmt.Sprintf("/api/v1/encounters?tournament_id=72&page=%d", i), "")
	}
	if len(c.keys) != 3 {
		t.Fatalf("cache grew past bound: %d entries", len(c.keys))
	}
	// page=1 (oldest) evicted; page=4 present.
	if rec := doGet(h, "/api/v1/encounters?tournament_id=72&page=4", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("newest entry evicted")
	}
	before := calls.Load()
	doGet(h, "/api/v1/encounters?tournament_id=72&page=1", "")
	if calls.Load() != before+1 {
		t.Fatal("oldest entry survived past the bound")
	}
}

// Herd collapse: N concurrent misses for one key -> exactly one upstream call.
func TestSingleflightCollapsesConcurrentMisses(t *testing.T) {
	var calls atomic.Int64
	release := make(chan struct{})
	c := testCache(t)
	h := c.Wrap(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		<-release
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{}`))
	}), Rule{Extract: FromPathValue("id")})

	const n = 16
	var wg sync.WaitGroup
	var started sync.WaitGroup
	results := make([]*httptest.ResponseRecorder, n)
	for i := range n {
		wg.Add(1)
		started.Add(1)
		go func(i int) {
			defer wg.Done()
			req := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments/72", nil)
			req.SetPathValue("id", "72")
			rec := httptest.NewRecorder()
			started.Done()
			h.ServeHTTP(rec, req)
			results[i] = rec
		}(i)
	}
	started.Wait()
	// Give the flight leader a moment to enter the handler, then release.
	time.Sleep(50 * time.Millisecond)
	close(release)
	wg.Wait()

	if calls.Load() != 1 {
		t.Fatalf("upstream calls = %d, want 1 (herd not collapsed)", calls.Load())
	}
	for i, rec := range results {
		if rec.Code != http.StatusOK || rec.Body.String() != `{}` {
			t.Fatalf("waiter %d got %d %q", i, rec.Code, rec.Body.String())
		}
	}
}

// A nil cache (disabled via config) must be fully inert.
func TestNilCacheIsInert(t *testing.T) {
	var c *Cache
	var calls atomic.Int64
	h := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id")})
	rec := doGet(h, "/api/v1/tournaments/72", "")
	if rec.Header().Get("X-Cache") != "" || calls.Load() != 1 {
		t.Fatal("nil cache must pass through untouched")
	}
	c.Broadcast("tournament:72:bracket", nil) // must not panic
	if c.Invalidate(72) != 0 {
		t.Fatal("nil Invalidate must return 0")
	}
	if New(0, slog.Default()) != nil {
		t.Fatal("New with ttl<=0 must return nil (disabled)")
	}
}

// Bodies past maxBodyBytes are served but never stored.
func TestOversizedBodyNotStored(t *testing.T) {
	var calls atomic.Int64
	big := make([]byte, maxBodyBytes+1)
	c := testCache(t)
	h := c.Wrap(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		_, _ = w.Write(big)
	}), Rule{Extract: FromPathValue("id")})

	first := doGet(h, "/api/v1/tournaments/72", "")
	if first.Body.Len() != len(big) {
		t.Fatalf("oversized body truncated: %d bytes", first.Body.Len())
	}
	doGet(h, "/api/v1/tournaments/72", "")
	if calls.Load() != 2 {
		t.Fatal("oversized body was stored")
	}
}
