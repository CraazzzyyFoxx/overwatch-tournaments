package ratelimit

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

// sharedLimiter builds the Redis-backed API-key limiter over a fresh miniredis,
// with the default budget `defaultRPM` and a counter of fail-open events.
func sharedLimiter(t *testing.T, defaultRPM int) (*miniredis.Miniredis, *RedisLimiter, *int) {
	t.Helper()
	srv := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: srv.Addr()})
	t.Cleanup(func() { _ = rdb.Close() })

	fallbacks := 0
	local := New(defaultRPM, time.Minute)
	l := NewRedis(rdb, local, slog.New(slog.NewTextHandler(io.Discard, nil)), func() { fallbacks++ })
	return srv, l, &fallbacks
}

func okHandler(calls *int) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		*calls++
		w.WriteHeader(http.StatusOK)
	})
}

// TestRedisLimiter_RefusesPastTheKeyBudget is the core contract: the shared
// counter binds at the key's own requests_per_minute, and the request that
// crosses it is refused with the unchanged 429 body.
func TestRedisLimiter_RefusesPastTheKeyBudget(t *testing.T) {
	_, l, fallbacks := sharedLimiter(t, 1000)
	calls := 0
	h := l.WrapAPIKey(okHandler(&calls), staticQuota)

	for i := range 2 {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, keyReq("7:2"))
		if rec.Code != http.StatusOK {
			t.Fatalf("request %d within the 2/min budget: want 200, got %d", i, rec.Code)
		}
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, keyReq("7:2"))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("3rd request over a 2/min budget: want 429, got %d", rec.Code)
	}
	if calls != 2 {
		t.Fatalf("the refused request must not reach the handler: %d calls", calls)
	}
	if *fallbacks != 0 {
		t.Fatalf("a healthy Redis must not count fail-opens, got %d", *fallbacks)
	}
	if body := rec.Body.String(); !strings.Contains(body, `"rate_limited"`) {
		t.Fatalf("the 429 body must keep the shared rate_limited code, got %s", body)
	}
	if got := rec.Header().Get("Retry-After"); got == "" || got == "0" {
		t.Fatalf("Retry-After must tell the client when the window resets, got %q", got)
	}
}

// TestRedisLimiter_ChargesTheSharedPythonKey pins the cross-language contract:
// the counter this limiter spends is the exact key shared/quota/enforcer.py
// charges, expiring after one minute. Drift here hands every API key a second
// full budget (see backend/tests/test_quota_key_parity.py).
func TestRedisLimiter_ChargesTheSharedPythonKey(t *testing.T) {
	srv, l, _ := sharedLimiter(t, 1000)
	calls := 0
	h := l.WrapAPIKey(okHandler(&calls), staticQuota)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, keyReq("42:5"))
	if rec.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", rec.Code)
	}
	got, err := srv.Get("q:key:42:rpm")
	if err != nil {
		t.Fatalf("q:key:42:rpm must hold the per-minute count: %v", err)
	}
	if got != "1" {
		t.Fatalf("one request must charge one token, got %q", got)
	}
	if ttl := srv.TTL("q:key:42:rpm"); ttl != time.Minute {
		t.Fatalf("the window must expire after a minute, got %s", ttl)
	}
}

// TestRedisLimiter_OneBucketAcrossReplicas is the reason this variant exists: two
// limiters (two gateway pods) spend ONE budget, instead of each granting a full
// one. With the in-process bucket this test would see four 200s.
func TestRedisLimiter_OneBucketAcrossReplicas(t *testing.T) {
	srv := miniredis.RunT(t)
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	handlers := make([]http.Handler, 2)
	for i := range handlers {
		rdb := redis.NewClient(&redis.Options{Addr: srv.Addr()})
		t.Cleanup(func() { _ = rdb.Close() })
		calls := 0
		handlers[i] = NewRedis(rdb, New(1000, time.Minute), logger, nil).WrapAPIKey(okHandler(&calls), staticQuota)
	}

	codes := make([]int, 0, 4)
	for range 2 {
		for _, h := range handlers {
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, keyReq("9:2"))
			codes = append(codes, rec.Code)
		}
	}
	want := []int{http.StatusOK, http.StatusOK, http.StatusTooManyRequests, http.StatusTooManyRequests}
	for i, code := range codes {
		if code != want[i] {
			t.Fatalf("request %d: want %d, got %d (codes %v) — replicas are not sharing one bucket", i, want[i], code, codes)
		}
	}
}

