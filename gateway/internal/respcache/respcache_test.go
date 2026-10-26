package respcache

import (
	"compress/gzip"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

func testCache(t *testing.T) *Cache {
	t.Helper()
	return newCache(time.Minute, maxEntries, maxTotalBytes, slog.Default())
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

// doGetWithID is doGet's cousin for requests whose {id} path value is not the
// literal "72" doGet hardcodes -- needed to exercise a slug-shaped segment.
func doGetWithID(h http.Handler, target, id, auth string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, target, nil)
	req.SetPathValue("id", id)
	if auth != "" {
		req.Header.Set("Authorization", auth)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

// upstreamTournament replies like the tournament-detail RPC: a JSON body
// whose "id" is the canonical numeric id regardless of which path segment
// (numeric or slug) the request used to reach it.
func upstreamTournament(calls *atomic.Int64, id int64) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintf(w, `{"id":%d,"name":"Season 5"}`, id)
	})
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

// stubBuilder stands in for edge.Dispatcher: every spec gets the counting
// upstream.
type stubBuilder struct{ calls *atomic.Int64 }

func (b stubBuilder) Handler(edge.RouteSpec) http.HandlerFunc { return upstream(b.calls).ServeHTTP }

// An AuthNone route never forwards identity, so RegisterCached grants it
// AuthedRead: signed-in viewers of public aggregates share the anonymous
// entry. An AuthOptional route with the same Rule keeps the full bypass.
func TestRegisterCachedGrantsAuthedReadOnlyToAuthNone(t *testing.T) {
	cases := []struct {
		auth      edge.AuthMode
		wantCache string
		wantCalls int64
	}{
		{edge.AuthNone, "HIT", 1},
		{edge.AuthOptional, "", 2},
	}
	for _, tc := range cases {
		var calls atomic.Int64
		mux := http.NewServeMux()
		spec := edge.RouteSpec{Method: http.MethodGet, Pattern: "/api/v1/statistics/champion", Auth: tc.auth}
		RegisterCached(mux, stubBuilder{&calls}, []edge.RouteSpec{spec},
			map[string]Rule{spec.Pattern: {Extract: TTLOnly()}}, testCache(t))

		doGet(mux, "/api/v1/statistics/champion", "") // anonymous seeds the entry
		authed := doGet(mux, "/api/v1/statistics/champion", "Bearer tok")
		if got := authed.Header().Get("X-Cache"); got != tc.wantCache {
			t.Fatalf("auth=%v: X-Cache = %q, want %q", tc.auth, got, tc.wantCache)
		}
		if calls.Load() != tc.wantCalls {
			t.Fatalf("auth=%v: upstream calls = %d, want %d", tc.auth, calls.Load(), tc.wantCalls)
		}
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
// any invalidation — it must never be cached.
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

// invalidate must drop every entry for the tournament and leave others alone.
func TestInvalidateDropsOnlyThatTournament(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstream(&calls), Rule{Extract: FromQuery("tournament_id")})

	doGet(h, "/api/v1/encounters?tournament_id=72", "")
	doGet(h, "/api/v1/encounters?tournament_id=72&page=2", "")
	doGet(h, "/api/v1/encounters?tournament_id=73", "")

	if n := c.invalidate(scopeKey{id: 72}, nil); n != 2 {
		t.Fatalf("invalidate(72, nil) = %d, want 2", n)
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

// A tournament entry drops ONLY on its `tournament:{id}:invalidation`. Domain
// topics carry data for the UI: a draft pick or a balancer presence heartbeat
// must not touch it, which is exactly the mistake the previous rail made (a
// reason-less draft frame dropped every entry for the tournament, twice per
// pick). A draft session's own topics reach only that session's entries.
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

	ignored := []string{
		"tournament:72:bracket",
		"tournament:72:draft",
		"draft:72:board",
		"draft:72:chat",
		"tournament:72:balancer",
		"tournament:72:streams",
		"encounter:72:map-veto",
		"workspace:1:logs",
		"workspace:1:invalidation", // parses, but nothing of a workspace is cached here
		"tournament:xx:invalidation",
	}
	for _, topic := range ignored {
		c.Broadcast(topic, invalidationFrame("tournament.structure"))
		if rec := doGet(h, "/api/v1/tournaments/72", ""); rec.Header().Get("X-Cache") != "HIT" {
			t.Fatalf("topic %q must not invalidate", topic)
		}
	}
	if calls.Load() != before {
		t.Fatalf("non-matching topics caused refetches: %d -> %d", before, calls.Load())
	}

	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.detail"))
	if rec := doGet(h, "/api/v1/tournaments/72", ""); rec.Header().Get("X-Cache") == "HIT" {
		t.Fatal("the tournament's invalidation topic must invalidate")
	}
}

// invalidationFrame builds the literal frame published to Redis for a
// cache.invalidated event (shared/services/realtime/emit.py): the stale
// resources sit at .event.data.resources.
func invalidationFrame(resources ...string) []byte {
	quoted := make([]string, 0, len(resources))
	for _, resource := range resources {
		quoted = append(quoted, fmt.Sprintf("%q", resource))
	}
	return []byte(fmt.Sprintf(
		`{"op":"event","topic":"tournament:72:invalidation","event":{"event_id":1,`+
			`"event_type":"cache.invalidated","schema_version":1,`+
			`"occurred_at":"2026-01-01T00:00:00Z","actor_user_id":null,`+
			`"data":{"resources":[%s]}}}`,
		strings.Join(quoted, ","),
	))
}

// tournament.encounters scopes to the encounter routes and leaves the
// tournament-detail entry alone — a score report must not cost every
// spectator a detail refetch.
func TestBroadcastBracketChangedScopesToEncounters(t *testing.T) {
	var tournamentCalls, encounterCalls atomic.Int64
	c := testCache(t)
	tournamentHandler := c.Wrap(upstream(&tournamentCalls), Rule{Extract: FromPathValue("id")})
	encountersHandler := c.Wrap(upstream(&encounterCalls), Rule{Extract: FromQuery("tournament_id")})

	doGet(tournamentHandler, "/api/v1/tournaments/72", "")
	doGet(encountersHandler, "/api/v1/encounters?tournament_id=72", "")

	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.encounters"))

	if rec := doGet(tournamentHandler, "/api/v1/tournaments/72", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("tournament.encounters must not evict the tournament-detail entry")
	}
	if rec := doGet(encountersHandler, "/api/v1/encounters?tournament_id=72", ""); rec.Header().Get("X-Cache") == "HIT" {
		t.Fatal("tournament.encounters must evict the encounters entry")
	}
}

// An FFA result write publishes tournament.encounters, and the recalculation it
// enqueues tournament.standings: either must evict the stage's lobby tables, or
// a spectator's refetch is served the pre-result table for a whole TTL.
func TestBroadcastResultEventsEvictFfaStage(t *testing.T) {
	for _, resource := range []string{"tournament.encounters", "tournament.standings"} {
		var calls atomic.Int64
		c := testCache(t)
		h := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id")})
		get := func() *httptest.ResponseRecorder {
			req := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments/72/stages/9/ffa", nil)
			req.SetPathValue("id", "72")
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)
			return rec
		}

		get()
		c.Broadcast("tournament:72:invalidation", invalidationFrame(resource))

		if rec := get(); rec.Header().Get("X-Cache") == "HIT" {
			t.Fatalf("%s must evict the FFA stage entry", resource)
		}
	}
}

// tournament.registrations covers the participants list AND the detail entry
// (it embeds live participants_count/registrations_count), but leaves
// encounters/standings/teams alone.
func TestBroadcastRegistrationChangedScopesToRegistrationAndDetail(t *testing.T) {
	var tournamentCalls, listCalls, encounterCalls atomic.Int64
	c := testCache(t)
	tournamentHandler := c.Wrap(upstream(&tournamentCalls), Rule{Extract: FromPathValue("id")})
	listHandler := c.Wrap(upstream(&listCalls), Rule{Extract: FromPathValue("tournament_id")})
	encountersHandler := c.Wrap(upstream(&encounterCalls), Rule{Extract: FromQuery("tournament_id")})

	doGet(tournamentHandler, "/api/v1/tournaments/72", "")
	doGet(encountersHandler, "/api/v1/encounters?tournament_id=72", "")
	listReq := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments/72/registration/list", nil)
	listReq.SetPathValue("tournament_id", "72")
	listHandler.ServeHTTP(httptest.NewRecorder(), listReq)

	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.registrations"))

	if rec := doGet(tournamentHandler, "/api/v1/tournaments/72", ""); rec.Header().Get("X-Cache") == "HIT" {
		t.Fatal("tournament.registrations must evict the tournament-detail entry (embeds live counts)")
	}
	if rec := doGet(encountersHandler, "/api/v1/encounters?tournament_id=72", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("tournament.registrations must not evict the encounters entry")
	}
	listReq2 := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments/72/registration/list", nil)
	listReq2.SetPathValue("tournament_id", "72")
	rec2 := httptest.NewRecorder()
	listHandler.ServeHTTP(rec2, listReq2)
	if rec2.Header().Get("X-Cache") == "HIT" {
		t.Fatal("tournament.registrations must evict the registration/list entry")
	}
}

// The id-qualified tournament-detail pattern ("/api/v1/tournaments/{id}?")
// must not also match a sibling sub-route sharing the same path prefix, like
// /stages — the "?" boundary is what keeps the substring match precise.
func TestBroadcastRegistrationsDoesNotOverreachOntoSubroutes(t *testing.T) {
	var detailCalls, stagesCalls atomic.Int64
	c := testCache(t)
	detailHandler := c.Wrap(upstream(&detailCalls), Rule{Extract: FromPathValue("id")})
	stagesHandler := c.Wrap(upstream(&stagesCalls), Rule{Extract: FromPathValue("id")})

	doGet(detailHandler, "/api/v1/tournaments/72", "")
	stagesReq := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments/72/stages", nil)
	stagesReq.SetPathValue("id", "72")
	stagesHandler.ServeHTTP(httptest.NewRecorder(), stagesReq)

	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.registrations"))

	stagesReq2 := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments/72/stages", nil)
	stagesReq2.SetPathValue("id", "72")
	rec := httptest.NewRecorder()
	stagesHandler.ServeHTTP(rec, stagesReq2)
	if rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("tournament.registrations for tournament 72 must not evict its /stages entry")
	}
}

// A form save (hide_registrations, max_participants, public questions) changes
// what the participants list renders, so it must evict that list — anonymous
// and signed-in viewers share the entry — and nothing else.
func TestBroadcastFormChangedEvictsOnlyRegistrationList(t *testing.T) {
	var tournamentCalls, listCalls, encounterCalls atomic.Int64
	c := testCache(t)
	tournamentHandler := c.Wrap(upstream(&tournamentCalls), Rule{Extract: FromPathValue("id")})
	listHandler := c.Wrap(upstream(&listCalls), Rule{Extract: FromPathValue("tournament_id")})
	encountersHandler := c.Wrap(upstream(&encounterCalls), Rule{Extract: FromQuery("tournament_id")})

	doGet(tournamentHandler, "/api/v1/tournaments/72", "")
	doGet(encountersHandler, "/api/v1/encounters?tournament_id=72", "")
	listReq := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments/72/registration/list", nil)
	listReq.SetPathValue("tournament_id", "72")
	listHandler.ServeHTTP(httptest.NewRecorder(), listReq)

	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.registration_form"))

	if rec := doGet(tournamentHandler, "/api/v1/tournaments/72", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("form edit must not evict the tournament-detail entry")
	}
	if rec := doGet(encountersHandler, "/api/v1/encounters?tournament_id=72", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("form edit must not evict the encounters entry")
	}
	listReq2 := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments/72/registration/list", nil)
	listReq2.SetPathValue("tournament_id", "72")
	rec2 := httptest.NewRecorder()
	listHandler.ServeHTTP(rec2, listReq2)
	if rec2.Header().Get("X-Cache") == "HIT" {
		t.Fatal("form edit must evict the registration/list entry (hide_registrations would keep serving rows)")
	}
}

// A domain topic carries data for the UI and must never reach the cache. This
// is the invariant behind the previous rail's worst bug: a draft pick's
// reason-less frame dropped every entry for the tournament, twice per pick, at
// peak spectating.
func TestBroadcastDomainTopicEvictsNothing(t *testing.T) {
	var tournamentCalls, encounterCalls atomic.Int64
	c := testCache(t)
	tournamentHandler := c.Wrap(upstream(&tournamentCalls), Rule{Extract: FromPathValue("id")})
	encountersHandler := c.Wrap(upstream(&encounterCalls), Rule{Extract: FromQuery("tournament_id")})

	doGet(tournamentHandler, "/api/v1/tournaments/72", "")
	doGet(encountersHandler, "/api/v1/encounters?tournament_id=72", "")

	c.Broadcast("tournament:72:draft", []byte(
		`{"op":"event","topic":"tournament:72:draft","event":{"event_id":1,`+
			`"event_type":"draft.pick_made","schema_version":1,`+
			`"occurred_at":"2026-01-01T00:00:00Z","actor_user_id":null,`+
			`"data":{"resource":"draft.board","session_id":3}}}`,
	))

	if rec := doGet(tournamentHandler, "/api/v1/tournaments/72", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("a draft pick must not evict the tournament-detail entry")
	}
	if rec := doGet(encountersHandler, "/api/v1/encounters?tournament_id=72", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("a draft pick must not evict the encounters entry")
	}
}

// Fail-safe: anything this table cannot resolve into patterns drops every
// entry for the scope. Over-invalidation costs a cache miss; under-
// invalidation serves a stale page. The manifest parity test
// (resources_test.go) is what keeps the "unknown resource" case theoretical.
func TestBroadcastUnresolvableInvalidationDropsEverything(t *testing.T) {
	cases := []struct {
		name    string
		payload []byte
	}{
		{"resource absent from this table", invalidationFrame("tournament.something_new")},
		{"one known resource next to an unknown one", invalidationFrame("tournament.encounters", "tournament.x")},
		{"malformed json", []byte("not json")},
		{"no resources at all", invalidationFrame()},
		{"nil payload", nil},
		{"pre-migration frame carrying a reason", []byte(
			`{"op":"event","topic":"tournament:72:invalidation","event":{"event_id":1,` +
				`"event_type":"tournament.updated","schema_version":1,` +
				`"occurred_at":"2026-01-01T00:00:00Z","actor_user_id":null,` +
				`"data":{"tournament_id":72,"reason":"results_changed"}}}`,
		)},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var tournamentCalls, encounterCalls atomic.Int64
			c := testCache(t)
			tournamentHandler := c.Wrap(upstream(&tournamentCalls), Rule{Extract: FromPathValue("id")})
			encountersHandler := c.Wrap(upstream(&encounterCalls), Rule{Extract: FromQuery("tournament_id")})

			doGet(tournamentHandler, "/api/v1/tournaments/72", "")
			doGet(encountersHandler, "/api/v1/encounters?tournament_id=72", "")

			c.Broadcast("tournament:72:invalidation", tc.payload)

			if rec := doGet(tournamentHandler, "/api/v1/tournaments/72", ""); rec.Header().Get("X-Cache") == "HIT" {
				t.Fatalf("%s must evict the tournament-detail entry too", tc.name)
			}
			if rec := doGet(encountersHandler, "/api/v1/encounters?tournament_id=72", ""); rec.Header().Get("X-Cache") == "HIT" {
				t.Fatalf("%s must evict the encounters entry", tc.name)
			}
		})
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
	c.Broadcast("tournament:72:invalidation", nil)
	c.Broadcast("tournament:0:invalidation", nil) // malformed id 0 — must be ignored
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

// gatedUpstream is upstream whose FIRST call blocks until release closes: a
// read that went upstream before a write committed and is still in flight.
func gatedUpstream(calls *atomic.Int64, release <-chan struct{}) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		n := calls.Add(1)
		if n == 1 {
			<-release
		}
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintf(w, `{"n":%d}`, n)
	})
}

