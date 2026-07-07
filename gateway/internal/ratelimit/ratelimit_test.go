package ratelimit

import (
	"net/http"
	"net/http/httptest"
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
