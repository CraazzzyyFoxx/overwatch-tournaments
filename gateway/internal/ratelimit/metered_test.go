package ratelimit

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// ceilings answers WorkspaceLimitFunc from a map: a missing id is a workspace
// that does not exist, a negative value one with no ceiling at all.
func ceilings(limits map[int64]int) WorkspaceLimitFunc {
	return func(_ context.Context, id int64) (int, bool, bool, error) {
		limit, ok := limits[id]
		switch {
		case !ok:
			return 0, false, false, nil
		case limit < 0:
			return 0, false, true, nil
		default:
			return limit, true, true, nil
		}
	}
}

func callerIs(c Caller) CallerFunc {
	return func(*http.Request) (Caller, bool) { return c, true }
}

// meteredReq is one request to a tenant-addressed route. token "" makes it
// anonymous (no Authorization header at all), which is what isAnonymous reads.
func meteredReq(token string, workspaceID string) *http.Request {
	target := "/api/v1/teams"
	if workspaceID != "" {
		target += "?workspace_id=" + workspaceID
	}
	r := httptest.NewRequest("GET", target, nil)
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	return r
}

func session(workspaces ...int64) Caller {
	return Caller{WorkspaceIDs: workspaces}
}

// TestWrapMetered_SessionCountsAgainstItsWorkspace is the gap this whole layer
// exists to close: a browser session spends the tenant's budget too, on the
// same bucket the Python enforcer reads — and gets no RateLimit-* headers,
// because a session has no published per-request budget to pace against.
func TestWrapMetered_SessionCountsAgainstItsWorkspace(t *testing.T) {
	srv, l, _ := sharedLimiter(t, 60)
	calls := 0
	h := l.WrapMetered(okHandler(&calls), callerIs(session(5)), ceilings(map[int64]int{5: 100}))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, meteredReq("tok", "5"))
	if rec.Code != http.StatusOK || calls != 1 {
		t.Fatalf("want one served request, got %d / %d calls", rec.Code, calls)
	}
	if got, err := srv.Get("q:ws:5:rpm"); err != nil || got != "1" {
		t.Fatalf("q:ws:5:rpm must hold the workspace count, got %q (%v)", got, err)
	}
	if ttl := srv.TTL("q:ws:5:rpm"); ttl != time.Minute {
		t.Fatalf("the workspace window must expire after a minute, got %s", ttl)
	}
	if srv.Exists("q:key:0:rpm") || srv.Exists("q:pub:ws:5:rpm") {
		t.Fatalf("a member session charges the workspace bucket only: %v", srv.Keys())
	}
	if rec.Header().Get("RateLimit-Limit") != "" {
		t.Fatalf("a session must not be told a per-request budget it does not have")
	}
}

// TestWrapMetered_WorkspaceCeilingRefusesAllOrNothing is the enforcement
// contract plus its most important detail: the refused request charges NOTHING,
// so a client whose tenant is full does not also burn its own key budget.
func TestWrapMetered_WorkspaceCeilingRefusesAllOrNothing(t *testing.T) {
	srv, l, _ := sharedLimiter(t, 60)
	layers := []string{}
	l.local.OnReject(func(layer string) { layers = append(layers, layer) })
	calls := 0
	key := Caller{APIKey: true, APIKeyID: 7, RequestsPerMinute: 100, WorkspaceID: 5}
	h := l.WrapMetered(okHandler(&calls), callerIs(key), ceilings(map[int64]int{5: 1}))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, meteredReq("owt_sk_x", ""))
	if rec.Code != http.StatusOK {
		t.Fatalf("first request within the 1/min workspace ceiling: got %d", rec.Code)
	}

	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, meteredReq("owt_sk_x", ""))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("second request over the workspace ceiling: want 429, got %d", rec.Code)
	}
	if calls != 1 {
		t.Fatalf("the refused request must not reach the handler: %d calls", calls)
	}
	if got, _ := srv.Get("q:key:7:rpm"); got != "1" {
		t.Fatalf("a workspace refusal must not charge the key bucket, got %q", got)
	}
	if got, _ := srv.Get("q:ws:5:rpm"); got != "1" {
		t.Fatalf("a refusal must not charge the workspace bucket either, got %q", got)
	}
	if len(layers) != 1 || layers[0] != layerWorkspace {
		t.Fatalf("the refusal must be labelled %q, got %v", layerWorkspace, layers)
	}
	if got := rec.Header().Get("Retry-After"); got == "" || got == "0" {
		t.Fatalf("Retry-After must name the workspace window's reset, got %q", got)
	}
}