func waitForCalls(t *testing.T, calls *atomic.Int64, want int64) {
	t.Helper()
	deadline := time.After(2 * time.Second)
	for calls.Load() < want {
		select {
		case <-deadline:
			t.Fatalf("upstream calls = %d, want %d", calls.Load(), want)
		case <-time.After(5 * time.Millisecond):
		}
	}
}

// A read that went upstream before a write committed returns its pre-write
// body AFTER the write's invalidation ran — and found nothing to evict, the
// entry not existing yet. Storing that body served the pre-export teams list
// as a HIT for a whole TTL.
func TestFlightStartedBeforeInvalidationIsNotStored(t *testing.T) {
	var calls atomic.Int64
	release := make(chan struct{})
	c := testCache(t)
	h := c.Wrap(gatedUpstream(&calls, release), Rule{Extract: FromQuery("tournament_id")})
	const target = "/api/v1/teams?tournament_id=72"

	done := make(chan struct{})
	go func() { defer close(done); doGet(h, target, "") }()
	waitForCalls(t, &calls, 1)
	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.teams"))
	close(release)
	<-done

	if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") == "HIT" {
		t.Fatalf("pre-invalidation body %s was stored and served as a HIT", rec.Body.String())
	}
}

// A request arriving after the invalidation must not be handed the in-flight
// pre-write body by joining that flight, and the late pre-write body must not
// overwrite the fresh entry its own flight stored.
func TestRequestAfterInvalidationDoesNotJoinEarlierFlight(t *testing.T) {
	var calls atomic.Int64
	release := make(chan struct{})
	releaseOnce := sync.OnceFunc(func() { close(release) })
	defer releaseOnce()
	c := testCache(t)
	h := c.Wrap(gatedUpstream(&calls, release), Rule{Extract: FromQuery("tournament_id")})
	const target = "/api/v1/teams?tournament_id=72"

	early := make(chan struct{})
	go func() { defer close(early); doGet(h, target, "") }()
	waitForCalls(t, &calls, 1)
	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.teams"))

	late := make(chan *httptest.ResponseRecorder, 1)
	go func() { late <- doGet(h, target, "") }()
	select {
	case rec := <-late:
		if rec.Body.String() != `{"n":2}` {
			t.Fatalf("late request got %s, want a fresh upstream read", rec.Body.String())
		}
	case <-time.After(2 * time.Second):
		t.Fatal("request after the invalidation joined the flight that went upstream before it")
	}
	releaseOnce()
	<-early

	if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") != "HIT" || rec.Body.String() != `{"n":2}` {
		t.Fatalf("got %s (X-Cache %q), want the post-invalidation entry", rec.Body.String(), rec.Header().Get("X-Cache"))
	}
}

