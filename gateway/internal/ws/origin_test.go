package ws

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/coder/websocket"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
)

// productionWSAllowedOrigins mirrors config.defaultWSAllowedOrigins (gateway/
// internal/config/config.go). It is duplicated here, rather than imported,
// to keep this package free of a config dependency; TestLoad_WSAllowedOriginsDefault
// in internal/config guards the source of truth.
var productionWSAllowedOrigins = []string{
	"https://owt.craazzzyyfoxx.me",
	"https://*.owt.craazzzyyfoxx.me",
}

// dialWithOrigin attempts the WS handshake against srvURL with the given
// Origin header and reports whether the server accepted the connection.
func dialWithOrigin(t *testing.T, srvURL, origin string) error {
	t.Helper()
	u := "ws" + srvURL[len("http"):] + "/ws"
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	header := http.Header{}
	if origin != "" {
		header.Set("Origin", origin)
	}
	c, _, err := websocket.Dial(ctx, u, &websocket.DialOptions{HTTPHeader: header})
	if err == nil {
		c.CloseNow()
	}
	return err
}

// TestWS_OriginAllowlist_ProductionDefault exercises the real coder/websocket
// accept path (not just config parsing) with the same allowlist
// config.Load's default produces, so a regression in either the default
// value or how it's wired into ws.NewHandler's AcceptOptions fails this test.
func TestWS_OriginAllowlist_ProductionDefault(t *testing.T) {
	h := NewHandler(NewHub(), auth.New(wsSecret), allowAuthorizer{allow: true}, fakeReplayer{},
		30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), productionWSAllowedOrigins, nil)
	mux := http.NewServeMux()
	mux.Handle("/ws", h)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	tests := []struct {
		name      string
		origin    string
		wantAllow bool
	}{
		{"no origin header (non-browser client)", "", true},
		{"apex origin", "https://owt.craazzzyyfoxx.me", true},
		{"tenant subdomain matches wildcard", "https://team-a.owt.craazzzyyfoxx.me", true},
		{"another tenant subdomain", "https://another-team.owt.craazzzyyfoxx.me", true},
		{"foreign origin rejected", "https://evil.example.com", false},
		{"lookalike suffix rejected", "https://owt.craazzzyyfoxx.me.evil.com", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := dialWithOrigin(t, srv.URL, tt.origin)
			allowed := err == nil
			if allowed != tt.wantAllow {
				t.Fatalf("origin %q: allowed=%v (err=%v), want allowed=%v", tt.origin, allowed, err, tt.wantAllow)
			}
		})
	}
}

// TestWS_OriginAllowlist_EmptyFallsBackToInsecure documents the one path that
// still reaches AcceptOptions.InsecureSkipVerify: an operator explicitly
// clearing the allowlist. It must never be the default (see
// TestWS_OriginAllowlist_ProductionDefault and
// config.TestLoad_WSAllowedOriginsDefault).
func TestWS_OriginAllowlist_EmptyFallsBackToInsecure(t *testing.T) {
	h := NewHandler(NewHub(), auth.New(wsSecret), allowAuthorizer{allow: true}, fakeReplayer{},
		30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), nil, nil)
	mux := http.NewServeMux()
	mux.Handle("/ws", h)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	if err := dialWithOrigin(t, srv.URL, "https://evil.example.com"); err != nil {
		t.Fatalf("expected InsecureSkipVerify fallback to accept any origin, got: %v", err)
	}
}
