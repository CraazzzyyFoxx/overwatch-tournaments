package config

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"net/netip"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"
)

// testPublicKey is a well-formed JWT_PUBLIC_KEY: 32 bytes, base64url, no padding.
var testPublicKey = base64.RawURLEncoding.EncodeToString(make([]byte, ed25519.PublicKeySize))

// clearGatewayEnv removes every env var Load reads so tests start from a
// clean slate and don't inherit values from the shell running `go test`.
func clearGatewayEnv(t *testing.T) {
	t.Helper()
	keys := []string{
		"JWT_PUBLIC_KEY", "GATEWAY_DATABASE_URL", "GATEWAY_ENV", "SENTRY_ENVIRONMENT",
		"RABBITMQ_URL", "GATEWAY_WS_ALLOWED_ORIGINS",
		"GATEWAY_WS_CUSTOM_DOMAIN_RATE_LIMIT", "GATEWAY_WS_CUSTOM_DOMAIN_RATE_WINDOW",
		"GATEWAY_DOCS_ENABLED", "GATEWAY_DB_MAX_CONNS", "OTEL_TRACES_SAMPLER_ARG",
		"GATEWAY_UPLOAD_MEMORY_BUDGET_MB", "GATEWAY_TRUSTED_PROXIES",
		"GATEWAY_ANON_RATE_LIMIT", "GATEWAY_API_KEY_RATE_LIMIT", "GATEWAY_WRITE_TIMEOUT",
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

// The gateway verifies identity-svc's EdDSA tokens with the public key alone:
// required, and exactly 32 base64url bytes (padding tolerated). The old shared
// HS256 secret is neither needed nor enough.
func TestLoad_JWTPublicKey(t *testing.T) {
	key := make([]byte, ed25519.PublicKeySize)
	key[0] = 0xfb // encodes to URL-alphabet characters ("-", "_")
	for _, tc := range []struct {
		name, value string
		ok          bool
	}{
		{"unpadded base64url", base64.RawURLEncoding.EncodeToString(key), true},
		{"padded base64url", base64.URLEncoding.EncodeToString(key), true},
		{"missing", "", false},
		{"standard alphabet", base64.RawStdEncoding.EncodeToString(key), false},
		{"wrong length", base64.RawURLEncoding.EncodeToString(key[:31]), false},
		{"a secret, not a key", "12345678901234567890123456789012", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			clearGatewayEnv(t)
			t.Setenv("JWT_SECRET_KEY", "12345678901234567890123456789012")
			t.Setenv("JWT_PUBLIC_KEY", tc.value)
			cfg, err := Load()
			if !tc.ok {
				if err == nil || !strings.Contains(err.Error(), "JWT_PUBLIC_KEY") {
					t.Fatalf("want an error naming JWT_PUBLIC_KEY, got cfg=%v err=%v", cfg, err)
				}
				return
			}
			if err != nil || !bytes.Equal(cfg.JWTPublicKey, key) {
				t.Fatalf("want the decoded key, got %x err=%v", cfg.JWTPublicKey, err)
			}
		})
	}
}

func TestLoad_WSAllowedOriginsDefault(t *testing.T) {
	clearGatewayEnv(t)
	os.Setenv("JWT_PUBLIC_KEY", testPublicKey)

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
	os.Setenv("JWT_PUBLIC_KEY", testPublicKey)
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
	os.Setenv("JWT_PUBLIC_KEY", testPublicKey)

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
	os.Setenv("JWT_PUBLIC_KEY", testPublicKey)
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

// A set-but-malformed value used to be swapped for the default without a word:
// GATEWAY_DOCS_ENABLED=fales kept the docs on, a typo'd limit silently changed
// capacity. Load must refuse and name every offending variable.
func TestLoad_MalformedValuesFailNamingEachVariable(t *testing.T) {
	clearGatewayEnv(t)
	t.Setenv("JWT_PUBLIC_KEY", testPublicKey)
	bad := map[string]string{
		"GATEWAY_DOCS_ENABLED":            "fales",
		"GATEWAY_DB_MAX_CONNS":            "16x",
		"OTEL_TRACES_SAMPLER_ARG":         "2",
		"GATEWAY_UPLOAD_MEMORY_BUDGET_MB": "-1",
		"GATEWAY_TRUSTED_PROXIES":         "10.0.0.0/8,not-an-ip",
	}
	for k, v := range bad {
		t.Setenv(k, v)
	}

	cfg, err := Load()
	if err == nil {
		t.Fatalf("Load accepted malformed values: %+v", cfg)
	}
	for k := range bad {
		if !strings.Contains(err.Error(), k) {
			t.Errorf("error does not name %s: %v", k, err)
		}
	}
}

// The stricter parser must not take away the documented "0 disables" (and
// "<= 0 disables" for the older limits).
func TestLoad_ZeroAndDocumentedNegativesStillDisable(t *testing.T) {
	clearGatewayEnv(t)
	t.Setenv("JWT_PUBLIC_KEY", testPublicKey)
	t.Setenv("GATEWAY_ANON_RATE_LIMIT", "0")
	t.Setenv("GATEWAY_API_KEY_RATE_LIMIT", "-1")
	t.Setenv("GATEWAY_UPLOAD_MEMORY_BUDGET_MB", "0")
	t.Setenv("GATEWAY_WRITE_TIMEOUT", "0")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.UploadMemoryBudget != 0 || cfg.WriteTimeout != 0 || cfg.APIKeyRateLimit != -1 {
		t.Fatalf("budget=%d write=%v apikey=%d", cfg.UploadMemoryBudget, cfg.WriteTimeout, cfg.APIKeyRateLimit)
	}
}

func TestLoad_TrustedProxies(t *testing.T) {
	clearGatewayEnv(t)
	t.Setenv("JWT_PUBLIC_KEY", testPublicKey)

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	var def []netip.Prefix
	for _, s := range []string{"127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"} {
		def = append(def, netip.MustParsePrefix(s))
	}
	if !reflect.DeepEqual(cfg.TrustedProxies, def) {
		t.Fatalf("default TrustedProxies = %v, want %v", cfg.TrustedProxies, def)
	}

	// A bare IP is that one host; host bits in a CIDR are masked off.
	t.Setenv("GATEWAY_TRUSTED_PROXIES", "10.1.2.3, 2001:db8::/32 ,192.168.1.77/24")
	cfg, err = Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	want := []netip.Prefix{
		netip.MustParsePrefix("10.1.2.3/32"),
		netip.MustParsePrefix("2001:db8::/32"),
		netip.MustParsePrefix("192.168.1.0/24"),
	}
	if !reflect.DeepEqual(cfg.TrustedProxies, want) {
		t.Fatalf("TrustedProxies = %v, want %v", cfg.TrustedProxies, want)
	}
}