// TestRedisLimiter_FailsOpenWhenRedisIsDown proves the availability choice: an
// unreachable counter must not turn a rate limit into an outage. The request is
// served, the fail-open is counted, and the headers report the full budget
// rather than a token nothing charged.
func TestRedisLimiter_FailsOpenWhenRedisIsDown(t *testing.T) {
	srv, l, fallbacks := sharedLimiter(t, 1000)
	calls := 0
	h := l.WrapAPIKey(okHandler(&calls), staticQuota)
	srv.Close() // every subsequent EVAL fails to connect

	for i := range 3 {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, keyReq("7:1"))
		if rec.Code != http.StatusOK {
			t.Fatalf("request %d must be allowed while Redis is down, got %d", i, rec.Code)
		}
		if got := rec.Header().Get("RateLimit-Remaining"); got != "1" {
			t.Fatalf("an unmetered request must not claim a consumed token, RateLimit-Remaining=%q", got)
		}
	}
	if calls != 3 {
		t.Fatalf("every request must reach the handler, got %d calls", calls)
	}
	if *fallbacks != 3 {
		t.Fatalf("each unmetered request must be counted, got %d", *fallbacks)
	}
}

// TestRedisLimiter_EmitsRateLimitHeaders covers the pacing contract: the triple
// is present on the allowed responses AND on the refusal, and Remaining walks
// the budget down to zero.
func TestRedisLimiter_EmitsRateLimitHeaders(t *testing.T) {
	_, l, _ := sharedLimiter(t, 1000)
	calls := 0
	h := l.WrapAPIKey(okHandler(&calls), staticQuota)

	for i, wantRemaining := range []string{"1", "0", "0"} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, keyReq("7:2"))
		if got := rec.Header().Get("RateLimit-Limit"); got != "2" {
			t.Fatalf("request %d: RateLimit-Limit=%q, want the key's own budget 2", i, got)
		}
		if got := rec.Header().Get("RateLimit-Remaining"); got != wantRemaining {
			t.Fatalf("request %d: RateLimit-Remaining=%q, want %q", i, got, wantRemaining)
		}
		if got := rec.Header().Get("RateLimit-Reset"); got != "60" {
			t.Fatalf("request %d: RateLimit-Reset=%q, want the 60s window", i, got)
		}
	}
}

// TestRedisLimiter_DefaultBudgetAndKillSwitch keeps the wrapped limiter's two
// config roles working through the Redis path: a key with no own
// requests_per_minute is metered on the platform default, and a non-positive
// GATEWAY_API_KEY_RATE_LIMIT disables per-key throttling entirely.
func TestRedisLimiter_DefaultBudgetAndKillSwitch(t *testing.T) {
	_, l, _ := sharedLimiter(t, 1)
	calls := 0
	h := l.WrapAPIKey(okHandler(&calls), staticQuota)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, keyReq("nolimit:0"))
	if rec.Code != http.StatusOK {
		t.Fatalf("1st request: want 200, got %d", rec.Code)
	}
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, keyReq("nolimit:0"))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("a key with no own budget must fall back to the configured 1/min, got %d", rec.Code)
	}

	srv := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: srv.Addr()})
	t.Cleanup(func() { _ = rdb.Close() })
	off := NewRedis(rdb, New(0, time.Minute), nil, nil).WrapAPIKey(okHandler(&calls), staticQuota)
	for i := range 5 {
		rec := httptest.NewRecorder()
		off.ServeHTTP(rec, keyReq("7:1"))
		if rec.Code != http.StatusOK {
			t.Fatalf("request %d with the limiter disabled: want 200, got %d", i, rec.Code)
		}
	}
	if len(srv.Keys()) != 0 {
		t.Fatalf("a disabled limiter must not touch Redis, keys: %v", srv.Keys())
	}
}

// TestRedisLimiter_NoClientUsesTheLocalBucket covers a gateway built without
// Redis: metering degrades to the in-process bucket (per-replica, as it was
// before) instead of dropping the per-key limit altogether.
func TestRedisLimiter_NoClientUsesTheLocalBucket(t *testing.T) {
	calls := 0
	h := NewRedis(nil, New(1000, time.Minute), nil, nil).WrapAPIKey(okHandler(&calls), staticQuota)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, keyReq("7:1"))
	if rec.Code != http.StatusOK {
		t.Fatalf("1st request: want 200, got %d", rec.Code)
	}
	if got := rec.Header().Get("RateLimit-Limit"); got != "1" {
		t.Fatalf("the local fallback must still let a client pace itself, RateLimit-Limit=%q", got)
	}
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, keyReq("7:1"))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("the local bucket must still refuse past the budget, got %d", rec.Code)
	}
}

// TestRedisLimiter_RejectionsAreCounted proves the Prometheus layer label is
// wired: a 429 from the shared bucket reports itself as the api_key layer.
func TestRedisLimiter_RejectionsAreCounted(t *testing.T) {
	_, l, _ := sharedLimiter(t, 1)
	layers := make([]string, 0, 1)
	l.local.OnReject(func(layer string) { layers = append(layers, layer) })
	calls := 0
	h := l.WrapAPIKey(okHandler(&calls), staticQuota)

	for range 2 {
		h.ServeHTTP(httptest.NewRecorder(), keyReq("7:1"))
	}
	if len(layers) != 1 || layers[0] != layerAPIKey {
		t.Fatalf("want exactly one %q rejection, got %v", layerAPIKey, layers)
	}
}
