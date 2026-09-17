package ratelimit

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

// TestLimiter_Allow_NilLimiterAlwaysAllows proves the nil-safety guarantee
// callers rely on (see ws.Handler.customDomainLimiter): a nil *Limiter
// behaves like a disabled one, so an optional *Limiter field can be left nil
// without a separate check at every call site.
func TestLimiter_Allow_NilLimiterAlwaysAllows(t *testing.T) {
	var l *Limiter
	for i := 0; i < 5; i++ {
		if !l.Allow("some-key") {
			t.Fatalf("call %d: nil *Limiter should always allow", i)
		}
	}
}

// TestLimiter_Allow_DisabledLimiterAlwaysAllows mirrors the nil case for a
// zero-value/non-positive-limit Limiter, i.e. what ratelimit.New returns
// when the operator sets a rate limit <= 0.
func TestLimiter_Allow_DisabledLimiterAlwaysAllows(t *testing.T) {
	l := New(0, 0)
	for i := 0; i < 5; i++ {
		if !l.Allow("some-key") {
			t.Fatalf("call %d: a disabled Limiter should always allow", i)
		}
	}
}

// TestLimiter_Allow_BoundsBurstsPerKey proves Allow enforces the same bucket
// Wrap does: within one burst window, only `limit` calls for a given key
// succeed; the next one is rejected until tokens refill.
func TestLimiter_Allow_BoundsBurstsPerKey(t *testing.T) {
	l := New(2, 1000*time.Second) // 2 requests per 1000s window: refill is negligible within this test.

	if !l.Allow("k") {
		t.Fatal("1st call should be allowed (burst capacity)")
	}
	if !l.Allow("k") {
		t.Fatal("2nd call should be allowed (burst capacity)")
	}
	if l.Allow("k") {
		t.Fatal("3rd call should be rejected: burst exhausted")
	}

	// A different key has its own independent bucket.
	if !l.Allow("other-key") {
		t.Fatal("a different key must not be affected by k's exhausted bucket")
	}
}

// reqFrom builds a request from a fixed client IP (X-Real-IP is what
// clientip.From trusts first behind nginx) with an optional Authorization header.
func reqFrom(ip, authorization string) *http.Request {
	r := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments", nil)
	r.Header.Set("X-Real-IP", ip)
	if authorization != "" {
		r.Header.Set("Authorization", authorization)
	}
	return r
}

// TestLimiter_WrapAnon_AnonymousThrottledByIP proves anonymous requests share a
// single per-IP bucket keyed on client IP alone (path-independent), so a burst
// from one IP is throttled while a different IP is unaffected.
func TestLimiter_WrapAnon_AnonymousThrottledByIP(t *testing.T) {
	l := New(1, 1000*time.Second) // 1 anon request per 1000s: refill negligible in-test.
	calls := 0
	h := l.WrapAnon(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls++
		w.WriteHeader(http.StatusOK)
	}))

	// First anonymous request from 1.1.1.1 passes.
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, reqFrom("1.1.1.1", ""))
	if rec.Code != http.StatusOK {
		t.Fatalf("1st anon request: want 200, got %d", rec.Code)
	}
	// Second from the same IP (different path would not matter) is throttled.
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, reqFrom("1.1.1.1", ""))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("2nd anon request from same IP: want 429, got %d", rec.Code)
	}
	if rec.Header().Get("Retry-After") == "" {
		t.Error("429 response should carry a Retry-After header")
	}
	// A different IP has its own bucket.
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, reqFrom("2.2.2.2", ""))
	if rec.Code != http.StatusOK {
		t.Fatalf("anon request from a fresh IP: want 200, got %d", rec.Code)
	}
	if calls != 2 {
		t.Fatalf("handler should run only for the 2 allowed requests, ran %d", calls)
	}
}

