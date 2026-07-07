package ws

import (
	"context"
	"errors"
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
		30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), productionWSAllowedOrigins, nil, nil)
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
		30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), nil, nil, nil)
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

// stubCustomDomainResolver is a fake CustomDomainResolver: it answers a fixed
// (verified, err) pair for every host and counts how many times it was
// called, so tests can both drive the accepted/rejected/fail-closed paths and
// assert that the static-origin fast path never touches the resolver at all.
type stubCustomDomainResolver struct {
	verified bool
	err      error
	calls    int
}

func (s *stubCustomDomainResolver) IsVerifiedCustomDomain(context.Context, string) (bool, error) {
	s.calls++
	return s.verified, s.err
}

// TestWS_OriginAllowlist_VerifiedCustomDomain exercises the dynamic
// custom-domain path (Phase 2 white-label): a host that is not covered by the
// static apex/*.owt allowlist is only accepted when the resolver reports it
// as a VERIFIED custom domain. An unverified domain, a resolver error, and a
// plain foreign origin must all be rejected — the same "reject" outcome,
// proving the handler never distinguishes "unverified" from "lookup failed"
// in the client's favor (fail-closed).
func TestWS_OriginAllowlist_VerifiedCustomDomain(t *testing.T) {
	tests := []struct {
		name      string
		resolver  *stubCustomDomainResolver
		origin    string
		wantAllow bool
	}{
		{
			name:      "verified custom domain is accepted",
			resolver:  &stubCustomDomainResolver{verified: true},
			origin:    "https://anakq.gg",
			wantAllow: true,
		},
		{
			name:      "unverified custom domain is rejected",
			resolver:  &stubCustomDomainResolver{verified: false},
			origin:    "https://anakq.gg",
			wantAllow: false,
		},
		{
			name:      "lookup error fails closed, not open",
			resolver:  &stubCustomDomainResolver{verified: true, err: errors.New("db unavailable")},
			origin:    "https://anakq.gg",
			wantAllow: false,
		},
		{
			name:      "foreign origin unrelated to any custom domain is rejected",
			resolver:  &stubCustomDomainResolver{verified: false},
			origin:    "https://evil.example.com",
			wantAllow: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := NewHandler(NewHub(), auth.New(wsSecret), allowAuthorizer{allow: true}, fakeReplayer{},
				30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), productionWSAllowedOrigins, tt.resolver, nil)
			mux := http.NewServeMux()
			mux.Handle("/ws", h)
			srv := httptest.NewServer(mux)
			t.Cleanup(srv.Close)

			err := dialWithOrigin(t, srv.URL, tt.origin)
			allowed := err == nil
			if allowed != tt.wantAllow {
				t.Fatalf("origin %q: allowed=%v (err=%v), want allowed=%v", tt.origin, allowed, err, tt.wantAllow)
			}
			if tt.resolver.calls != 1 {
				t.Fatalf("expected exactly 1 resolver call for a non-static origin, got %d", tt.resolver.calls)
			}
		})
	}
}

// TestWS_OriginAllowlist_StaticOriginSkipsCustomDomainLookup proves the fast
// path (no DB lookup for an origin already covered by the static apex/*.owt
// allowlist): the resolver here is rigged to reject and blow up if called at
// all, so the connections would fail if acceptOptionsFor ever queried it for
// these origins.
func TestWS_OriginAllowlist_StaticOriginSkipsCustomDomainLookup(t *testing.T) {
	resolver := &stubCustomDomainResolver{verified: false, err: errors.New("must not be called for a static origin")}
	h := NewHandler(NewHub(), auth.New(wsSecret), allowAuthorizer{allow: true}, fakeReplayer{},
		30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), productionWSAllowedOrigins, resolver, nil)
	mux := http.NewServeMux()
	mux.Handle("/ws", h)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	origins := []string{
		"https://owt.craazzzyyfoxx.me",
		"https://team-a.owt.craazzzyyfoxx.me",
	}
	for _, origin := range origins {
		if err := dialWithOrigin(t, srv.URL, origin); err != nil {
			t.Fatalf("origin %q: expected static allowlist to accept it, got: %v", origin, err)
		}
	}
	if resolver.calls != 0 {
		t.Fatalf("expected the custom-domain resolver to never be called for a static origin, got %d calls", resolver.calls)
	}
}
