package respcache

import (
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
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

	if n := c.Invalidate(72, nil); n != 2 {
		t.Fatalf("Invalidate(72, nil) = %d, want 2", n)
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

// Broadcast consumes ONLY `<scope>:invalidation`. Domain topics carry data for
// the UI: a draft pick or a balancer presence heartbeat must not touch the
// cache, which is exactly the mistake the previous rail made (a reason-less
// draft frame dropped every entry for the tournament, twice per pick).
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

// tournament.registration_form is admin configuration: nothing here caches the
// form route, so its manifest entry is an EMPTY pattern set and the event must
// evict nothing. A missing entry would instead mean "drop everything".
func TestBroadcastFormChangedEvictsNothing(t *testing.T) {
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
	if rec2.Header().Get("X-Cache") != "HIT" {
		t.Fatal("form edit must not evict the registration/list entry")
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
	if c.Invalidate(72, nil) != 0 {
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

// The byte budget: entries are evicted oldest-first once their combined size
// would exceed maxBytes, even when the entry count is still under max. This
// is what makes raising maxBodyBytes safe — a cache full of large bodies
// cannot grow past a bounded memory footprint.
func TestByteBudgetEvictsOldestOnOverflow(t *testing.T) {
	var calls atomic.Int64
	const entrySize = 100
	c := newCache(time.Minute, maxEntries, 3*entrySize, slog.Default())
	body := make([]byte, entrySize)
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
	// Invalidate(72, ...) must reach it too: the entry was indexed under the
	// numeric id extracted from the body, not the unparseable path segment.
	if n := c.Invalidate(72, nil); n != 1 {
		t.Fatalf("Invalidate(72, nil) = %d, want 1 (slug entry unreachable)", n)
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