// TestLimiter_WrapAnon_BearerBypasses proves authenticated requests never
// consume the anonymous bucket, even well past the limit.
func TestLimiter_WrapAnon_BearerBypasses(t *testing.T) {
	l := New(1, 1000*time.Second)
	h := l.WrapAnon(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	for i := 0; i < 5; i++ {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, reqFrom("1.1.1.1", "Bearer some.jwt.token"))
		if rec.Code != http.StatusOK {
			t.Fatalf("authenticated request %d must bypass the anon limiter, got %d", i, rec.Code)
		}
	}
}

// TestLimiter_WrapAnon_DisabledPassThrough proves a disabled limiter returns the
// handler unchanged (no throttling of anonymous traffic).
func TestLimiter_WrapAnon_DisabledPassThrough(t *testing.T) {
	l := New(0, 0)
	h := l.WrapAnon(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	for i := 0; i < 5; i++ {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, reqFrom("1.1.1.1", ""))
		if rec.Code != http.StatusOK {
			t.Fatalf("disabled limiter should pass anon request %d through, got %d", i, rec.Code)
		}
	}
}

// TestIsAnonymous covers the bearer-detection edge cases the throttle decision
// hinges on: only a non-empty, scheme-insensitive bearer counts as authenticated.
func TestIsAnonymous(t *testing.T) {
	cases := []struct {
		authorization string
		wantAnon      bool
	}{
		{"", true},
		{"Bearer token", false},
		{"bearer token", false}, // scheme is case-insensitive
		{"Bearer ", true},       // empty credential is not authenticated
		{"Basic dXNlcjpwYXNz", true},
		{"token-without-scheme", true},
	}
	for _, c := range cases {
		r := httptest.NewRequest(http.MethodGet, "/", nil)
		if c.authorization != "" {
			r.Header.Set("Authorization", c.authorization)
		}
		if got := isAnonymous(r); got != c.wantAnon {
			t.Errorf("isAnonymous(%q) = %v, want %v", c.authorization, got, c.wantAnon)
		}
	}
}

// wrapFailuresReq builds a POST /api/auth/refresh from a fixed client IP, the
// shape WrapFailures is wired for in main.go.
func wrapFailuresReq(ip string) *http.Request {
	r := httptest.NewRequest(http.MethodPost, "/api/auth/refresh", nil)
	r.Header.Set("X-Real-IP", ip)
	return r
}

// TestLimiter_WrapFailures_SuccessesAreFree is the whole point of WrapFailures:
// a VPN / carrier-NAT exit IP carries many legitimate users, and their ordinary
// refresh rotations must never exhaust one shared per-IP budget (the 429 reaches
// the browser as a refresh failure, i.e. a forced re-login for everyone on it).
func TestLimiter_WrapFailures_SuccessesAreFree(t *testing.T) {
	l := New(2, 1000*time.Second) // 2 per 1000s: refill is negligible in-test.
	h := l.WrapFailures(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	for i := range 20 {
		rec := httptest.NewRecorder()
		h(rec, wrapFailuresReq("1.1.1.1"))
		if rec.Code != http.StatusOK {
			t.Fatalf("successful refresh %d: want 200, got %d", i, rec.Code)
		}
	}
}

// TestLimiter_WrapFailures_MetersRejections proves the anti-brute-force property
// survives: failed attempts (401 — what guessing a refresh token produces) still
// consume the per-IP budget, and the next attempt is throttled.
func TestLimiter_WrapFailures_MetersRejections(t *testing.T) {
	l := New(2, 1000*time.Second)
	calls := 0
	h := l.WrapFailures(func(w http.ResponseWriter, _ *http.Request) {
		calls++
		w.WriteHeader(http.StatusUnauthorized)
	})

	for i := range 2 {
		rec := httptest.NewRecorder()
		h(rec, wrapFailuresReq("1.1.1.1"))
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("failed refresh %d: want 401, got %d", i, rec.Code)
		}
	}

	rec := httptest.NewRecorder()
	h(rec, wrapFailuresReq("1.1.1.1"))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("3rd failed refresh: want 429, got %d", rec.Code)
	}
	if rec.Header().Get("Retry-After") == "" {
		t.Error("429 response should carry a Retry-After header")
	}
	if calls != 2 {
		t.Fatalf("handler should have run only for the 2 allowed attempts, ran %d", calls)
	}

	// A throttled IP must not affect anyone else.
	rec = httptest.NewRecorder()
	h(rec, wrapFailuresReq("2.2.2.2"))
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("fresh IP: want 401 (own bucket), got %d", rec.Code)
	}
}