// The invalidation lands here right after the writer's commit; a service
// caching the same read misses it at that commit, unless the generation bump
// failed and only the outbox relay re-bumps it. A fill in that gap may carry
// the upstream's pre-write copy, so it lives only until upstreamSettle passes;
// a fill after the window gets the full TTL.
func TestFillRightAfterInvalidationLivesOnlyTheSettleWindow(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	fake := time.Now()
	c.now = func() time.Time { return fake }
	h := c.Wrap(upstream(&calls), Rule{Extract: FromQuery("tournament_id")})
	const target = "/api/v1/teams?tournament_id=72"

	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.teams"))
	fake = fake.Add(time.Second)
	doGet(h, target, "")
	if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("a fill inside the settle window must still absorb the herd")
	}
	fake = fake.Add(upstreamSettle)
	if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") == "HIT" {
		t.Fatal("a fill inside the settle window outlived it")
	}
	fake = fake.Add(time.Minute - time.Second)
	if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("a fill after the settle window must live its full TTL")
	}
}

// The LRU bound: a flood of distinct anonymous URLs must never grow the map
// past max, and must evict oldest-used first.
func TestLRUBound(t *testing.T) {
	var calls atomic.Int64
	c := newCache(time.Minute, 3, maxTotalBytes, slog.Default())
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
	c.Broadcast("tournament:72:invalidation", nil) // must not panic
	c.Reset()                                      // nor this
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

// The byte budget: entries are evicted oldest-first once their combined size
// would exceed maxBytes, even when the entry count is still under max. This
// is what makes raising maxBodyBytes safe — a cache full of large bodies
// cannot grow past a bounded memory footprint. The client-chosen key counts
// too: with bodies alone, all four entries fit this budget.
func TestByteBudgetEvictsOldestOnOverflow(t *testing.T) {
	var calls atomic.Int64
	const bodySize = 100
	// Every key here has the same length (single-digit page).
	entrySize := int64(bodySize + len("/api/v1/encounters?page=1&tournament_id=72"))
	c := newCache(time.Minute, maxEntries, 3*entrySize, slog.Default())
	body := make([]byte, bodySize)
	h := c.Wrap(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		_, _ = w.Write(body)
	}), Rule{Extract: FromQuery("tournament_id")})

	for i := 1; i <= 4; i++ {
		doGet(h, fmt.Sprintf("/api/v1/encounters?tournament_id=72&page=%d", i), "")
	}
	if len(c.keys) != 3 {
		t.Fatalf("cache grew past the byte budget: %d entries", len(c.keys))
	}
	if c.totalBytes > 3*entrySize {
		t.Fatalf("totalBytes = %d, want <= %d", c.totalBytes, 3*entrySize)
	}
	// page=1 (oldest) evicted for space; page=4 present.
	if rec := doGet(h, "/api/v1/encounters?tournament_id=72&page=4", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("newest entry evicted")
	}
	before := calls.Load()
	doGet(h, "/api/v1/encounters?tournament_id=72&page=1", "")
	if calls.Load() != before+1 {
		t.Fatal("oldest entry survived past the byte budget")
	}
}

