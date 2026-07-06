// Package ratelimit is a small in-memory token-bucket rate limiter used to blunt
// brute-force / credential-stuffing against the auth endpoints (login/register/
// refresh/oauth-callback). It is keyed by client IP + request path and is
// intentionally best-effort: per-process (not shared across replicas) and
// dependency-free. nginx limit_req provides the coarse outer defense layer.
package ratelimit

import (
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/clientip"
)

// maxKeys bounds memory: past this many tracked buckets, stale ones are purged.
const maxKeys = 8192

type bucket struct {
	tokens float64
	last   time.Time
}

// Limiter is a per-key token bucket. A zero-value (disabled) limiter lets all
// traffic through, so it can be turned off via config without code changes.
type Limiter struct {
	rate   float64 // tokens refilled per second
	burst  float64 // bucket capacity
	window time.Duration
	now    func() time.Time

	mu      sync.Mutex
	buckets map[string]*bucket
}

// New builds a limiter allowing `limit` requests per `window` (burst = limit). A
// non-positive limit or window yields a disabled limiter.
func New(limit int, window time.Duration) *Limiter {
	if limit <= 0 || window <= 0 {
		return &Limiter{}
	}
	return &Limiter{
		rate:    float64(limit) / window.Seconds(),
		burst:   float64(limit),
		window:  window,
		now:     time.Now,
		buckets: make(map[string]*bucket),
	}
}

// Enabled reports whether the limiter is active.
func (l *Limiter) Enabled() bool { return l.rate > 0 }

// allow consumes one token for key, returning false when the bucket is empty.
func (l *Limiter) allow(key string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	b, ok := l.buckets[key]
	if !ok {
		if len(l.buckets) >= maxKeys {
			l.purge(now)
		}
		b = &bucket{tokens: l.burst, last: now}
		l.buckets[key] = b
	}
	b.tokens += now.Sub(b.last).Seconds() * l.rate
	if b.tokens > l.burst {
		b.tokens = l.burst
	}
	b.last = now
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}

// purge drops buckets idle longer than the window (fully refilled). Caller holds l.mu.
func (l *Limiter) purge(now time.Time) {
	for k, b := range l.buckets {
		if now.Sub(b.last) >= l.window {
			delete(l.buckets, k)
		}
	}
	if len(l.buckets) >= maxKeys {
		l.buckets = make(map[string]*bucket) // last resort: bound memory
	}
}

// Wrap returns next guarded by the limiter, keyed on client IP + request path.
// When the limiter is disabled it returns next unchanged.
func (l *Limiter) Wrap(next http.HandlerFunc) http.HandlerFunc {
	if !l.Enabled() {
		return next
	}
	return func(w http.ResponseWriter, r *http.Request) {
		key := clientip.From(r) + "|" + r.URL.Path
		if !l.allow(key) {
			w.Header().Set("Retry-After", strconv.Itoa(int(l.window.Seconds())))
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusTooManyRequests)
			_, _ = w.Write([]byte(`{"detail":"Too many requests"}`))
			return
		}
		next(w, r)
	}
}
