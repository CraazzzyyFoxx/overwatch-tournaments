// Package ratelimit is a small in-memory token-bucket rate limiter. It blunts
// brute-force / credential-stuffing against the auth endpoints (login/register/
// refresh/oauth-callback), bounds anonymous traffic per client IP, and meters
// workspace-scoped API keys against their own per-key requests_per_minute
// budget (WrapAPIKey).
//
// The in-process variants here share one deliberate limitation: their buckets
// live in THIS process only. Nothing is shared across replicas, so with N
// gateway pods a caller's effective budget is up to N x the configured limit.
// That is fine for the anti-brute-force (auth) and anti-abuse (anonymous)
// jobs — nginx limit_req is the coarse outer layer — but it means those limits
// are a guardrail, not an accounting boundary.
//
// The API-key bucket is the one place where the exact number is the product
// contract, so WrapAPIKey has a Redis-backed variant (redis.go) that spends the
// SAME per-minute key the Python enforcer does. It degrades to the in-process
// bucket when no Redis client is configured.
package ratelimit

import (
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apierr"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/clientip"
)

// maxKeys bounds memory: past this many tracked buckets, stale ones are purged.
const maxKeys = 8192

// Layer names reported to the reject hook, one per wrapper. They are what lets
// an operator tell "someone is scanning us" (anon) from "a client outgrew its
// key" (api_key) apart in one Prometheus counter.
const (
	layerAuth   = "auth"
	layerAnon   = "anon"
	layerAPIKey = "api_key"
)

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
	reject func(layer string)

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

// OnReject registers a hook invoked once per refused request, labelled with the
// layer that refused it. main wires it to a Prometheus counter. Set once at
// startup, before the limiter serves traffic; it returns l so it chains onto New.
func (l *Limiter) OnReject(hook func(layer string)) *Limiter {
	l.reject = hook
	return l
}

// rejected fires the reject hook, if one is registered.
func (l *Limiter) rejected(layer string) {
	if l.reject != nil {
		l.reject(layer)
	}
}

// Allow reports whether the next request for key may proceed, consuming a
// token if so. It is exported (in addition to Wrap) for callers that need to
// gate a single unit of work inside a larger handler rather than reject an
// entire request — e.g. ws.Handler bounds only its pre-handshake
// custom-domain lookup this way, falling through to the static origin
// allowlist (which then rejects the connection) instead of refusing the
// whole request outright.
//
// A nil *Limiter behaves like a disabled one (always allows), so callers can
// safely hold an optional *Limiter field without a separate nil check.
func (l *Limiter) Allow(key string) bool {
	if l == nil || !l.Enabled() {
		return true
	}
	return l.allow(key)
}

// allow consumes one token for key against the limiter's configured budget.
func (l *Limiter) allow(key string) bool {
	ok, _ := l.allowQuota(key, l.burst)
	return ok
}

// allowQuota consumes one token for key against an explicit budget of `limit`
// requests per window, returning false when the bucket is empty plus the whole
// tokens left afterwards (what RateLimit-Remaining reports). It is the same
// bucket machinery allow uses, with the rate supplied per call: an API key's
// requests_per_minute is a property of the key, not of the process config, so
// one Limiter has to serve many different budgets at once.
func (l *Limiter) allowQuota(key string, limit float64) (bool, int) {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	rate := limit / l.window.Seconds()
	b, ok := l.buckets[key]
	if !ok {
		if len(l.buckets) >= maxKeys {
			l.purge(now)
		}
		b = &bucket{tokens: limit, last: now}
		l.buckets[key] = b
	}
	b.tokens += now.Sub(b.last).Seconds() * rate
	if b.tokens > limit {
		b.tokens = limit
	}
	b.last = now
	if b.tokens < 1 {
		return false, 0
	}
	b.tokens--
	return true, int(b.tokens)
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
			l.rejected(layerAuth)
			tooManyRequests(w, l.window)
			return
		}
		next(w, r)
	}
}

// WrapFailures returns next guarded by the limiter, keyed on client IP + request
// path, but consuming a token ONLY when next rejects the call as unauthenticated
// (401/403). Successful calls are free.
//
// Wrap's flat per-IP budget is wrong for /api/v1/auth/refresh: a VPN or carrier-NAT
// exit node puts many legitimate users behind ONE IP, and their ordinary token
// rotations alone drain the bucket. The resulting 429 reaches the frontend as a
// refresh failure — i.e. everyone sharing that IP gets logged out. Brute-force
// attempts, by definition, produce 401s, so metering only failures keeps the
// anti-brute-force property without punishing shared IPs.
func (l *Limiter) WrapFailures(next http.HandlerFunc) http.HandlerFunc {
	if !l.Enabled() {
		return next
	}
	return func(w http.ResponseWriter, r *http.Request) {
		key := clientip.From(r) + "|" + r.URL.Path
		if !l.hasTokens(key) {
			l.rejected(layerAuth)
			tooManyRequests(w, l.window)
			return
		}
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next(rec, r)
		if rec.status == http.StatusUnauthorized || rec.status == http.StatusForbidden {
			l.allow(key)
		}
	}
}