// A single entry within maxBodyBytes but larger than the whole configured
// byte budget must still be stored (and served as a HIT) rather than being
// endlessly evicted-and-skipped; store() must terminate its eviction loop.
func TestByteBudgetSmallerThanSingleEntryStillStores(t *testing.T) {
	var calls atomic.Int64
	body := make([]byte, 200)
	c := newCache(time.Minute, maxEntries, 50, slog.Default())
	h := c.Wrap(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		_, _ = w.Write(body)
	}), Rule{Extract: FromPathValue("id")})

	doGet(h, "/api/v1/tournaments/72", "")
	if rec := doGet(h, "/api/v1/tournaments/72", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("entry over budget but under maxBodyBytes must still be cached")
	}
	if calls.Load() != 1 {
		t.Fatalf("calls = %d, want 1", calls.Load())
	}
}

// A slug-shaped path segment (Extract fails to parse it as an id) must not
// silently bypass the cache when the rule carries ExtractFromBody: the first
// request populates the entry from the response's own numeric "id", and a
// repeat request for the same slug URL is a HIT.
func TestSlugPathFallsBackToBodyExtractedID(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstreamTournament(&calls, 72), Rule{
		Extract:         FromPathValue("id"),
		ExtractFromBody: ExtractIDFromJSONBody(),
	})

	first := doGetWithID(h, "/api/v1/tournaments/overwatch-season-5", "overwatch-season-5", "")
	second := doGetWithID(h, "/api/v1/tournaments/overwatch-season-5", "overwatch-season-5", "")

	if calls.Load() != 1 {
		t.Fatalf("upstream calls = %d, want 1", calls.Load())
	}
	if got := second.Header().Get("X-Cache"); got != "HIT" {
		t.Fatalf("X-Cache = %q, want HIT", got)
	}
	if first.Body.String() != second.Body.String() {
		t.Fatalf("cached body diverged: %q vs %q", first.Body.String(), second.Body.String())
	}
	// invalidate(72, ...) must reach it too: the entry was indexed under the
	// numeric id extracted from the body, not the unparseable path segment.
	if n := c.invalidate(scopeKey{id: 72}, nil); n != 1 {
		t.Fatalf("invalidate(72, nil) = %d, want 1 (slug entry unreachable)", n)
	}
	doGetWithID(h, "/api/v1/tournaments/overwatch-season-5", "overwatch-season-5", "")
	if calls.Load() != 2 {
		t.Fatalf("calls = %d, want 2 after invalidation", calls.Load())
	}
}