// TestWrapMetered_KeyRefusalLeavesTheWorkspaceUncounted is the same
// all-or-nothing rule from the other side: a key that outgrew its own budget
// must not inflate its tenant's usage with requests nobody served.
func TestWrapMetered_KeyRefusalLeavesTheWorkspaceUncounted(t *testing.T) {
	srv, l, _ := sharedLimiter(t, 60)
	layers := []string{}
	l.local.OnReject(func(layer string) { layers = append(layers, layer) })
	calls := 0
	key := Caller{APIKey: true, APIKeyID: 7, RequestsPerMinute: 1, WorkspaceID: 5}
	h := l.WrapMetered(okHandler(&calls), callerIs(key), ceilings(map[int64]int{5: -1}))

	for range 2 {
		h.ServeHTTP(httptest.NewRecorder(), meteredReq("owt_sk_x", ""))
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, meteredReq("owt_sk_x", ""))
	if rec.Code != http.StatusTooManyRequests || calls != 1 {
		t.Fatalf("want the 2nd request refused on the key budget: code %d, %d calls", rec.Code, calls)
	}
	if got, _ := srv.Get("q:key:7:rpm"); got != "1" {
		t.Fatalf("the key bucket must stop at its budget, got %q", got)
	}
	if got, _ := srv.Get("q:ws:5:rpm"); got != "1" {
		t.Fatalf("a key refusal must not charge the workspace, got %q", got)
	}
	if len(layers) != 2 || layers[0] != layerAPIKey {
		t.Fatalf("a key refusal keeps the %q label, got %v", layerAPIKey, layers)
	}
	if rec.Header().Get("RateLimit-Limit") != "1" {
		t.Fatalf("the key's RateLimit-* triple must survive, got %q", rec.Header().Get("RateLimit-Limit"))
	}
}

// TestWrapMetered_AnonymousIsStatisticsOnly: a tenant's public page views are
// worth counting and must never be refusable — otherwise anyone could take a
// workspace offline by spending its budget from the outside.
func TestWrapMetered_AnonymousIsStatisticsOnly(t *testing.T) {
	srv, l, _ := sharedLimiter(t, 60)
	calls := 0
	h := l.WrapMetered(okHandler(&calls), callerIs(session(5)), ceilings(map[int64]int{5: 1}))

	for i := range 3 {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, meteredReq("", "5"))
		if rec.Code != http.StatusOK {
			t.Fatalf("anonymous request %d must never be refused, got %d", i, rec.Code)
		}
	}
	if got, _ := srv.Get("q:pub:ws:5:rpm"); got != "3" {
		t.Fatalf("public traffic must be counted, got %q", got)
	}
	if srv.Exists("q:ws:5:rpm") {
		t.Fatalf("anonymous traffic must not spend the tenant's own budget: %v", srv.Keys())
	}
	if calls != 3 {
		t.Fatalf("every anonymous request must be served, got %d", calls)
	}
}

// TestWrapMetered_NonMemberSessionIsPublic covers the attribution rule that
// makes the public bucket more than an anonymous one: being signed in somewhere
// else does not make you a tenant's user.
func TestWrapMetered_NonMemberSessionIsPublic(t *testing.T) {
	srv, l, _ := sharedLimiter(t, 60)
	calls := 0
	h := l.WrapMetered(okHandler(&calls), callerIs(session(9)), ceilings(map[int64]int{5: 1, 9: 100}))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, meteredReq("tok", "5"))
	if rec.Code != http.StatusOK {
		t.Fatalf("a non-member read must not be refused, got %d", rec.Code)
	}
	if got, _ := srv.Get("q:pub:ws:5:rpm"); got != "1" {
		t.Fatalf("a non-member's traffic belongs in the public bucket, got %q", got)
	}
	if srv.Exists("q:ws:5:rpm") || srv.Exists("q:ws:9:rpm") {
		t.Fatalf("no metered bucket may be charged here: %v", srv.Keys())
	}
}

// TestWrapMetered_SuperuserIsMetered: a platform operator acting on a tenant is
// real traffic for that tenant, member row or not.
func TestWrapMetered_SuperuserIsMetered(t *testing.T) {
	srv, l, _ := sharedLimiter(t, 60)
	calls := 0
	h := l.WrapMetered(okHandler(&calls), callerIs(Caller{Superuser: true}), ceilings(map[int64]int{5: 100}))

	h.ServeHTTP(httptest.NewRecorder(), meteredReq("tok", "5"))
	if got, _ := srv.Get("q:ws:5:rpm"); got != "1" {
		t.Fatalf("a superuser's request must land on the workspace bucket, got %q", got)
	}
}

