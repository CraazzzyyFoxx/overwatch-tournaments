package ratelimit

import (
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