// Without ExtractFromBody, a slug-shaped segment keeps bypassing the cache
// exactly like the pre-existing numeric-id-missing case — the fallback is
// opt-in per rule, so every other route's behavior is unchanged.
func TestSlugPathWithoutBodyFallbackBypassesCache(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstreamTournament(&calls, 72), Rule{Extract: FromPathValue("id")})

	for range 2 {
		rec := doGetWithID(h, "/api/v1/tournaments/overwatch-season-5", "overwatch-season-5", "")
		if rec.Header().Get("X-Cache") != "" {
			t.Fatal("slug request without ExtractFromBody must bypass the cache")
		}
	}
	if calls.Load() != 2 {
		t.Fatalf("calls = %d, want 2 (no caching)", calls.Load())
	}
}

// registration_changed must still evict the tournament-detail entry when it
// was reached (and cached) via its slug rather than its numeric id — the
// bareTournamentDetailPattern shape check does not depend on knowing the
// segment's literal text the way the old numeric-id substring did.
func TestBroadcastRegistrationChangedEvictsSlugKeyedDetailEntry(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstreamTournament(&calls, 72), Rule{
		Extract:         FromPathValue("id"),
		ExtractFromBody: ExtractIDFromJSONBody(),
	})

	doGetWithID(h, "/api/v1/tournaments/overwatch-season-5", "overwatch-season-5", "")

	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.registrations"))

	rec := doGetWithID(h, "/api/v1/tournaments/overwatch-season-5", "overwatch-season-5", "")
	if rec.Header().Get("X-Cache") == "HIT" {
		t.Fatal("registration_changed must evict the slug-keyed tournament-detail entry")
	}
}

// The shape check must not overreach onto a sibling sub-route (e.g. /stages)
// sharing the same slug prefix, mirroring the numeric-id "?" boundary case.
func TestBareTournamentDetailPatternDoesNotOverreachOntoSlugSubroutes(t *testing.T) {
	var detailCalls, stagesCalls atomic.Int64
	c := testCache(t)
	detailHandler := c.Wrap(upstreamTournament(&detailCalls, 72), Rule{
		Extract:         FromPathValue("id"),
		ExtractFromBody: ExtractIDFromJSONBody(),
	})
	stagesHandler := c.Wrap(upstreamTournament(&stagesCalls, 72), Rule{
		Extract:         FromPathValue("id"),
		ExtractFromBody: ExtractIDFromJSONBody(),
	})

	doGetWithID(detailHandler, "/api/v1/tournaments/overwatch-season-5", "overwatch-season-5", "")
	stagesReq := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments/overwatch-season-5/stages", nil)
	stagesReq.SetPathValue("id", "overwatch-season-5")
	stagesHandler.ServeHTTP(httptest.NewRecorder(), stagesReq)

	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.registrations"))

	stagesReq2 := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments/overwatch-season-5/stages", nil)
	stagesReq2.SetPathValue("id", "overwatch-season-5")
	rec := httptest.NewRecorder()
	stagesHandler.ServeHTTP(rec, stagesReq2)
	if rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("registration_changed must not evict the slug-keyed /stages entry")
	}
}

