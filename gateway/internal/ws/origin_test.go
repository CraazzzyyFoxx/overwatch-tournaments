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
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
)

// productionWSAllowedOrigins is config.DefaultWSAllowedOrigins, the exact
// slice config.Load falls back to. Referencing the exported value (rather
// than duplicating the literal) means this test and
// config.TestLoad_WSAllowedOriginsDefault can't drift apart.
var productionWSAllowedOrigins = config.DefaultWSAllowedOrigins

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

// TestWS_OriginAllowlist_EmptyRejectsForeignOrigin proves the fail-closed
// behaviour when an operator explicitly clears GATEWAY_WS_ALLOWED_ORIGINS:
// NewHandler must never set AcceptOptions.InsecureSkipVerify. coder/websocket
// always authorizes the request's own Host regardless of OriginPatterns (see
// authenticateOrigin in its accept.go), so an empty allowlist degrades to
// same-origin-only enforcement — a foreign cross-site handshake is rejected,
// while a same-origin handshake (Origin host == request Host) still works.
func TestWS_OriginAllowlist_EmptyRejectsForeignOrigin(t *testing.T) {
	h := NewHandler(NewHub(), auth.New(wsSecret), allowAuthorizer{allow: true}, fakeReplayer{},
		30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), nil, nil)
	mux := http.NewServeMux()
	mux.Handle("/ws", h)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	if err := dialWithOrigin(t, srv.URL, "https://evil.example.com"); err == nil {
		t.Fatal("expected empty allow-list to reject a foreign cross-origin handshake, but it was accepted")
	}

	// Same-origin (Origin host == request Host) must still work even with an
	// empty allowlist: coder/websocket authorizes the request's own Host
	// unconditionally. Only the host matters for that check, so reusing
	// srv.URL (http scheme) as the Origin against the ws:// dial target is
	// sufficient.
	if err := dialWithOrigin(t, srv.URL, srv.URL); err != nil {
		t.Fatalf("expected same-origin handshake to be accepted with empty allow-list, got: %v", err)
	}
}
