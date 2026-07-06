package config

import (
	"os"
	"reflect"
	"testing"
)

// clearGatewayEnv removes every env var Load reads so tests start from a
// clean slate and don't inherit values from the shell running `go test`.
func clearGatewayEnv(t *testing.T) {
	t.Helper()
	keys := []string{
		"JWT_SECRET_KEY", "GATEWAY_DATABASE_URL", "GATEWAY_ENV", "SENTRY_ENVIRONMENT",
		"RABBITMQ_URL", "GATEWAY_WS_ALLOWED_ORIGINS",
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