// Draft entries live under their session: a board frame drops that session's
// board entries only — not its chat, not another session's board, and never a
// tournament sharing the numeric id — and a chat frame likewise. A draft frame
// needs no payload: any frame on the topic means the session moved.
func TestDraftTopicsDropOnlyTheirOwnSessionScope(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	board := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id"), Scope: ScopeDraftBoard})
	chat := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id"), Scope: ScopeDraftChat})
	tournament := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id")})
	routes := []struct {
		name, target, id string
		h                http.Handler
	}{
		{"board 5", "/api/v1/balancer/draft/sessions/5/board", "5", board},
		{"board 6", "/api/v1/balancer/draft/sessions/6/board", "6", board},
		{"chat 5", "/api/v1/balancer/draft/sessions/5/chat?limit=50", "5", chat},
		{"chat 6", "/api/v1/balancer/draft/sessions/6/chat?limit=50", "6", chat},
		{"tournament 5", "/api/v1/tournaments/5", "5", tournament},
	}
	for _, r := range routes {
		doGetWithID(r.h, r.target, r.id, "")
	}

	for _, tc := range []struct {
		topic   string
		dropped string
	}{
		{"draft:5:board", "board 5"},
		{"draft:5:chat", "chat 5"},
		{"draft:6:board", "board 6"},
		{"draft:6:chat", "chat 6"},
		{"tournament:5:invalidation", "tournament 5"},
	} {
		c.Broadcast(tc.topic, nil)
		// Every route is re-checked (a dropped one refills on this read), so
		// each case starts from a fully cached set.
		for _, r := range routes {
			if hit := doGetWithID(r.h, r.target, r.id, "").Header().Get("X-Cache") == "HIT"; hit == (r.name == tc.dropped) {
				t.Errorf("%s: %s HIT=%v", tc.topic, r.name, hit)
			}
		}
	}
}

// The tournament draft lookup is addressed by tournament but holds the active
// session's board: it is cached under the session its body names and dropped
// by that session's board frame alone. No active draft answers null (or
// nothing), which no frame could ever reach, so it stays uncached.
func TestDraftLookupCachedUnderBodySession(t *testing.T) {
	var calls atomic.Int64
	body := `{"session":{"id":5,"status":"live"},"picks":[]}`
	c := testCache(t)
	h := c.Wrap(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		_, _ = fmt.Fprint(w, body)
	}), Rule{Scope: ScopeDraftBoard, ExtractFromBody: ExtractSessionIDFromJSONBody()})
	const target = "/api/v1/balancer/draft/tournaments/72/draft"

	doGet(h, target, "")
	if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("the lookup must be cached under its body's session")
	}
	c.Broadcast("tournament:72:invalidation", nil)
	c.Broadcast("draft:6:board", nil)
	c.Broadcast("draft:5:chat", nil)
	if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("only the session's own board frame may drop the lookup")
	}
	c.Broadcast("draft:5:board", nil)
	if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") == "HIT" {
		t.Fatal("the session's board frame must drop the lookup")
	}

	for _, empty := range []string{"null", ""} {
		body = empty
		before := calls.Load()
		doGet(h, "/api/v1/balancer/draft/tournaments/73/draft", "")
		doGet(h, "/api/v1/balancer/draft/tournaments/73/draft", "")
		if calls.Load()-before != 2 {
			t.Fatalf("body %q was stored", empty)
		}
	}
}

// The generation guard holds per session: a board read that went upstream
// before the session's frame is neither joined by a request arriving after
// the frame nor stored over the fresh entry that request fills.
func TestFlightStartedBeforeDraftFrameIsNotStored(t *testing.T) {
	var calls atomic.Int64
	release := make(chan struct{})
	releaseOnce := sync.OnceFunc(func() { close(release) })
	defer releaseOnce()
	c := testCache(t)
	h := c.Wrap(gatedUpstream(&calls, release), Rule{Extract: FromPathValue("id"), Scope: ScopeDraftBoard})
	const target = "/api/v1/balancer/draft/sessions/72/board"

	early := make(chan struct{})
	go func() { defer close(early); doGet(h, target, "") }()
	waitForCalls(t, &calls, 1)
	c.Broadcast("draft:72:board", nil)

	late := make(chan *httptest.ResponseRecorder, 1)
	go func() { late <- doGet(h, target, "") }()
	select {
	case rec := <-late:
		if rec.Body.String() != `{"n":2}` {
			t.Fatalf("late request got %s, want a fresh upstream read", rec.Body.String())
		}
	case <-time.After(2 * time.Second):
		t.Fatal("request after the board frame joined the flight that went upstream before it")
	}
	releaseOnce()
	<-early

	if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") != "HIT" || rec.Body.String() != `{"n":2}` {
		t.Fatalf("got %s (X-Cache %q), want the post-frame entry", rec.Body.String(), rec.Header().Get("X-Cache"))
	}
}

// A rule's own TTL (the live draft reads) expires its entry while a
// default-TTL entry stored at the same moment survives.
func TestRuleTTLOverridesCacheDefault(t *testing.T) {
	var draftCalls, tournamentCalls atomic.Int64
	c := testCache(t)
	fake := time.Now()
	c.now = func() time.Time { return fake }
	draft := c.Wrap(upstream(&draftCalls), Rule{Extract: FromPathValue("id"), Scope: ScopeDraftBoard, TTL: 5 * time.Second})
	tournament := c.Wrap(upstream(&tournamentCalls), Rule{Extract: FromPathValue("id")})
	const draftTarget, tournamentTarget = "/api/v1/balancer/draft/sessions/72/board", "/api/v1/tournaments/72"

	doGet(draft, draftTarget, "")
	doGet(tournament, tournamentTarget, "")
	fake = fake.Add(4 * time.Second)
	if rec := doGet(draft, draftTarget, ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("draft entry expired before its own TTL")
	}
	fake = fake.Add(2 * time.Second)
	if rec := doGet(draft, draftTarget, ""); rec.Header().Get("X-Cache") == "HIT" {
		t.Fatal("draft entry outlived its own TTL")
	}
	if rec := doGet(tournament, tournamentTarget, ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("default-TTL entry expired with the draft rule's TTL")
	}
}