// TestLimiter_WrapFailures_SuccessAfterFailuresStillPasses proves a client that
// recovers is not stuck behind its own earlier failures while the bucket holds
// tokens, and that successes never deepen the debt.
func TestLimiter_WrapFailures_SuccessAfterFailuresStillPasses(t *testing.T) {
	l := New(2, 1000*time.Second)
	status := http.StatusUnauthorized
	h := l.WrapFailures(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(status)
	})

	rec := httptest.NewRecorder()
	h(rec, wrapFailuresReq("1.1.1.1")) // burns 1 of 2
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("want 401, got %d", rec.Code)
	}

	status = http.StatusOK
	for i := range 10 {
		rec = httptest.NewRecorder()
		h(rec, wrapFailuresReq("1.1.1.1"))
		if rec.Code != http.StatusOK {
			t.Fatalf("recovered refresh %d: want 200, got %d", i, rec.Code)
		}
	}
}

// TestLimiter_WrapFailures_DisabledPassThrough mirrors Wrap/WrapAnon: a
// non-positive limit yields the handler unchanged.
func TestLimiter_WrapFailures_DisabledPassThrough(t *testing.T) {
	l := New(0, 0)
	h := l.WrapFailures(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	})
	for i := range 5 {
		rec := httptest.NewRecorder()
		h(rec, wrapFailuresReq("1.1.1.1"))
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("disabled limiter should pass attempt %d through, got %d", i, rec.Code)
		}
	}
}

// staticQuota is a KeyQuota that reads the bucket key and budget straight off
// the request's Authorization header value ("<key>:<perMinute>"), standing in
// for principal.Resolver.APIKeyQuota without an RPC stub. An empty header means
// "not API-key traffic".
func staticQuota(r *http.Request) (string, int, bool) {
	raw := r.Header.Get("Authorization")
	if raw == "" {
		return "", 0, false
	}
	key, rpm, _ := strings.Cut(raw, ":")
	n, _ := strconv.Atoi(rpm)
	return key, n, true
}

func keyReq(auth string) *http.Request {
	r := httptest.NewRequest(http.MethodGet, "/api/v1/tournaments", nil)
	if auth != "" {
		r.Header.Set("Authorization", auth)
	}
	return r
}

// TestLimiter_WrapAPIKey_MetersEachKeyOnItsOwnBudget is the core contract: a key
// is throttled against the requests_per_minute IT was issued (not one flat
// process-wide number), and each key gets its own bucket.
func TestLimiter_WrapAPIKey_MetersEachKeyOnItsOwnBudget(t *testing.T) {
	l := New(1000, time.Minute) // generous default: the per-key budgets must bind, not this.
	h := l.WrapAPIKey(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}), staticQuota)

	// Key "a" is issued 2/min: two pass, the third is refused.
	for i := 1; i <= 2; i++ {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, keyReq("a:2"))
		if rec.Code != http.StatusOK {
			t.Fatalf("request %d within key a's budget: want 200, got %d", i, rec.Code)
		}
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, keyReq("a:2"))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("3rd request over key a's 2/min: want 429, got %d", rec.Code)
	}
	if got := rec.Header().Get("Retry-After"); got != "60" {
		t.Errorf("Retry-After: want 60 (the minute window), got %q", got)
	}
	// The shared contract, not a byte-exact body: `detail` for humans, `code`
	// for clients branching on the reason (see internal/apierr).
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("429 body must be JSON, got %s", rec.Body.String())
	}
	if body["detail"] != "Too many requests" || body["code"] != "rate_limited" {
		t.Errorf("429 body must match the shared shape, got %s", rec.Body.String())
	}

	// Key "b" is unaffected by key a's exhaustion, and spends its own budget.
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, keyReq("b:1"))
	if rec.Code != http.StatusOK {
		t.Fatalf("a fresh key must have its own bucket, got %d", rec.Code)
	}
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, keyReq("b:1"))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("2nd request over key b's 1/min: want 429, got %d", rec.Code)
	}
}

