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
	"container/list"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apierr"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/clientip"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
)

// maxKeys bounds memory: at most this many buckets are tracked per limiter
// (see slot for what a new key gets past it).
const maxKeys = 8192

// Layer names reported to the reject hook, one per wrapper. They are what lets
// an operator tell "someone is scanning us" (anon) from "a client outgrew its
// key" (api_key) or "a tenant outgrew its plan" (workspace) apart in one
// Prometheus counter.
const (
	layerAuth      = "auth"
	layerAnon      = "anon"
	layerAPIKey    = "api_key"
	layerWorkspace = "workspace"
)

type bucket struct {
	key    string
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
	buckets map[string]*list.Element // key -> element in lru (holds *bucket)
	lru     *list.List               // most recently touched at the front
	// overflow is the one bucket every NEW key shares while the table is full
	// of buckets still mid-window (see slot).
	overflow bucket
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
		buckets: make(map[string]*list.Element),
		lru:     list.New(),
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
	b := l.slot(key, limit, now)
	l.refill(b, limit, now)
	if b.tokens < 1 {
		return false, 0
	}
	b.tokens--
	return true, int(b.tokens)
}

// slot returns key's bucket, tracking a new full one when there is room.
// Caller holds l.mu.
//
// A full table makes room by dropping its least-recently-touched bucket, but
// only once that bucket has sat idle a whole window: by then it has refilled
// to the brim, so forgetting it changes nobody's budget. Otherwise every
// tracked client is mid-window and the newcomer shares the overflow bucket —
// evicting an active bucket (or, as this once did, the whole table) would hand
// an exhausted client a fresh burst for flooding new keys. O(1) either way.
func (l *Limiter) slot(key string, limit float64, now time.Time) *bucket {
	if el, ok := l.buckets[key]; ok {
		l.lru.MoveToFront(el)
		return el.Value.(*bucket)
	}
	if l.saturated(now) {
		return &l.overflow
	}
	if len(l.buckets) >= maxKeys {
		oldest := l.lru.Back()
		delete(l.buckets, oldest.Value.(*bucket).key)
		l.lru.Remove(oldest)
	}
	b := &bucket{key: key, tokens: limit, last: now}
	l.buckets[key] = l.lru.PushFront(b)
	return b
}

// saturated reports whether the table is full and even its least-recently
// touched bucket — hence every bucket — is still mid-window. Caller holds l.mu.
func (l *Limiter) saturated(now time.Time) bool {
	return len(l.buckets) >= maxKeys && now.Sub(l.lru.Back().Value.(*bucket).last) < l.window
}

// refill credits b for the time since it was last touched, at limit tokens per
// window, capped at limit. Caller holds l.mu.
func (l *Limiter) refill(b *bucket, limit float64, now time.Time) {
	b.tokens = min(limit, b.tokens+now.Sub(b.last).Seconds()*limit/l.window.Seconds())
	b.last = now
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
// but NOT consuming. An untracked key (nothing failed yet) passes and, unlike
// allow, allocates no bucket — so well-behaved clients cost no memory. The one
// exception is a saturated table: a failure from that key would be charged to
// the overflow bucket, so that is the budget it must still have.
func (l *Limiter) hasTokens(key string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	var b *bucket
	if el, ok := l.buckets[key]; ok {
		l.lru.MoveToFront(el)
		b = el.Value.(*bucket)
	} else if l.saturated(now) {
		b = &l.overflow
	} else {
		return true
	}
	l.refill(b, l.burst, now)
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

// WrapAnon returns next guarded by the limiter for requests authenticated(r)
// does not vouch for, keyed on client IP alone (a global per-IP anonymous
// budget across all paths). Merely carrying an Authorization header is not
// enough to be exempt — that let `Bearer junk` switch the limiter off for
// anyone who sent it. All requests pass through untouched when the limiter is
// disabled. Unlike Wrap it takes/returns http.Handler so it can wrap the whole
// API mux as outer middleware.
func (l *Limiter) WrapAnon(next http.Handler, authenticated func(*http.Request) bool) http.Handler {
	if !l.Enabled() {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !authenticated(r) && !l.allow(clientip.From(r)) {
			l.rejected(layerAnon)
			tooManyRequests(w, l.window)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// ErrKeyRejected is what a KeyQuota or CallerFunc reports when identity-svc
// judged the request's API key and refused it (unknown, revoked, expired).
var ErrKeyRejected = errors.New("api key rejected")

// KeyQuota identifies the API key behind a request and the per-minute request
// budget that key itself carries. An empty key with a nil error means the
// request is not API-key traffic and is not metered here; ErrKeyRejected means
// identity-svc refused the key; any other error means its identity could not
// be judged. Implemented by principal.Resolver.APIKeyQuota, which answers
// without any identity lookup for session/anonymous traffic.
type KeyQuota func(r *http.Request) (key string, perMinute int, err error)

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
// pace itself instead of discovering the wall. A key the quota lookup refuses
// or cannot judge never reaches next (see refuseIdentity).
//
// This is the per-replica variant; RedisLimiter.WrapAPIKey (redis.go) is the
// shared-bucket one main prefers when Redis is configured.
func (l *Limiter) WrapAPIKey(next http.Handler, quota KeyQuota) http.Handler {
	if !l.Enabled() || quota == nil {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		key, perMinute, err := quota(r)
		if err != nil {
			refuseIdentity(w, r, err)
			return
		}
		if key != "" {
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

// refuseIdentity answers a request whose credential the identity lookup did
// not accept. A key identity-svc rejected is a 401 here, not a pass-through:
// otherwise any `owt_sk_` string is unmetered traffic that skips the anonymous
// limiter and reaches the workers on every public route. An identity backend
// that could not judge it is a 503 at once — passing it on only made the route
// resolve the same token again and wait out a second validate_token timeout.
func refuseIdentity(w http.ResponseWriter, r *http.Request, err error) {
	if errors.Is(err, ErrKeyRejected) {
		apierr.WriteError(w, http.StatusUnauthorized, "Invalid API key", "unauthorized", nil)
		return
	}
	httplog.From(r.Context()).Error("identity resolution unavailable", "err", err)
	w.Header().Set("Retry-After", "1")
	apierr.WriteError(w, http.StatusServiceUnavailable, "service unavailable", "unavailable", nil)
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
