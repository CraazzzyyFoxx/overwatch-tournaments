package ws

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/ratelimit"
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
		30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), productionWSAllowedOrigins, nil, nil, nil)
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
		30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), nil, nil, nil, nil)
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
				30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), productionWSAllowedOrigins, tt.resolver, nil, nil)
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
		30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), productionWSAllowedOrigins, resolver, nil, nil)
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

// newAcceptTestHandler builds a Handler wired exactly like production
// (static allowlist + a custom-domain resolver + an optional rate limiter),
// for tests that call acceptOptionsFor directly rather than dialing a real
// server — this lets tests assert resolver.calls precisely without the
// overhead/timing sensitivity of a full WS handshake.
func newAcceptTestHandler(resolver CustomDomainResolver, limiter *ratelimit.Limiter) *Handler {
	return NewHandler(NewHub(), auth.New(wsSecret), allowAuthorizer{allow: true}, fakeReplayer{},
		30*time.Second, slog.New(slog.NewTextHandler(io.Discard, nil)), productionWSAllowedOrigins, resolver, limiter, nil)
}

// newUpgradeRequest builds a GET /ws request carrying the Connection/Upgrade
// header pair a genuine WebSocket handshake requires (see
// isWebSocketUpgrade), plus the given Origin header (skipped if empty).
func newUpgradeRequest(origin string) *http.Request {
	r := httptest.NewRequest(http.MethodGet, "/ws", nil)
	r.Header.Set("Connection", "Upgrade")
	r.Header.Set("Upgrade", "websocket")
	if origin != "" {
		r.Header.Set("Origin", origin)
	}
	return r
}

// TestAcceptOptionsFor_NonUpgradeRequestSkipsLookup is the direct regression
// test for the trivial bare-GET probe this review closed: previously,
// acceptOptionsFor ran the custom-domain DB lookup for ANY request carrying
// an Origin header, with no check at all that the request was an actual
// WebSocket handshake. /ws has neither auth nor a rate limiter in front of
// it, so that made a single unauthenticated `GET /ws` (no Upgrade headers,
// just a hostile Origin) enough to trigger one Postgres query + one cache
// write. A bare GET must now cost 0 resolver calls.
func TestAcceptOptionsFor_NonUpgradeRequestSkipsLookup(t *testing.T) {
	resolver := &stubCustomDomainResolver{verified: true}
	h := newAcceptTestHandler(resolver, nil)

	r := httptest.NewRequest(http.MethodGet, "/ws", nil) // no Connection/Upgrade headers at all
	r.Header.Set("Origin", "https://attacker.example.com")

	if opts := h.acceptOptionsFor(r); opts != h.accept {
		t.Fatal("a non-upgrade request must fall through to the static accept options unchanged")
	}
	if resolver.calls != 0 {
		t.Fatalf("expected 0 resolver calls for a non-upgrade request, got %d", resolver.calls)
	}
}

// TestAcceptOptionsFor_MalformedOriginSkipsLookup proves a malformed or
// hostless Origin never reaches the resolver, even on a genuine WS-upgrade
// request — websocket.Accept re-parses the same header and rejects it
// identically, so there is nothing to gain from querying first.
func TestAcceptOptionsFor_MalformedOriginSkipsLookup(t *testing.T) {
	resolver := &stubCustomDomainResolver{verified: true}
	h := newAcceptTestHandler(resolver, nil)

	origins := []string{
		"not-a-url",  // no scheme/authority -> u.Host == ""
		"http://%zz", // invalid percent-encoding -> url.Parse returns an error
	}
	for _, origin := range origins {
		if opts := h.acceptOptionsFor(newUpgradeRequest(origin)); opts != h.accept {
			t.Errorf("origin %q: expected fallthrough to the static accept options", origin)
		}
	}
	if resolver.calls != 0 {
		t.Fatalf("expected 0 resolver calls for malformed origins, got %d", resolver.calls)
	}
}

// TestAcceptOptionsFor_OversizedOriginSkipsLookup proves an Origin host
// longer than a DNS name can ever be (maxOriginHostLen) is rejected before
// it is ever used as a query parameter or cache key — no verified
// custom_domain row could match it regardless.
func TestAcceptOptionsFor_OversizedOriginSkipsLookup(t *testing.T) {
	resolver := &stubCustomDomainResolver{verified: true}
	h := newAcceptTestHandler(resolver, nil)

	oversizedHost := strings.Repeat("a", maxOriginHostLen+1) + ".example.com"
	r := newUpgradeRequest("https://" + oversizedHost)

	if opts := h.acceptOptionsFor(r); opts != h.accept {
		t.Fatal("an oversized Origin host must fall through to the static accept options")
	}
	if resolver.calls != 0 {
		t.Fatalf("expected 0 resolver calls for an oversized origin host, got %d", resolver.calls)
	}
}