// hasTokens reports whether key's bucket still has a token to spend, refilling it
// but NOT consuming. An untracked key (nothing failed yet) always passes and,
// unlike allow, allocates no bucket — so well-behaved clients cost no memory.
func (l *Limiter) hasTokens(key string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	b, ok := l.buckets[key]
	if !ok {
		return true
	}
	now := l.now()
	b.tokens += now.Sub(b.last).Seconds() * l.rate
	if b.tokens > l.burst {
		b.tokens = l.burst
	}
	b.last = now
	return b.tokens >= 1
}

// statusRecorder records the status the wrapped handler wrote, so WrapFailures
// can meter only rejections. A handler that writes a body without an explicit
// WriteHeader keeps the zero value 200 (success), which is what net/http sends.
type statusRecorder struct {
	http.ResponseWriter
	status      int
	wroteHeader bool
}

func (s *statusRecorder) WriteHeader(status int) {
	if !s.wroteHeader {
		s.status = status
		s.wroteHeader = true
	}
	s.ResponseWriter.WriteHeader(status)
}

// Unwrap exposes the wrapped writer to http.ResponseController (flush/deadlines).
func (s *statusRecorder) Unwrap() http.ResponseWriter { return s.ResponseWriter }

// WrapAnon returns next guarded by the limiter for anonymous requests only —
// those that carry no bearer token — keyed on client IP alone (a global
// per-IP anonymous budget across all paths). Authenticated requests
// (Authorization: Bearer …) pass through untouched, as do all requests when
// the limiter is disabled. Unlike Wrap it takes/returns http.Handler so it can
// wrap the whole API mux as outer middleware.
func (l *Limiter) WrapAnon(next http.Handler) http.Handler {
	if !l.Enabled() {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if isAnonymous(r) && !l.allow(clientip.From(r)) {
			l.rejected(layerAnon)
			tooManyRequests(w, l.window)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// KeyQuota identifies the API key behind a request and the per-minute request
// budget that key itself carries. ok=false means the request is not API-key
// traffic — or its identity could not be judged — and must not be metered here.
// Implemented by principal.Resolver.APIKeyQuota, which answers without any
// identity lookup for session/anonymous traffic.
type KeyQuota func(r *http.Request) (key string, perMinute int, ok bool)

// WrapAPIKey returns next guarded by a PER-KEY budget: an API-key request is
// metered against its own key id — a global budget across all paths, like
// WrapAnon's per-IP one — using the requests_per_minute that key was issued
// rather than one flat process-wide number. Session and anonymous traffic pass
// through untouched, as do all requests when the limiter is disabled. Like
// WrapAnon it takes/returns http.Handler so it can wrap the whole API mux.
//
// A key carrying no explicit requests_per_minute falls back to the limiter's
// configured limit, which doubles as the kill switch: a non-positive
// GATEWAY_API_KEY_RATE_LIMIT disables per-key throttling entirely.
//
// Rejection uses the shared 429 body + Retry-After, so an API client sees the
// same contract here as it does from the balancer worker's Redis-backed quota,
// and every metered response carries the RateLimit-* triple a client needs to
// pace itself instead of discovering the wall.
//
// This is the per-replica variant; RedisLimiter.WrapAPIKey (redis.go) is the
// shared-bucket one main prefers when Redis is configured.
func (l *Limiter) WrapAPIKey(next http.Handler, quota KeyQuota) http.Handler {
	if !l.Enabled() || quota == nil {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if key, perMinute, ok := quota(r); ok {
			limit := float64(perMinute)
			if limit <= 0 {
				limit = l.burst
			}
			allowed, remaining := l.allowQuota(key, limit)
			writeRateLimitHeaders(w, int(limit), remaining, int(l.window.Seconds()))
			if !allowed {
				l.rejected(layerAPIKey)
				tooManyRequests(w, l.window)
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

// writeRateLimitHeaders reports the budget, what is left of it and when it
// resets (seconds), on every metered response — refused or not. Names follow
// the IETF RateLimit header fields draft, which is what API clients and SDK
// retry middlewares already look for.
func writeRateLimitHeaders(w http.ResponseWriter, limit, remaining, resetSeconds int) {
	if remaining < 0 {
		remaining = 0
	}
	if resetSeconds < 1 {
		resetSeconds = 1
	}
	h := w.Header()
	h.Set("RateLimit-Limit", strconv.Itoa(limit))
	h.Set("RateLimit-Remaining", strconv.Itoa(remaining))
	h.Set("RateLimit-Reset", strconv.Itoa(resetSeconds))
}

// tooManyRequests writes the shared 429: Retry-After plus the same
// {detail, code} body a worker-side rate limit produces, so a client branches
// on one `rate_limited` code no matter which layer refused it (per-IP and
// per-key here, Redis job quotas in balancer-service).
func tooManyRequests(w http.ResponseWriter, window time.Duration) {
	secs := int(window.Seconds())
	if secs < 1 {
		secs = 1
	}
	w.Header().Set("Retry-After", strconv.Itoa(secs))
	apierr.WriteError(w, http.StatusTooManyRequests, "Too many requests", "rate_limited", map[string]any{"retry_after": secs})
}

// isAnonymous reports whether r carries no usable bearer token. It mirrors
// principal.bearer's parsing (scheme-insensitive, non-empty credential) so the
// "anonymous" verdict here matches what the identity resolver would treat as
// unauthenticated — without the RPC token validation.
func isAnonymous(r *http.Request) bool {
	scheme, creds, found := strings.Cut(r.Header.Get("Authorization"), " ")
	return !(found && strings.EqualFold(scheme, "bearer") && strings.TrimSpace(creds) != "")
}