// tournament.structure also carries a visibility flip (is_hidden): no
// anonymous entry of the tournament may survive it. The shell-only pattern
// set left the participants list and a player's page for that tournament
// serving a now-hidden tournament for a whole TTL. Another tournament's
// entries stay.
func TestBroadcastStructureDropsTheWholeTournament(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id")})
	targets := []string{
		"/api/v1/tournaments/72/registration/list",
		"/api/v1/users/5/tournaments/72/leaderboard",
		"/api/v1/tournaments/72",
	}
	for _, target := range targets {
		doGet(h, target, "")
	}
	const other = "/api/v1/tournaments/73/registration/list"
	doGetWithID(h, other, "73", "")

	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.structure"))

	for _, target := range targets {
		if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") == "HIT" {
			t.Fatalf("%s survived tournament.structure", target)
		}
	}
	if rec := doGetWithID(h, other, "73", ""); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatal("tournament 73 must survive 72's structure frame")
	}
}

// Parsed logs emit only tournament.encounters / tournament.standings, and a
// player's pages for that tournament (stats.PublicCacheableReads) render
// both, so either must drop them — while the player's TTL-only profile
// (scope id 0) stays.
func TestResultEventsEvictPlayerTournamentPages(t *testing.T) {
	for _, resource := range []string{"tournament.encounters", "tournament.standings"} {
		t.Run(resource, func(t *testing.T) {
			var calls atomic.Int64
			c := testCache(t)
			perTournament := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id")})
			profile := c.Wrap(upstream(&calls), Rule{Extract: TTLOnly()})
			targets := []string{
				"/api/v1/users/5/tournaments/72",
				"/api/v1/users/5/tournaments/72/encounters",
				"/api/v1/users/5/tournaments/72/leaderboard",
			}
			for _, target := range targets {
				doGet(perTournament, target, "")
			}
			doGet(profile, "/api/v1/users/5/profile", "")

			c.Broadcast("tournament:72:invalidation", invalidationFrame(resource))

			for _, target := range targets {
				if rec := doGet(perTournament, target, ""); rec.Header().Get("X-Cache") == "HIT" {
					t.Fatalf("%s survived %s", target, resource)
				}
			}
			if rec := doGet(profile, "/api/v1/users/5/profile", ""); rec.Header().Get("X-Cache") != "HIT" {
				t.Fatalf("%s must not reach the TTL-only profile", resource)
			}
		})
	}
}

// Invalidation records are bookkeeping for fills, not history: past the
// settle window with no older fill in flight, the next invalidation drops
// them. They used to accumulate one per scope ever invalidated.
func TestInvalidationRecordsPrunedAfterSettle(t *testing.T) {
	c := testCache(t)
	fake := time.Now()
	c.now = func() time.Time { return fake }

	c.Broadcast("tournament:72:invalidation", nil)
	fake = fake.Add(upstreamSettle)
	c.Broadcast("tournament:73:invalidation", nil)
	if _, ok := c.invalidated[scopeKey{id: 72}]; ok || len(c.invalidated) != 1 {
		t.Fatalf("records = %v, want only tournament 73's", c.invalidated)
	}
}

// Pruning must not reopen the stale-fill race: a fill that went upstream
// before an invalidation keeps that record, however long it runs, and is
// still refused when it lands; only then may the record go.
func TestPruneKeepsRecordAnOlderFillNeeds(t *testing.T) {
	var calls atomic.Int64
	release := make(chan struct{})
	c := testCache(t)
	fake := time.Now()
	c.now = func() time.Time { return fake }
	h := c.Wrap(gatedUpstream(&calls, release), Rule{Extract: FromQuery("tournament_id")})
	const target = "/api/v1/teams?tournament_id=72"
	pending := scopeKey{id: 72}

	done := make(chan struct{})
	go func() { defer close(done); doGet(h, target, "") }()
	waitForCalls(t, &calls, 1)
	c.Broadcast("tournament:72:invalidation", invalidationFrame("tournament.teams"))
	fake = fake.Add(2 * upstreamSettle)
	c.Broadcast("tournament:73:invalidation", nil)
	if _, ok := c.invalidated[pending]; !ok {
		t.Fatal("record pruned while a fill that predates it is still in flight")
	}
	close(release)
	<-done
	if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") == "HIT" {
		t.Fatalf("pre-invalidation body %s was stored and served as a HIT", rec.Body.String())
	}

	c.Broadcast("tournament:74:invalidation", nil)
	if _, ok := c.invalidated[pending]; ok {
		t.Fatal("record outlived the fill it was kept for")
	}
}

// Reset (the subscriber re-subscribed after a lost connection, so frames may
// be missing) drops every entry — TTL-only ones included — refuses a fill
// that went upstream before it, and keeps requests after it off that fill.
func TestResetDropsEntriesAndFencesInflightFills(t *testing.T) {
	var seeded, calls atomic.Int64
	release := make(chan struct{})
	releaseOnce := sync.OnceFunc(func() { close(release) })
	defer releaseOnce()
	c := testCache(t)
	stored := c.Wrap(upstream(&seeded), Rule{Extract: TTLOnly()})
	gated := c.Wrap(gatedUpstream(&calls, release), Rule{Extract: FromQuery("tournament_id")})
	const target = "/api/v1/teams?tournament_id=72"

	doGet(stored, "/api/v1/statistics/champion", "")
	early := make(chan struct{})
	go func() { defer close(early); doGet(gated, target, "") }()
	waitForCalls(t, &calls, 1)

	c.Reset()

	if rec := doGet(stored, "/api/v1/statistics/champion", ""); rec.Header().Get("X-Cache") == "HIT" {
		t.Fatal("Reset left an entry in place")
	}
	late := make(chan *httptest.ResponseRecorder, 1)
	go func() { late <- doGet(gated, target, "") }()
	select {
	case rec := <-late:
		if rec.Body.String() != `{"n":2}` {
			t.Fatalf("late request got %s, want a fresh upstream read", rec.Body.String())
		}
	case <-time.After(2 * time.Second):
		t.Fatal("request after Reset joined the flight that went upstream before it")
	}
	releaseOnce()
	<-early

	if rec := doGet(gated, target, ""); rec.Header().Get("X-Cache") != "HIT" || rec.Body.String() != `{"n":2}` {
		t.Fatalf("got %s (X-Cache %q), want the post-Reset entry", rec.Body.String(), rec.Header().Get("X-Cache"))
	}
}