// TestAcceptOptionsFor_SameHostSkipsLookup proves the common real case — a
// white-label custom domain's page talking back to that same host — never
// touches the DB: coder/websocket's own authenticateOrigin authorizes the
// request's own Host unconditionally (strings.EqualFold(r.Host, u.Host),
// before it even looks at OriginPatterns), so acceptOptionsFor short-circuits
// identically before querying. The resolver here is rigged to blow up if
// called at all, proving the short-circuit — not a lucky "unverified"
// answer — is what causes the fallthrough.
func TestAcceptOptionsFor_SameHostSkipsLookup(t *testing.T) {
	resolver := &stubCustomDomainResolver{verified: false, err: errors.New("must not be called for a same-host origin")}
	h := newAcceptTestHandler(resolver, nil)

	r := newUpgradeRequest("https://anakq.gg")
	r.Host = "anakq.gg" // Origin host == request Host

	if opts := h.acceptOptionsFor(r); opts != h.accept {
		t.Fatal("a same-host origin must fall through to the static accept options")
	}
	if resolver.calls != 0 {
		t.Fatalf("expected 0 resolver calls for a same-host origin, got %d", resolver.calls)
	}
}

// TestAcceptOptionsFor_RateLimitBoundsDistinctHostFlood is the direct
// regression test for the availability finding this review closed: a flood
// of distinct, non-static, non-same-host Origins from one client IP must not
// drive an unbounded number of DB lookups. With the limiter capped at 2
// requests, 5 distinct hosts must yield at most 2 resolver calls — the rest
// fall through to the static (rejecting) accept options instead of querying.
func TestAcceptOptionsFor_RateLimitBoundsDistinctHostFlood(t *testing.T) {
	resolver := &stubCustomDomainResolver{verified: true}
	limiter := ratelimit.New(2, time.Minute)
	h := newAcceptTestHandler(resolver, limiter)

	const distinctHosts = 5
	var accepted int
	for i := 0; i < distinctHosts; i++ {
		origin := fmt.Sprintf("https://tenant-%d.example.com", i)
		// httptest.NewRequest always sets the same RemoteAddr, so every one
		// of these is seen as the same client IP by the limiter.
		if opts := h.acceptOptionsFor(newUpgradeRequest(origin)); opts != h.accept {
			accepted++
		}
	}

	if resolver.calls != 2 {
		t.Fatalf("expected the rate limiter to cap resolver calls at 2 despite %d distinct hosts, got %d", distinctHosts, resolver.calls)
	}
	if accepted != 2 {
		t.Fatalf("expected exactly 2 of %d distinct hosts to be dynamically accepted (the rest rate-limited), got %d", distinctHosts, accepted)
	}
}

// TestAcceptOptionsFor_RateLimitDoesNotAffectStaticOrSameHost proves the
// limiter only gates the dynamic custom-domain DB lookup, never a
// same-host or already-statically-allowed connection: with the limiter
// exhausted (limit 0, i.e. disabled-by-config would actually pass-through,
// so use limit 1 and burn it first), a same-host request must still be
// accepted without even consulting the limiter.
func TestAcceptOptionsFor_RateLimitDoesNotAffectStaticOrSameHost(t *testing.T) {
	resolver := &stubCustomDomainResolver{verified: true}
	limiter := ratelimit.New(1, time.Minute)
	h := newAcceptTestHandler(resolver, limiter)

	// Burn the limiter's single token on a distinct dynamic lookup.
	burn := newUpgradeRequest("https://tenant-0.example.com")
	if opts := h.acceptOptionsFor(burn); opts == h.accept {
		t.Fatal("the first dynamic lookup should have been allowed and accepted")
	}
	if resolver.calls != 1 {
		t.Fatalf("expected exactly 1 resolver call after burning the limiter, got %d", resolver.calls)
	}

	// A static-allowlist origin must still be accepted even though the
	// limiter is now exhausted: it never reaches the limiter check at all.
	static := newUpgradeRequest("https://owt.craazzzyyfoxx.me")
	if opts := h.acceptOptionsFor(static); opts != h.accept {
		t.Fatal("a static-allowlist origin must be handled by h.accept directly")
	}

	// A same-host origin must also still be accepted (via h.accept, which
	// coder/websocket authorizes unconditionally for the request's own
	// Host) even with the limiter exhausted: it too never reaches the
	// limiter check.
	sameHost := newUpgradeRequest("https://white-label.example.com")
	sameHost.Host = "white-label.example.com"
	if opts := h.acceptOptionsFor(sameHost); opts != h.accept {
		t.Fatal("a same-host origin must fall through to h.accept without consulting the limiter")
	}

	// The resolver must not have been called again by either of the above.
	if resolver.calls != 1 {
		t.Fatalf("expected resolver calls to stay at 1 (static/same-host never touch the resolver), got %d", resolver.calls)
	}
}
