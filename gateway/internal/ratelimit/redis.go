package ratelimit

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"slices"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
)

// rpmKeyFormat is the Redis key holding one API key's per-minute request count.
// It MUST stay byte-identical to shared/quota/enforcer.py's _rpm_key
// ("q:{namespace}:{principal_id}:rpm", namespace "key" for an API key): the
// gateway is the only writer (every keyed request spends one token here) and
// the Python usage view reads the same key back, so a rename on either side
// turns the published consumption into a permanent zero.
// backend/tests/test_quota_key_parity.py fails on drift.
const rpmKeyFormat = "q:key:%s:rpm"

// rpmWindow is the per-minute window. Fixed, not taken from the Limiter's
// config: the key is shared across languages, so its expiry is part of the
// contract rather than a local knob.
const rpmWindow = 60 * time.Second

// redisTimeout bounds the metering round-trip. The limiter fails open, so a
// stalled Redis costs one request this much latency — never availability.
const redisTimeout = 250 * time.Millisecond

// wsRPMKeyFormat is the Redis key holding ONE WORKSPACE's per-minute request
// count, across every credential spending it. Same contract as rpmKeyFormat: it
// is shared with shared/quota/enforcer.py's _rpm_key (namespace "ws"), and
// backend/tests/test_quota_key_parity.py parses this exact declaration. While
// QUOTA_EDGE_WORKSPACE_METERING is on the gateway OWNS this bucket — the Python
// enforcer stops charging it, so every REST request is counted once.
const wsRPMKeyFormat = "q:ws:%d:rpm"

// publicRPMKeyFormat holds traffic a workspace caused but that no member can be
// billed for: anonymous visitors and signed-in non-members hitting its public
// surface. It is STATISTICS ONLY — nothing is ever refused on this bucket, so a
// tenant cannot be taken offline by strangers spending its budget.
const publicRPMKeyFormat = "q:pub:ws:%d:rpm"

// noLimit marks a bucket that is counted but has no ceiling — a workspace whose
// plan sets no requests_per_minute, and every public bucket.
const noLimit = -1

// rpmScript mirrors the requests_per_minute branch of the Python enforcer's
// CHARGE_SCRIPT: read first, and only then INCR (+ EXPIRE on the first hit of a
// window). Checking before incrementing is what makes a refused request cost
// nothing and keeps TTL an honest Retry-After — an INCR-then-compare limiter
// would keep pushing the counter up for the whole duration of a flood.
//
// Returns {allowed, used, ttl}.
var rpmScript = redis.NewScript(`
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local used = tonumber(redis.call("GET", KEYS[1]) or "0")
local ttl = redis.call("TTL", KEYS[1])
if ttl < 1 then ttl = window end
if used + 1 > limit then
  return {0, used, ttl}
end
used = redis.call("INCR", KEYS[1])
if used == 1 then
  redis.call("EXPIRE", KEYS[1], window)
  ttl = window
end
return {1, used, ttl}
`)

// RedisLimiter meters API-key traffic against a bucket every gateway replica
// shares, which is what closes the "N pods means N x the limit" gap the
// in-process buckets have (see the package comment). It is the API-key variant
// only: the anonymous and auth-endpoint limiters stay local, where a guardrail
// is all that is wanted.
//
// Everything that is not the counter itself is delegated to the *Limiter it
// wraps — the kill switch, the default budget for a key that carries no
// requests_per_minute, and the entire request path when no Redis client is
// configured.
type RedisLimiter struct {
	rdb      redis.Scripter
	local    *Limiter
	logger   *slog.Logger
	fallback func()
}

// NewRedis builds the shared-bucket variant over an ALREADY EXISTING client —
// the gateway's realtime-bus one — so metering adds no second connection pool.
// A nil client (Redis unconfigured) degrades every call to local's in-process
// bucket. onFallback, when non-nil, counts requests that went unmetered because
// Redis was unreachable.
func NewRedis(rdb redis.Scripter, local *Limiter, logger *slog.Logger, onFallback func()) *RedisLimiter {
	return &RedisLimiter{rdb: rdb, local: local, logger: logger, fallback: onFallback}
}

