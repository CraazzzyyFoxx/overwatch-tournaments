// Package config loads gateway settings from the environment.
//
// The gateway shares the same Postgres/Redis/JWT settings as the Python
// services (see backend/env/*.env), so the variable names mirror them.
package config

import (
	"fmt"
	"net"
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
	Port             string
	MetricsPort      string
	Environment      string
	JWTSecret        string
	RedisURL         string
	RabbitMQURL      string
	DatabaseURL      string
	DBPgBouncer      bool
	WSIdleTimeout    time.Duration
	WSReplayLimit    int
	WSAllowedOrigins []string
	AuthRateLimit    int
	AuthRateWindow   time.Duration
	// WSCustomDomainRateLimit/Window bound how often ws.Handler's dynamic
	// custom-domain Origin lookup (see acceptOptionsFor) may run per client
	// IP. /ws carries neither auth nor the outer nginx-level limiter that
	// guards /api/auth/*, so this is the only per-IP throttle on a lookup
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
	Upstreams      Upstreams
	Sentry         Sentry
	Tracing        Tracing
	Log            Log
	Docs           Docs
}

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

// Upstreams are the base URLs of the existing services the gateway proxies to.
// Defaults match the docker-compose service names / ports.
type Upstreams struct {
	Parser    string
	Analytics string
	Frontend  string
}

// Sentry holds the optional error-monitoring / tracing settings. An empty DSN
// disables the SDK entirely, so the gateway behaves exactly as before.
type Sentry struct {
	DSN              string
	Environment      string
	Release          string
	TracesSampleRate float64
}

// Load reads configuration from environment variables, applying defaults.
// It returns an error only for settings that have no safe default (JWT secret).
func Load() (*Config, error) {
	secret := os.Getenv("JWT_SECRET_KEY")
	if secret == "" {
		return nil, fmt.Errorf("JWT_SECRET_KEY is required")
	}
	// Reject weak secrets at startup: a short HS256 key is brute-forceable, and
	// this key signs every access/service JWT the gateway validates.
	if len(secret) < 32 {
		return nil, fmt.Errorf("JWT_SECRET_KEY must be at least 32 characters (got %d)", len(secret))
	}

	dbURL := os.Getenv("GATEWAY_DATABASE_URL")
	if dbURL == "" {
		dbURL = buildDatabaseURL()
	}

	env := getenv("GATEWAY_ENV", getenv("SENTRY_ENVIRONMENT", "development"))
	production := strings.EqualFold(env, "production")

	// RabbitMQ carries every RPC into the domain services. Never silently fall
	// back to the guest:guest dev credentials in production — require an explicit
	// URL there (fail-closed, like JWT_SECRET_KEY).
	rabbitURL := os.Getenv("RABBITMQ_URL")
	if rabbitURL == "" {
		if production {
			return nil, fmt.Errorf("RABBITMQ_URL is required in production")
		}
		rabbitURL = "amqp://guest:guest@rabbitmq:5672"
	}

	return &Config{
		Port:                     getenv("GATEWAY_PORT", "8080"),
		MetricsPort:              getenv("GATEWAY_METRICS_PORT", "9110"),
		Environment:              env,
		JWTSecret:                secret,
		RedisURL:                 getenv("REDIS_URL", "redis://redis:6379"),
		RabbitMQURL:              rabbitURL,
		DatabaseURL:              dbURL,
		DBPgBouncer:              getenvBool("DB_PGBOUNCER", false),
		WSIdleTimeout:            time.Duration(getenvInt("WS_IDLE_TIMEOUT", 60)) * time.Second,
		WSReplayLimit:            getenvInt("WS_REPLAY_LIMIT", 500),
		WSAllowedOrigins:         splitCSV(getenv("GATEWAY_WS_ALLOWED_ORIGINS", defaultWSAllowedOrigins)),
		AuthRateLimit:            getenvInt("GATEWAY_AUTH_RATE_LIMIT", 10),
		AuthRateWindow:           time.Duration(getenvInt("GATEWAY_AUTH_RATE_WINDOW", 60)) * time.Second,
		WSCustomDomainRateLimit:  getenvInt("GATEWAY_WS_CUSTOM_DOMAIN_RATE_LIMIT", 30),
		WSCustomDomainRateWindow: time.Duration(getenvInt("GATEWAY_WS_CUSTOM_DOMAIN_RATE_WINDOW", 10)) * time.Second,
		AnonRateLimit:            getenvInt("GATEWAY_ANON_RATE_LIMIT", 0), // 0 = disabled (pass-through)
		AnonRateWindow:           time.Duration(getenvInt("GATEWAY_ANON_RATE_WINDOW", 10)) * time.Second,
		Upstreams: Upstreams{
			Parser:    getenv("UPSTREAM_PARSER", "http://parser:8002"),
			Analytics: getenv("UPSTREAM_ANALYTICS", "http://analytics:8006"),
			Frontend:  getenv("UPSTREAM_FRONTEND", "http://frontend:3000"),
		},
		Sentry: Sentry{
			DSN:              os.Getenv("SENTRY_DSN"),
			Environment:      getenv("SENTRY_ENVIRONMENT", "development"),
			Release:          os.Getenv("SENTRY_RELEASE"),
			TracesSampleRate: getenvFloat("SENTRY_TRACES_SAMPLE_RATE", 0.2),
		},
		Tracing: Tracing{
			Enabled:      getenvBool("TRACING_ENABLED", false),
			OTLPEndpoint: getenv("OTLP_ENDPOINT", "http://otel-collector:4317"),
			SamplerArg:   getenvFloat("OTEL_TRACES_SAMPLER_ARG", 0.1),
		},
		Log: Log{
			Level: getenv("LOG_LEVEL", "info"),
			File:  getenv("LOG_FILE", "/logs/gateway.log"),
		},
		Docs: Docs{
			Enabled: getenvBool("GATEWAY_DOCS_ENABLED", true),
			// Fail-closed: the admin docs page (which enumerates every admin route)
			// is off unless explicitly enabled via GATEWAY_DOCS_ADMIN=true, rather
			// than guessed from the environment name.
			AdminEnabled: getenvBool("GATEWAY_DOCS_ADMIN", false),
			CDN:          getenv("GATEWAY_DOCS_CDN", "https://cdn.jsdelivr.net/npm/@scalar/api-reference@1.60.0"),
		},
	}, nil
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

func getenvInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}

func getenvBool(key string, fallback bool) bool {
	if v := os.Getenv(key); v != "" {
		if b, err := strconv.ParseBool(v); err == nil {
			return b
		}
	}
	return fallback
}

func getenvFloat(key string, fallback float64) float64 {
	if v := os.Getenv(key); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return fallback
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
