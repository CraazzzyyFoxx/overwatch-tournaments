package config

import (
	"os"
	"reflect"
	"testing"
	"time"
)

// clearGatewayEnv removes every env var Load reads so tests start from a
// clean slate and don't inherit values from the shell running `go test`.
func clearGatewayEnv(t *testing.T) {
	t.Helper()
	keys := []string{
		"JWT_SECRET_KEY", "GATEWAY_DATABASE_URL", "GATEWAY_ENV", "SENTRY_ENVIRONMENT",
		"RABBITMQ_URL", "GATEWAY_WS_ALLOWED_ORIGINS",
		"GATEWAY_WS_CUSTOM_DOMAIN_RATE_LIMIT", "GATEWAY_WS_CUSTOM_DOMAIN_RATE_WINDOW",
	}
	for _, k := range keys {
		v, ok := os.LookupEnv(k)
		os.Unsetenv(k)
		if ok {
			t.Cleanup(func(k, v string) func() {
				return func() { os.Setenv(k, v) }
			}(k, v))
		}
	}
}

func TestLoad_WSAllowedOriginsDefault(t *testing.T) {
	clearGatewayEnv(t)
	os.Setenv("JWT_SECRET_KEY", "12345678901234567890123456789012")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	want := []string{"https://owt.craazzzyyfoxx.me", "https://*.owt.craazzzyyfoxx.me"}
	if !reflect.DeepEqual(cfg.WSAllowedOrigins, want) {
		t.Fatalf("WSAllowedOrigins = %v, want %v", cfg.WSAllowedOrigins, want)
	}
}

func TestLoad_WSAllowedOriginsOverride(t *testing.T) {
	clearGatewayEnv(t)
	os.Setenv("JWT_SECRET_KEY", "12345678901234567890123456789012")
	os.Setenv("GATEWAY_WS_ALLOWED_ORIGINS", "https://custom.example.com")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	want := []string{"https://custom.example.com"}
	if !reflect.DeepEqual(cfg.WSAllowedOrigins, want) {
		t.Fatalf("WSAllowedOrigins = %v, want %v", cfg.WSAllowedOrigins, want)
	}
}

// TestLoad_WSCustomDomainRateLimitDefault pins the fallback ws.Handler's
// dynamic custom-domain Origin lookup uses when GATEWAY_WS_CUSTOM_DOMAIN_RATE_LIMIT
// / _WINDOW are unset (see the WSCustomDomainRateLimit/Window doc comment in
// config.go): 30 requests per 10s.
func TestLoad_WSCustomDomainRateLimitDefault(t *testing.T) {
	clearGatewayEnv(t)
	os.Setenv("JWT_SECRET_KEY", "12345678901234567890123456789012")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	if cfg.WSCustomDomainRateLimit != 30 {
		t.Fatalf("WSCustomDomainRateLimit = %d, want 30", cfg.WSCustomDomainRateLimit)
	}
	if cfg.WSCustomDomainRateWindow != 10*time.Second {
		t.Fatalf("WSCustomDomainRateWindow = %v, want 10s", cfg.WSCustomDomainRateWindow)
	}
}

// TestLoad_WSCustomDomainRateLimitOverride proves both env vars are parsed
// (limit as a bare int, window as whole seconds) rather than silently
// falling back to the default on any override.
func TestLoad_WSCustomDomainRateLimitOverride(t *testing.T) {
	clearGatewayEnv(t)
	os.Setenv("JWT_SECRET_KEY", "12345678901234567890123456789012")
	os.Setenv("GATEWAY_WS_CUSTOM_DOMAIN_RATE_LIMIT", "5")
	os.Setenv("GATEWAY_WS_CUSTOM_DOMAIN_RATE_WINDOW", "42")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	if cfg.WSCustomDomainRateLimit != 5 {
		t.Fatalf("WSCustomDomainRateLimit = %d, want 5", cfg.WSCustomDomainRateLimit)
	}
	if cfg.WSCustomDomainRateWindow != 42*time.Second {
		t.Fatalf("WSCustomDomainRateWindow = %v, want 42s", cfg.WSCustomDomainRateWindow)
	}
}