// WrapAPIKey is Limiter.WrapAPIKey with the counter in Redis: same per-minute
// semantics, same 429 body, same pass-through for session/anonymous traffic and
// for a disabled limiter, but the budget is spent once per key rather than once
// per key per replica.
func (l *RedisLimiter) WrapAPIKey(next http.Handler, quota KeyQuota) http.Handler {
	if l.rdb == nil {
		return l.local.WrapAPIKey(next, quota)
	}
	if !l.local.Enabled() || quota == nil {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		key, perMinute, ok := quota(r)
		if !ok {
			next.ServeHTTP(w, r)
			return
		}
		limit := perMinute
		if limit <= 0 {
			limit = int(l.local.burst)
		}
		allowed, remaining, reset := l.allow(r.Context(), key, limit)
		writeRateLimitHeaders(w, limit, remaining, reset)
		if !allowed {
			l.local.rejected(layerAPIKey)
			// The window's real remaining TTL, not the nominal minute: the
			// shared counter knows exactly when the budget comes back, so
			// Retry-After can stop overstating it.
			tooManyRequests(w, time.Duration(reset)*time.Second)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// allow spends one request token for apiKeyID and reports what is left of the
// budget plus the seconds until it resets.
func (l *RedisLimiter) allow(ctx context.Context, apiKeyID string, limit int) (allowed bool, remaining, reset int) {
	window := int(rpmWindow.Seconds())
	ctx, cancel := context.WithTimeout(ctx, redisTimeout)
	defer cancel()

	res, err := rpmScript.Run(ctx, l.rdb, []string{fmt.Sprintf(rpmKeyFormat, apiKeyID)}, limit, window).Slice()
	if err != nil {
		return l.failOpen(apiKeyID, err, limit, window)
	}
	if len(res) < 3 {
		return l.failOpen(apiKeyID, fmt.Errorf("unexpected reply %v", res), limit, window)
	}
	used := asInt(res[1])
	if remaining = limit - used; remaining < 0 {
		remaining = 0
	}
	return asInt(res[0]) == 1, remaining, asInt(res[2])
}

// failOpen allows a request the shared counter could not judge. Availability
// beats exactness here: nginx limit_req still bounds the flood from outside and
// the workers re-check their own quotas in Redis, so refusing real paying
// traffic because a counter is unreachable would trade a rate limit for an
// outage. The headers report the full budget rather than a consumed token —
// nothing was counted, and telling a client to back off against a number that
// is not moving would be a lie.
func (l *RedisLimiter) failOpen(apiKeyID string, err error, limit, window int) (bool, int, int) {
	if l.fallback != nil {
		l.fallback()
	}
	if l.logger != nil {
		l.logger.Warn("api key request left unmetered: redis unavailable",
			"api_key_id", apiKeyID, "error", err)
	}
	return true, limit, window
}

// asInt coerces one Lua reply element. Lua numbers arrive as int64; a stringly
// typed element is tolerated so a future script edit cannot turn a real count
// into a silent zero.
func asInt(v any) int {
	switch n := v.(type) {
	case int64:
		return int(n)
	case string:
		parsed, err := strconv.Atoi(n)
		if err != nil {
			return 0
		}
		return parsed
	}
	return 0
}

// meterScript charges up to TWO buckets in one round trip, all-or-nothing:
// KEYS[1] is the principal (API key) bucket and KEYS[2] the workspace or public
// one; an empty key is skipped, a limit of -1 means "count, never refuse".
// Every bucket is CHECKED before anything is incremented, so a request refused
// by either ceiling costs nothing anywhere — the alternative (charge key, then
// discover the workspace is full) would burn a client's own budget on requests
// it never got served.
//
// Returns {allowed, refused_index, used, ttl}: on a refusal the index names
// which bucket said no with ITS used/ttl (so Retry-After is that bucket's real
// reset), and on success the counters belong to KEYS[1] — the only bucket whose
// numbers are published as RateLimit-* headers.
var meterScript = redis.NewScript(`
local window = tonumber(ARGV[3])
local limits = {tonumber(ARGV[1]), tonumber(ARGV[2])}
for i = 1, 2 do
  local key = KEYS[i]
  local limit = limits[i]
  if key ~= "" and limit >= 0 then
    local used = tonumber(redis.call("GET", key) or "0")
    if used + 1 > limit then
      local ttl = redis.call("TTL", key)
      if ttl < 1 then ttl = window end
      return {0, i, used, ttl}
    end
  end
end
local used = 0
local ttl = window
for i = 1, 2 do
  local key = KEYS[i]
  if key ~= "" then
    local n = redis.call("INCR", key)
    if n == 1 then
      redis.call("EXPIRE", key, window)
    end
    if i == 1 then
      used = n
      local t = redis.call("TTL", key)
      if t >= 1 then ttl = t end
    end
  end
end
return {1, 0, used, ttl}
`)

// Caller is the identity behind one request, reduced to what metering needs.
// It is a plain struct rather than the resolver's own type so this package
// keeps not knowing about identity resolution (main.go adapts principal.Info).
type Caller struct {
	// APIKey distinguishes machine traffic (metered on its own key bucket and
	// refusable there) from a browser session (counted on the workspace bucket
	// only).
	APIKey bool
	// APIKeyID is the key's numeric id — the q:key bucket, zero for a session.
	APIKeyID int64
	// RequestsPerMinute is the key's own budget; 0 means the platform default.
	RequestsPerMinute int
	// WorkspaceID is the single workspace an API key is pinned to.
	WorkspaceID int64
	// WorkspaceIDs is every workspace the caller belongs to.
	WorkspaceIDs []int64
	// Superuser may act on a workspace it is not a member of.
	Superuser bool
}

// CallerFunc resolves the identity behind a request. ok=false means the
// identity could not be judged (backend down, token rejected) and the request
// must pass through UNMETERED — the route behind it answers 401/503, and a 429
// there would be a lie.
type CallerFunc func(r *http.Request) (Caller, bool)

// WorkspaceLimitFunc resolves a workspace's effective workspace-scope
// requests_per_minute: limited=false means no ceiling, exists=false means no
// such workspace. Implemented by workspace.Store.WorkspaceRequestsPerMinute.
type WorkspaceLimitFunc func(ctx context.Context, workspaceID int64) (limit int, limited bool, exists bool, err error)

// plan is what one request will charge: at most one principal bucket and one
// workspace/public bucket, each with its ceiling (noLimit = count only).
type plan struct {
	keyBucket string
	keyLimit  int
	wsBucket  string
	wsLimit   int
}

// WrapMetered is the QUOTA_EDGE_WORKSPACE_METERING variant of WrapAPIKey: it
// counts EVERY request against its workspace, not just API-key ones, and
// enforces the workspace's own requests_per_minute ceiling at the edge.
//
// Attribution, in one pass (see plan):
//   - anonymous + ?workspace_id= naming a real workspace -> public bucket,
//     statistics only, never refused;
//   - API key -> its own q:key bucket (unchanged: same budget, same headers,
//     same 429) AND its workspace's bucket;
//   - session -> the workspace bucket of a workspace it belongs to (or any
//     workspace, for a superuser); a workspace it is NOT a member of goes to
//     the public bucket. No per-user bucket at the edge: the session plan is
//     sized for metered operations, and one UI page load fans out into enough
//     calls to exhaust it.
//
// Everything else passes through untouched: an unjudgeable identity, a request
// that names no workspace at all, and a workspace that does not exist.
func (l *RedisLimiter) WrapMetered(next http.Handler, who CallerFunc, ceiling WorkspaceLimitFunc) http.Handler {
	if l.rdb == nil || who == nil || ceiling == nil {
		return next
	}
	window := int(rpmWindow.Seconds())
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p := l.plan(r, who, ceiling)
		if p.keyBucket == "" && p.wsBucket == "" {
			next.ServeHTTP(w, r)
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), redisTimeout)
		res, err := meterScript.Run(ctx, l.rdb, []string{p.keyBucket, p.wsBucket}, p.keyLimit, p.wsLimit, window).Slice()
		cancel()
		if err == nil && len(res) < 4 {
			err = fmt.Errorf("unexpected reply %v", res)
		}
		if err != nil {
			// Fail open, exactly like the single-bucket path: an unreachable
			// counter must not turn a rate limit into an outage.
			if l.fallback != nil {
				l.fallback()
			}
			if l.logger != nil {
				l.logger.Warn("request left unmetered: redis unavailable",
					"key_bucket", p.keyBucket, "workspace_bucket", p.wsBucket, "error", err)
			}
			if p.keyBucket != "" {
				writeRateLimitHeaders(w, p.keyLimit, p.keyLimit, window)
			}
			next.ServeHTTP(w, r)
			return
		}

		allowed, refused, used, ttl := asInt(res[0]) == 1, asInt(res[1]), asInt(res[2]), asInt(res[3])
		// RateLimit-* describes the key bucket and only it — a session has no
		// published per-request budget, and on a WORKSPACE refusal nothing was
		// charged to the key bucket, so its counters are unknown here.
		if p.keyBucket != "" && (allowed || refused == 1) {
			remaining := p.keyLimit - used
			if remaining < 0 {
				remaining = 0
			}
			writeRateLimitHeaders(w, p.keyLimit, remaining, ttl)
		}
		if allowed {
			next.ServeHTTP(w, r)
			return
		}
		if refused == 1 {
			l.local.rejected(layerAPIKey)
		} else {
			l.local.rejected(layerWorkspace)
		}
		tooManyRequests(w, time.Duration(ttl)*time.Second)
	})
}