// TestLimiter_WrapAPIKey_FallsBackToConfiguredLimit covers a key issued without
// an explicit requests_per_minute: it is metered on the platform default the
// limiter was built with, not left unbounded.
func TestLimiter_WrapAPIKey_FallsBackToConfiguredLimit(t *testing.T) {
	l := New(1, time.Minute)
	h := l.WrapAPIKey(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}), staticQuota)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, keyReq("nolimit:0"))
	if rec.Code != http.StatusOK {
		t.Fatalf("1st request: want 200, got %d", rec.Code)
	}
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, keyReq("nolimit:0"))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("a key with no own quota must fall back to the configured 1/min, got %d", rec.Code)
	}
}

// TestLimiter_WrapAPIKey_NonKeyTrafficUntouched proves session and anonymous
// requests keep their exact previous behaviour: quota reports ok=false for them,
// and nothing is metered no matter how many arrive.
func TestLimiter_WrapAPIKey_NonKeyTrafficUntouched(t *testing.T) {
	l := New(1, time.Minute)
	calls := 0
	h := l.WrapAPIKey(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls++
		w.WriteHeader(http.StatusOK)
	}), staticQuota)

	for i := range 5 {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, keyReq(""))
		if rec.Code != http.StatusOK {
			t.Fatalf("non-key request %d must pass through, got %d", i, rec.Code)
		}
	}
	if calls != 5 {
		t.Fatalf("all 5 non-key requests must reach the handler, got %d", calls)
	}
}

// TestLimiter_WrapAPIKey_DisabledPassThrough mirrors the other wrappers: a
// non-positive limit (GATEWAY_API_KEY_RATE_LIMIT <= 0) is the kill switch and
// returns the handler unchanged, without ever consulting the quota.
func TestLimiter_WrapAPIKey_DisabledPassThrough(t *testing.T) {
	quotaCalls := 0
	counting := func(r *http.Request) (string, int, bool) {
		quotaCalls++
		return staticQuota(r)
	}
	h := New(0, time.Minute).WrapAPIKey(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}), counting)

	for i := range 5 {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, keyReq("a:1"))
		if rec.Code != http.StatusOK {
			t.Fatalf("disabled limiter must pass request %d through, got %d", i, rec.Code)
		}
	}
	if quotaCalls != 0 {
		t.Fatalf("a disabled limiter must not resolve identities at all, got %d quota calls", quotaCalls)
	}
}

// TestLimiter_WrapAPIKey_NilQuotaPassThrough guards the wiring: without a quota
// resolver there is nothing to meter, so the surface must be served, not broken.
func TestLimiter_WrapAPIKey_NilQuotaPassThrough(t *testing.T) {
	h := New(1, time.Minute).WrapAPIKey(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}), nil)
	for i := range 3 {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, keyReq("a:1"))
		if rec.Code != http.StatusOK {
			t.Fatalf("nil quota must pass request %d through, got %d", i, rec.Code)
		}
	}
}

// TestLimiter_AllowQuotaMatchesConfiguredAllow pins the refactor: allow is now
// allowQuota with the limiter's own budget, so passing that budget explicitly
// must behave identically — the session/anon wrappers rely on it.
func TestLimiter_AllowQuotaMatchesConfiguredAllow(t *testing.T) {
	const limit = 3
	configured, explicit := New(limit, 1000*time.Second), New(limit, 1000*time.Second)
	for i := range limit + 1 {
		want := configured.allow("k")
		if got, _ := explicit.allowQuota("k", limit); got != want {
			t.Fatalf("call %d: allowQuota=%v, allow=%v", i, got, want)
		}
	}
}