// A key past maxKeyBytes (a client-chosen query string) bypasses the cache
// instead of being retained at whatever length the client picked.
func TestOversizedKeyBypassesCache(t *testing.T) {
	var calls atomic.Int64
	c := testCache(t)
	h := c.Wrap(upstream(&calls), Rule{Extract: FromPathValue("id")})
	target := "/api/v1/tournaments/72?q=" + strings.Repeat("a", maxKeyBytes)

	doGet(h, target, "")
	if rec := doGet(h, target, ""); rec.Header().Get("X-Cache") != "" || calls.Load() != 2 || len(c.keys) != 0 {
		t.Fatalf("oversized key cached: X-Cache %q, calls %d, entries %d", rec.Header().Get("X-Cache"), calls.Load(), len(c.keys))
	}
}

// bigJSON is a compressible body past gzipMinBytes.
var bigJSON = "[" + strings.Repeat(`{"team":"Blue","score":3},`, 100) + `{}]`

func doGetAccepting(h http.Handler, target, acceptEncoding string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, target, nil)
	req.SetPathValue("id", "72")
	if acceptEncoding != "" {
		req.Header.Set("Accept-Encoding", acceptEncoding)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

// A stored body is gzipped once: a hit whose client accepts gzip gets that
// copy, any other gets identity, the leader's own miss stays as upstream
// wrote it, and a body under gzipMinBytes is never compressed. Every answer
// varies on Accept-Encoding, so nothing downstream mixes the two up.
func TestHitServesStoredGzipCopy(t *testing.T) {
	var calls, smallCalls atomic.Int64
	c := testCache(t)
	h := c.Wrap(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, bigJSON)
	}), Rule{Extract: FromPathValue("id")})
	small := c.Wrap(upstream(&smallCalls), Rule{Extract: FromPathValue("id")})
	const target = "/api/v1/tournaments/72"

	check := func(rec *httptest.ResponseRecorder, wantGzip bool) {
		t.Helper()
		if got := rec.Header().Values("Vary"); len(got) != 1 || got[0] != "Accept-Encoding" {
			t.Fatalf("Vary = %q, want [Accept-Encoding]", got)
		}
		body := rec.Body.String()
		if rec.Header().Get("Content-Encoding") == "gzip" {
			if !wantGzip {
				t.Fatal("gzip served to a client that did not accept it")
			}
			zr, err := gzip.NewReader(rec.Body)
			if err != nil {
				t.Fatalf("gzip reader: %v", err)
			}
			raw, err := io.ReadAll(zr)
			if err != nil {
				t.Fatalf("gunzip: %v", err)
			}
			body = string(raw)
		} else if wantGzip {
			t.Fatal("identity served to a client that accepts gzip")
		}
		if body != bigJSON {
			t.Fatalf("body did not round-trip: %d bytes", len(body))
		}
	}

	leader := doGetAccepting(h, target, "gzip")
	check(leader, false)
	if got := leader.Header().Get("X-Cache"); got != "MISS" {
		t.Fatalf("X-Cache = %q, want MISS", got)
	}
	for _, ae := range []string{"gzip", "deflate, gzip;q=0.5", "*"} {
		rec := doGetAccepting(h, target, ae)
		if rec.Header().Get("X-Cache") != "HIT" {
			t.Fatalf("Accept-Encoding %q: not a HIT", ae)
		}
		check(rec, true)
	}
	for _, ae := range []string{"", "gzip;q=0", "br", "*;q=0"} {
		check(doGetAccepting(h, target, ae), false)
	}
	if calls.Load() != 1 {
		t.Fatalf("upstream calls = %d, want 1", calls.Load())
	}

	doGetAccepting(small, "/api/v1/tournaments/72/stages", "gzip")
	if rec := doGetAccepting(small, "/api/v1/tournaments/72/stages", "gzip"); rec.Header().Get("Content-Encoding") != "" {
		t.Fatal("a body under gzipMinBytes was compressed")
	}
}

func TestAcceptsGzip(t *testing.T) {
	cases := []struct {
		values []string
		want   bool
	}{
		{nil, false},
		{[]string{"gzip"}, true},
		{[]string{"GZip"}, true},
		{[]string{"x-gzip"}, true},
		{[]string{"gzip, deflate, br, zstd"}, true},
		{[]string{"gzip;q=0"}, false},
		{[]string{"gzip; q=0.000"}, false},
		{[]string{"gzip;q=0.001"}, true},
		{[]string{"gzip;q=bogus"}, false},
		{[]string{"deflate, br"}, false},
		{[]string{"*"}, true},
		{[]string{"*;q=0"}, false},
		{[]string{"br, *;q=0, gzip"}, true},
		{[]string{"*, gzip;q=0"}, false},
		{[]string{"br", "gzip"}, true},
	}
	for _, tc := range cases {
		if got := acceptsGzip(tc.values); got != tc.want {
			t.Errorf("acceptsGzip(%q) = %v, want %v", tc.values, got, tc.want)
		}
	}
}