// plan decides which buckets a request charges. It never widens authority: a
// workspace a caller cannot name is simply not charged to it.
func (l *RedisLimiter) plan(r *http.Request, who CallerFunc, ceiling WorkspaceLimitFunc) plan {
	p := plan{keyLimit: noLimit, wsLimit: noLimit}
	queried := queryWorkspaceID(r)

	if isAnonymous(r) {
		p.wsBucket = l.publicBucket(r, ceiling, queried)
		return p
	}

	c, ok := who(r)
	if !ok {
		return p
	}

	if c.APIKey {
		// The kill switch stays exactly where it was: a non-positive
		// GATEWAY_API_KEY_RATE_LIMIT disables the per-key bucket, and only it —
		// workspace metering is governed by its own flag.
		if l.local.Enabled() && c.APIKeyID > 0 {
			p.keyBucket = fmt.Sprintf(rpmKeyFormat, strconv.FormatInt(c.APIKeyID, 10))
			if p.keyLimit = c.RequestsPerMinute; p.keyLimit <= 0 {
				p.keyLimit = int(l.local.burst)
			}
		}
		workspace := c.WorkspaceID
		if workspace <= 0 && len(c.WorkspaceIDs) == 1 {
			workspace = c.WorkspaceIDs[0]
		}
		p.wsBucket, p.wsLimit = l.workspaceBucket(r, ceiling, workspace)
		return p
	}

	switch {
	case queried > 0 && (c.Superuser || slices.Contains(c.WorkspaceIDs, queried)):
		p.wsBucket, p.wsLimit = l.workspaceBucket(r, ceiling, queried)
	case queried > 0:
		// Signed in, but a stranger to this tenant: its traffic is the tenant's
		// to see, never the tenant's to be refused for.
		p.wsBucket = l.publicBucket(r, ceiling, queried)
	case len(c.WorkspaceIDs) == 1:
		p.wsBucket, p.wsLimit = l.workspaceBucket(r, ceiling, c.WorkspaceIDs[0])
	}
	return p
}

