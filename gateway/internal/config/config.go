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
	"time"
)

// Config holds all runtime settings for the gateway.
type Config struct {
	Port          string
	MetricsPort   string
	JWTSecret     string
	RedisURL      string
	RabbitMQURL   string
	DatabaseURL   string
	DBPgBouncer   bool
	WSIdleTimeout time.Duration
	WSReplayLimit int
	Upstreams     Upstreams
	Sentry        Sentry
	Log           Log
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

	dbURL := os.Getenv("GATEWAY_DATABASE_URL")
	if dbURL == "" {
		dbURL = buildDatabaseURL()
	}

	return &Config{
		Port:          getenv("GATEWAY_PORT", "8080"),
		MetricsPort:   getenv("GATEWAY_METRICS_PORT", "9110"),
		JWTSecret:     secret,
		RedisURL:      getenv("REDIS_URL", "redis://redis:6379"),
		RabbitMQURL:   getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672"),
		DatabaseURL:   dbURL,
		DBPgBouncer:   getenvBool("DB_PGBOUNCER", false),
		WSIdleTimeout: time.Duration(getenvInt("WS_IDLE_TIMEOUT", 60)) * time.Second,
		WSReplayLimit: getenvInt("WS_REPLAY_LIMIT", 500),
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
		Log: Log{
			Level: getenv("LOG_LEVEL", "info"),
			File:  getenv("LOG_FILE", "/logs/gateway.log"),
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