// TestWrapMetered_UnknownWorkspaceWritesNothing bounds the key space: the id is
// attacker-chosen (an anonymous query string), so a workspace that does not
// exist must create no Redis key at all.
func TestWrapMetered_UnknownWorkspaceWritesNothing(t *testing.T) {
	srv, l, _ := sharedLimiter(t, 60)
	calls := 0
	h := l.WrapMetered(okHandler(&calls), callerIs(session(5)), ceilings(map[int64]int{5: 100}))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, meteredReq("", "999999"))
	if rec.Code != http.StatusOK || calls != 1 {
		t.Fatalf("the request must still be served: %d / %d calls", rec.Code, calls)
	}
	if keys := srv.Keys(); len(keys) != 0 {
		t.Fatalf("a made-up workspace id must write nothing, got %v", keys)
	}
}

// TestWrapMetered_UnjudgeableIdentityPassesThrough: the route behind this layer
// answers 401/503 for a token that could not be validated; metering it would
// turn that honest answer into a 429.
func TestWrapMetered_UnjudgeableIdentityPassesThrough(t *testing.T) {
	srv, l, _ := sharedLimiter(t, 60)
	calls := 0
	who := func(*http.Request) (Caller, bool) { return Caller{}, false }
	h := l.WrapMetered(okHandler(&calls), who, ceilings(map[int64]int{5: 100}))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, meteredReq("bad", "5"))
	if rec.Code != http.StatusOK || calls != 1 {
		t.Fatalf("want an unmetered pass-through, got %d / %d calls", rec.Code, calls)
	}
	if keys := srv.Keys(); len(keys) != 0 {
		t.Fatalf("nothing may be charged for an unjudged identity, got %v", keys)
	}
}

// TestWrapMetered_KeyLimiterKillSwitch keeps GATEWAY_API_KEY_RATE_LIMIT<=0
// meaning exactly what it means today — no per-key bucket — without taking the
// workspace bucket with it.
func TestWrapMetered_KeyLimiterKillSwitch(t *testing.T) {
	srv, l, _ := sharedLimiter(t, 0)
	calls := 0
	key := Caller{APIKey: true, APIKeyID: 7, RequestsPerMinute: 0, WorkspaceID: 5}
	h := l.WrapMetered(okHandler(&calls), callerIs(key), ceilings(map[int64]int{5: 100}))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, meteredReq("owt_sk_x", ""))
	if srv.Exists("q:key:7:rpm") {
		t.Fatalf("a disabled per-key limiter must charge no key bucket")
	}
	if got, _ := srv.Get("q:ws:5:rpm"); got != "1" {
		t.Fatalf("the workspace bucket is governed by its own flag, got %q", got)
	}
	if rec.Header().Get("RateLimit-Limit") != "" {
		t.Fatalf("no key bucket means no RateLimit-* triple")
	}
}

// TestWrapMetered_FailsOpenWhenRedisIsDown keeps the availability choice of the
// single-bucket path: an unreachable counter costs accuracy, never uptime.
func TestWrapMetered_FailsOpenWhenRedisIsDown(t *testing.T) {
	srv, l, fallbacks := sharedLimiter(t, 60)
	srv.Close()
	calls := 0
	key := Caller{APIKey: true, APIKeyID: 7, RequestsPerMinute: 2, WorkspaceID: 5}
	h := l.WrapMetered(okHandler(&calls), callerIs(key), ceilings(map[int64]int{5: 1}))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, meteredReq("owt_sk_x", ""))
	if rec.Code != http.StatusOK || calls != 1 {
		t.Fatalf("want the request served, got %d / %d calls", rec.Code, calls)
	}
	if *fallbacks != 1 {
		t.Fatalf("the unmetered request must be counted, got %d", *fallbacks)
	}
	if got := rec.Header().Get("RateLimit-Remaining"); got != "2" {
		t.Fatalf("nothing was charged, so the full budget is the honest number: got %q", got)
	}
}

// TestWrapMetered_CeilingErrorStillCounts: a policy read that fails must not
// silently stop metering — usage keeps accruing, enforcement is what drops.
func TestWrapMetered_CeilingErrorStillCounts(t *testing.T) {
	srv, l, _ := sharedLimiter(t, 60)
	calls := 0
	failing := func(context.Context, int64) (int, bool, bool, error) {
		return 0, false, false, context.DeadlineExceeded
	}
	h := l.WrapMetered(okHandler(&calls), callerIs(session(5)), failing)

	for range 3 {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, meteredReq("tok", "5"))
		if rec.Code != http.StatusOK {
			t.Fatalf("an unreadable ceiling must enforce nothing, got %d", rec.Code)
		}
	}
	if got, _ := srv.Get("q:ws:5:rpm"); got != "3" {
		t.Fatalf("usage must still be counted, got %q", got)
	}
}