// workspaceBucket names the metered bucket for a workspace the caller may be
// charged for, plus its ceiling. A ceiling that cannot be read still COUNTS the
// request (a failed policy read must not silently stop metering) but enforces
// nothing — the Python workers still check their own quotas.
func (l *RedisLimiter) workspaceBucket(r *http.Request, ceiling WorkspaceLimitFunc, workspaceID int64) (string, int) {
	if workspaceID <= 0 {
		return "", noLimit
	}
	limit, limited, exists, err := ceiling(r.Context(), workspaceID)
	if err != nil {
		if l.logger != nil {
			l.logger.Warn("workspace quota unreadable: counting without a ceiling",
				"workspace_id", workspaceID, "error", err)
		}
		return fmt.Sprintf(wsRPMKeyFormat, workspaceID), noLimit
	}
	if !exists {
		return "", noLimit
	}
	if !limited {
		return fmt.Sprintf(wsRPMKeyFormat, workspaceID), noLimit
	}
	return fmt.Sprintf(wsRPMKeyFormat, workspaceID), limit
}

// publicBucket names the statistics bucket for unattributable traffic, and only
// for a workspace that really exists: the id comes from an anonymous query
// string, so inventing keys for it would let anyone grow Redis at will. An
// unreadable policy read is treated as "unknown workspace" for the same reason.
func (l *RedisLimiter) publicBucket(r *http.Request, ceiling WorkspaceLimitFunc, workspaceID int64) string {
	if workspaceID <= 0 {
		return ""
	}
	_, _, exists, err := ceiling(r.Context(), workspaceID)
	if err != nil {
		if l.logger != nil {
			l.logger.Warn("public traffic left uncounted: workspace lookup failed",
				"workspace_id", workspaceID, "error", err)
		}
		return ""
	}
	if !exists {
		return ""
	}
	return fmt.Sprintf(publicRPMKeyFormat, workspaceID)
}

// queryWorkspaceID reads the ?workspace_id= a request addresses a tenant with —
// the same parameter edge.dispatch forwards to the workers. 0 when absent,
// malformed or non-positive.
func queryWorkspaceID(r *http.Request) int64 {
	id, err := strconv.ParseInt(r.URL.Query().Get("workspace_id"), 10, 64)
	if err != nil || id <= 0 {
		return 0
	}
	return id
}
