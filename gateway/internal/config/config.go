// Package config loads gateway settings from the environment.
//
// The gateway shares the same Postgres/Redis/JWT settings as the Python
// services (see backend/env/*.env), so the variable names mirror them.
package config

import (
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

// defaultWSAllowedOrigins is the fallback for GATEWAY_WS_ALLOWED_ORIGINS. It
// covers the platform apex plus every tenant subdomain (workspace white-label
// hosts, see docs/superpowers/specs/2026-07-06-workspace-multidomain-design.md)
// so that ws.NewHandler never receives an empty allow-list in a default
// deployment and falls back to AcceptOptions.InsecureSkipVerify. Operators can
// still override this with an explicit (possibly empty) CSV, but the default
// itself must never leave production open.
const defaultWSAllowedOrigins = "https://owt.craazzzyyfoxx.me,https://*.owt.craazzzyyfoxx.me"

// DefaultWSAllowedOrigins is the parsed form of defaultWSAllowedOrigins,
// exported so callers outside this package (e.g. ws package tests) can
// assert against the exact production default without duplicating the
// literal and risking drift.
var DefaultWSAllowedOrigins = splitCSV(defaultWSAllowedOrigins)

// Config holds all runtime settings for the gateway.
type Config struct {
	Port        string
	MetricsPort string
	Environment string
	// JWTPublicKey verifies identity-svc's EdDSA access tokens; the gateway
	// never holds the signing key.
	JWTPublicKey ed25519.PublicKey
	RedisURL     string
	RabbitMQURL  string
	DatabaseURL  string
	DBPgBouncer  bool
	// DBMaxConns caps the gateway's own Postgres pool (ACL / event-replay /
	// custom-domain reads). Modest by default since the gateway shares Postgres
	// with the workers; raise it if WS/ACL load starves the pool.
	DBMaxConns int
	// DBStatementTimeout is a server-side backstop cancelling any gateway query
	// running longer, so a slow/hung Postgres can't pin pool connections against
	// the unauthenticated /ws lookup path. Applied on direct Postgres only
	// (pgBouncer rejects it as a startup parameter — set it on the role there).
	// 0 disables.
	DBStatementTimeout time.Duration
	WSIdleTimeout      time.Duration
	WSReplayLimit      int
	WSAllowedOrigins   []string
	// WSMaxAnonConnsPerIP caps concurrent anonymous /ws connections per client
	// IP (0 = unlimited). /ws has no auth and no per-IP limiter in front of it,
	// so this is the only bound on one IP opening sockets; keep it generous
	// because shared NATs put many legitimate visitors behind one IP.
	// WSMaxTopicsAnon/Auth cap simultaneous topic subscriptions per connection,
	// tighter for anonymous clients (0 = unlimited).
	WSMaxAnonConnsPerIP int
	WSMaxTopicsAnon     int
	WSMaxTopicsAuth     int
	AuthRateLimit       int
	AuthRateWindow      time.Duration
	// WSCustomDomainRateLimit/Window bound how often ws.Handler's dynamic
	// custom-domain Origin lookup (see acceptOptionsFor) may run per client
	// IP. /ws carries neither auth nor the outer nginx-level limiter that
	// guards /api/v1/auth/*, so this is the only per-IP throttle on a lookup
	// path that is otherwise reachable by anyone with distinct fake Origin
	// headers. The default (30 requests / 10s) is generous relative to any
	// realistic WS reconnect storm from a single IP.
	WSCustomDomainRateLimit  int
	WSCustomDomainRateWindow time.Duration
	// AnonRateLimit/Window bound anonymous (no-bearer) API traffic per client
	// IP across all /api paths — a global anonymous budget layered under the
	// coarse nginx limit_req. Authenticated requests (Authorization: Bearer …)
	// bypass it. Disabled by default (limit 0): set GATEWAY_ANON_RATE_LIMIT to
	// enable. Keep it generous — a single anonymous page view fans out into many
	// public API calls, so a tight limit would throttle legitimate visitors.
	AnonRateLimit  int
	AnonRateWindow time.Duration
	// APIKeyRateLimit is the per-minute request budget for a workspace-scoped
	// API key that does not carry its own requests_per_minute. A key's own
	// value always wins when present (legacy snapshots). The window is fixed
	// at one minute because this quota is defined per minute.
	// GATEWAY_API_KEY_RATE_LIMIT <= 0 disables per-key throttling entirely
	// (the balancer worker still enforces its own Redis-backed job quotas).
	APIKeyRateLimit int
	// EdgeWorkspaceMetering turns on per-workspace request metering at the
	// gateway edge: EVERY REST request (API key, session, anonymous) is counted
	// against its workspace's q:ws:{id}:rpm bucket and refused when the
	// workspace-scope requests_per_minute ceiling is crossed. Traffic that
	// cannot be attributed to a member (anonymous or non-member) is counted in a
	// statistics-only q:pub:ws:{id}:rpm bucket and never refused.
	//
	// Off by default, and OFF means byte-for-byte today's behaviour (per-key
	// metering only). Shared with the Python enforcer
	// (QUOTA_EDGE_WORKSPACE_METERING in backend/env/common.env): when it is on,
	// Python stops charging q:ws itself because the gateway owns that bucket.
	EdgeWorkspaceMetering bool
	// ResponseCacheTTL is the staleness backstop for the gateway's in-memory
	// response cache on anonymous public tournament reads (internal/respcache).
	// Invalidation is event-driven (the worker's tournament_changed consumer
	// publishes realtime:tournament:{id}:bracket, which the cache consumes), so
	// the TTL only bounds staleness for writes that emit no event (e.g. public
	// registration counts) and for missed pub/sub messages. 0 disables the
	// cache entirely (GATEWAY_RESPONSE_CACHE_TTL, seconds).
	ResponseCacheTTL time.Duration
	// RPCMaxInFlight caps concurrent in-flight RPC calls per queue (bulkhead).
	// When a queue is saturated the gateway sheds the request with an immediate
	// 503 instead of queueing it for up to the full RPC timeout. 0 disables.
	RPCMaxInFlight int
	// TrustedProxies are the peers whose X-Forwarded-For / X-Real-IP the
	// gateway believes (clientip.SetTrustedProxies); any other peer is keyed by
	// its socket address, so a client cannot choose its own rate-limit bucket by
	// sending the header. GATEWAY_TRUSTED_PROXIES: CSV of CIDRs (a bare IP is that
	// one host); default loopback + RFC1918 + ULA, where a same-network reverse
	// proxy sits.
	TrustedProxies []netip.Prefix
	// UploadMemoryBudget caps the bytes multipart uploads and match ingest may
	// hold in memory at once (internal/upload). A request that would cross it is
	// refused with 503 + Retry-After BEFORE its body is read, instead of growing
	// the heap toward the container limit. GATEWAY_UPLOAD_MEMORY_BUDGET_MB,
	// 0 = unlimited.
	UploadMemoryBudget int64
	// WriteTimeout is the REST response deadline (http.Server.WriteTimeout,
	// counted from the end of the request headers), so a slow reader cannot pin
	// a handler and its buffers forever. It must cover the body read plus the
	// longest RPC (120s edge ceiling) plus the write. GATEWAY_WRITE_TIMEOUT,
	// seconds, 0 disables. A hijacked WebSocket inherits the deadline, so the WS
	// path must clear it after the upgrade.
	WriteTimeout time.Duration
	// ShutdownTimeout bounds the graceful HTTP drain on SIGTERM; requests still
	// running after it are cut. Keep the container stop grace period above it.
	// GATEWAY_SHUTDOWN_TIMEOUT, seconds.
	ShutdownTimeout time.Duration
	Sentry          Sentry
	Tracing         Tracing
	Log             Log
	Docs            Docs
}

// defaultTrustedProxies is the GATEWAY_TRUSTED_PROXIES fallback: loopback plus
// the private ranges (RFC1918, IPv6 ULA) a reverse proxy in the same Docker or
// LAN network connects from.
const defaultTrustedProxies = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"

// Tracing holds the OpenTelemetry settings. The variable names mirror the
// Python services (backend/shared/observability/tracing.py) so one env block
// configures the whole stack. The sampler kind is fixed to
// parentbased_traceidratio (OTEL_TRACES_SAMPLER is not parsed).
type Tracing struct {
	Enabled      bool    // TRACING_ENABLED
	OTLPEndpoint string  // OTLP_ENDPOINT
	SamplerArg   float64 // OTEL_TRACES_SAMPLER_ARG
}

// Docs holds the Scalar API-documentation settings. Two pages are served from
// the route tables the gateway already owns: a public one (always on) and an
// admin one that is gated to non-production environments.
type Docs struct {
	// Enabled is the master switch for the public docs page + spec.
	Enabled bool
	// AdminEnabled gates the admin docs page + spec. Fail-closed: defaults to off
	// and is only enabled by an explicit GATEWAY_DOCS_ADMIN=true. When off,
	// /api/docs/admin returns 404.
	AdminEnabled bool
	// CDN is the pinned <script src> for the standalone Scalar bundle.
	CDN string
}

// Log holds logging settings. File is the path of the rotating JSON log that
// Promtail tails; an empty File logs to stdout only.
type Log struct {
	Level string
	File  string
}

// Sentry holds the optional error-monitoring / tracing settings. An empty DSN
// disables the SDK entirely, so the gateway behaves exactly as before.
//
// TracesSampleRate defaults to 0 because spans reach Sentry through the
// otel-collector's Sentry Exporter, not this SDK. Turning it on adds a second,
// disconnected copy of every request: sentryhttp wraps the OUTER router, whose
// matched pattern is "/", so its transactions all group under "GET /" while the
// OTel middleware names them by the real route. Errors still link to the OTel
// trace via sentryotel.NewOtelIntegration (see internal/observability).
type Sentry struct {
	DSN              string
	Environment      string
	Release          string
	TracesSampleRate float64
}

// Load reads configuration from environment variables, applying defaults.
// It returns an error for settings that have no safe default (JWT public key)
// and for any variable that is set but malformed — naming every such variable.
func Load() (*Config, error) {
	// identity-svc's Ed25519 public key, base64url without padding (identity
	// logs it at startup; `make jwt-public-key` prints it).
	rawKey := os.Getenv("JWT_PUBLIC_KEY")
	if rawKey == "" {
		return nil, fmt.Errorf("JWT_PUBLIC_KEY is required")
	}
	publicKey, err := base64.RawURLEncoding.DecodeString(strings.TrimRight(rawKey, "="))
	if err != nil || len(publicKey) != ed25519.PublicKeySize {
		return nil, fmt.Errorf("JWT_PUBLIC_KEY must be a base64url Ed25519 public key (%d bytes)", ed25519.PublicKeySize)
	}

	dbURL := os.Getenv("GATEWAY_DATABASE_URL")
	if dbURL == "" {
		dbURL = buildDatabaseURL()
	}

	env := getenv("GATEWAY_ENV", getenv("SENTRY_ENVIRONMENT", "development"))
	production := strings.EqualFold(env, "production")

	// RabbitMQ carries every RPC into the domain services. Never silently fall
	// back to the guest:guest dev credentials in production — require an explicit
	// URL there (fail-closed, like JWT_PUBLIC_KEY).
	rabbitURL := os.Getenv("RABBITMQ_URL")
	if rabbitURL == "" {
		if production {
			return nil, fmt.Errorf("RABBITMQ_URL is required in production")
		}
		rabbitURL = "amqp://guest:guest@rabbitmq:5672"
	}

	e := &envReader{}
	cfg := &Config{
		Port:                     getenv("GATEWAY_PORT", "8080"),
		MetricsPort:              getenv("GATEWAY_METRICS_PORT", "9110"),
		Environment:              env,
		JWTPublicKey:             publicKey,
		RedisURL:                 getenv("REDIS_URL", "redis://redis:6379"),
		RabbitMQURL:              rabbitURL,
		DatabaseURL:              dbURL,
		DBPgBouncer:              e.bool("DB_PGBOUNCER", false),
		DBMaxConns:               e.int("GATEWAY_DB_MAX_CONNS", 16),
		DBStatementTimeout:       time.Duration(e.int("GATEWAY_DB_STATEMENT_TIMEOUT_MS", 15000)) * time.Millisecond,
		WSIdleTimeout:            time.Duration(e.int("WS_IDLE_TIMEOUT", 60)) * time.Second,
		WSReplayLimit:            e.int("WS_REPLAY_LIMIT", 500),
		WSAllowedOrigins:         splitCSV(getenv("GATEWAY_WS_ALLOWED_ORIGINS", defaultWSAllowedOrigins)),
		WSMaxAnonConnsPerIP:      e.int("GATEWAY_WS_MAX_ANON_CONNS_PER_IP", 64),
		WSMaxTopicsAnon:          e.int("GATEWAY_WS_MAX_TOPICS_ANON", 24),
		WSMaxTopicsAuth:          e.int("GATEWAY_WS_MAX_TOPICS_AUTH", 128),
		AuthRateLimit:            e.int("GATEWAY_AUTH_RATE_LIMIT", 10),
		AuthRateWindow:           time.Duration(e.int("GATEWAY_AUTH_RATE_WINDOW", 60)) * time.Second,
		WSCustomDomainRateLimit:  e.int("GATEWAY_WS_CUSTOM_DOMAIN_RATE_LIMIT", 30),
		WSCustomDomainRateWindow: time.Duration(e.int("GATEWAY_WS_CUSTOM_DOMAIN_RATE_WINDOW", 10)) * time.Second,
		AnonRateLimit:            e.int("GATEWAY_ANON_RATE_LIMIT", 0), // 0 = disabled (pass-through)
		AnonRateWindow:           time.Duration(e.int("GATEWAY_ANON_RATE_WINDOW", 10)) * time.Second,
		APIKeyRateLimit:          e.int("GATEWAY_API_KEY_RATE_LIMIT", 60),
		EdgeWorkspaceMetering:    e.bool("QUOTA_EDGE_WORKSPACE_METERING", false),
		ResponseCacheTTL:         time.Duration(e.int("GATEWAY_RESPONSE_CACHE_TTL", 30)) * time.Second,
		RPCMaxInFlight:           e.int("GATEWAY_RPC_MAX_INFLIGHT", 64),
		TrustedProxies:           e.prefixes("GATEWAY_TRUSTED_PROXIES", defaultTrustedProxies),
		UploadMemoryBudget:       int64(e.nonNegative("GATEWAY_UPLOAD_MEMORY_BUDGET_MB", 256)) << 20,
		WriteTimeout:             time.Duration(e.nonNegative("GATEWAY_WRITE_TIMEOUT", 180)) * time.Second,
		ShutdownTimeout:          time.Duration(e.nonNegative("GATEWAY_SHUTDOWN_TIMEOUT", 30)) * time.Second,
		Sentry: Sentry{
			DSN:              os.Getenv("SENTRY_DSN"),
			Environment:      getenv("SENTRY_ENVIRONMENT", "development"),
			Release:          os.Getenv("SENTRY_RELEASE"),
			TracesSampleRate: e.ratio("SENTRY_TRACES_SAMPLE_RATE", 0),
		},
		Tracing: Tracing{
			Enabled:      e.bool("TRACING_ENABLED", false),
			OTLPEndpoint: getenv("OTLP_ENDPOINT", "http://otel-collector:4317"),
			SamplerArg:   e.ratio("OTEL_TRACES_SAMPLER_ARG", 0.1),
		},
		Log: Log{
			Level: getenv("LOG_LEVEL", "info"),
			File:  getenv("LOG_FILE", "/logs/gateway.log"),
		},
		Docs: Docs{
			Enabled: e.bool("GATEWAY_DOCS_ENABLED", true),
			// Fail-closed: the admin docs page (which enumerates every admin route)
			// is off unless explicitly enabled via GATEWAY_DOCS_ADMIN=true, rather
			// than guessed from the environment name.
			AdminEnabled: e.bool("GATEWAY_DOCS_ADMIN", false),
			CDN:          getenv("GATEWAY_DOCS_CDN", "https://cdn.jsdelivr.net/npm/@scalar/api-reference@1.60.0"),
		},
	}
	if err := errors.Join(e.errs...); err != nil {
		return nil, err
	}
	return cfg, nil
}

// buildDatabaseURL assembles a libpq-style URL from the shared POSTGRES_* vars.
func buildDatabaseURL() string {
	u := url.URL{
		Scheme: "postgres",
		User:   url.UserPassword(getenv("POSTGRES_USER", "postgres"), os.Getenv("POSTGRES_PASSWORD")),
		Host:   net.JoinHostPort(getenv("POSTGRES_HOST", "postgres"), getenv("POSTGRES_PORT", "5432")),
		Path:   "/" + getenv("POSTGRES_DB", "postgres"),
	}
	q := u.Query()
	q.Set("sslmode", getenv("POSTGRES_SSLMODE", "disable"))
	u.RawQuery = q.Encode()
	return u.String()
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// envReader parses typed settings. A malformed value is recorded instead of
// being replaced by the default: a typo like GATEWAY_DOCS_ENABLED=fales must
// stop startup, not quietly run with docs on. Load reports every bad variable
// at once. An unset or empty variable still means "use the default".
type envReader struct{ errs []error }

func (e *envReader) fail(key, v, want string) {
	e.errs = append(e.errs, fmt.Errorf("invalid %s=%q: %s", key, v, want))
}

func (e *envReader) int(key string, fallback int) int {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		e.fail(key, v, "want an integer")
		return fallback
	}
	return n
}

// nonNegative is int for settings that have no meaning below zero (the older
// limits keep their documented "<= 0 disables" instead).
func (e *envReader) nonNegative(key string, fallback int) int {
	n := e.int(key, fallback)
	if n < 0 {
		e.fail(key, os.Getenv(key), "want a value >= 0")
		return fallback
	}
	return n
}

func (e *envReader) bool(key string, fallback bool) bool {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		e.fail(key, v, "want true or false")
		return fallback
	}
	return b
}

// ratio reads a fraction in [0, 1] (sample rates).
func (e *envReader) ratio(key string, fallback float64) float64 {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	f, err := strconv.ParseFloat(v, 64)
	if err != nil || !(f >= 0 && f <= 1) { // the negated form also rejects NaN
		e.fail(key, v, "want a number in [0, 1]")
		return fallback
	}
	return f
}

// prefixes reads a CSV of CIDRs; a bare IP address means that single host.
func (e *envReader) prefixes(key, fallback string) []netip.Prefix {
	var out []netip.Prefix
	for _, s := range splitCSV(getenv(key, fallback)) {
		p, err := netip.ParsePrefix(s)
		if err != nil {
			a, aerr := netip.ParseAddr(s)
			if aerr != nil {
				e.fail(key, s, "want a CIDR or an IP address")
				continue
			}
			p = netip.PrefixFrom(a, a.BitLen())
		}
		out = append(out, p.Masked())
	}
	return out
}

// splitCSV parses a comma-separated env value into a trimmed, non-empty slice.
// An empty or blank input yields nil.
func splitCSV(s string) []string {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	parts := strings.Split(s, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if v := strings.TrimSpace(p); v != "" {
			out = append(out, v)
		}
	}
	return out
}
