package ratelimit

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
)

// rpmKeyFormat is the Redis key holding one API key's per-minute request count.
// It MUST stay byte-identical to shared/quota/enforcer.py's _rpm_key
// ("q:{namespace}:{principal_id}:rpm", namespace "key" for an API key): the
// gateway and the Python enforcers deliberately spend the SAME bucket, so a
// rename on either side silently hands every key a second full budget.
// backend/tests/test_quota_key_parity.py fails on drift.
const rpmKeyFormat = "q:key:%s:rpm"

// rpmWindow is the per-minute window. Fixed, not taken from the Limiter's
// config: the key is shared across languages, so its expiry is part of the
// contract rather than a local knob.
const rpmWindow = 60 * time.Second

// redisTimeout bounds the metering round-trip. The limiter fails open, so a
// stalled Redis costs one request this much latency — never availability.
const redisTimeout = 250 * time.Millisecond

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
