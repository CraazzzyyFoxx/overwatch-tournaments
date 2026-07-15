package ws

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"net/url"
	"path"
	"strings"
	"time"

	"github.com/coder/websocket"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/clientip"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/protocol"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/ratelimit"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/replay"
)

// maxOriginHostLen is the maximum length of a fully-qualified DNS name (RFC
// 1035 §3.1: 255 octets total, i.e. 253 printable characters once the
// trailing root label and one length-prefix byte are accounted for). No
// verified custom_domain row can ever match a host longer than this, so an
// Origin host beyond it is rejected before it is ever passed to the DB or
// used as a cache key — never mind letting an attacker inflate either with
// an arbitrarily long string.
const maxOriginHostLen = 253

// customDomainLookupTimeout bounds the pre-handshake IsVerifiedCustomDomain
// call, mirroring the house convention of wrapping every cross-process
// lookup in its own context.WithTimeout (see
// gateway/internal/identity/handler.go's rpcTimeout and
// gateway/internal/principal/resolver.go's validateTimeout). /ws has no auth
// and no rate limiter of its own in front of it — only customDomainLimiter,
// which bounds request RATE, not how long any single request can hold a
// connection — and the shared DB pool is capped at MaxConns=8 with no
// statement_timeout backstop (gateway/internal/db/db.go). Without a deadline
// here, a slow/hanging Postgres turns this unauthenticated surface into a
// lever to starve the pool against authenticated ACL/replay queries. Shorter
// than the REST rpcTimeout siblings (5s) since this is a single cached
// point-lookup, not an RPC round-trip to another service.
const customDomainLookupTimeout = 2 * time.Second

// Authorizer decides whether a principal may subscribe to a topic.
type Authorizer interface {
	Allow(ctx context.Context, user *auth.User, topic string) (bool, error)
}

// Replayer supplies cursor-based catch-up on subscribe.
type Replayer interface {
	CurrentCursor(ctx context.Context, topic string) (int64, error)
	EventsSince(ctx context.Context, topic string, after *int64, upTo int64) ([]protocol.Envelope, error)
}

// CustomDomainResolver answers whether host is a verified white-label
// workspace custom domain (Phase 2). Implemented by *workspace.Store's
// IsVerifiedCustomDomain. A nil CustomDomainResolver simply disables
// dynamic custom-domain origin matching (ServeHTTP falls back to the static
// allowlist for every request), which keeps Handler's zero-ish value safe
// and lets tests that don't care about custom domains pass nil.
type CustomDomainResolver interface {
	IsVerifiedCustomDomain(ctx context.Context, host string) (bool, error)
}

// Handler serves the WebSocket endpoint: it authenticates the connection,
// registers it with the hub, and runs the per-connection read loop.
type Handler struct {
	hub                 *Hub
	auth                *auth.Authenticator
	authz               Authorizer
	replay              Replayer
	idleTimeout         time.Duration
	log                 *slog.Logger
	accept              *websocket.AcceptOptions
	customDomains       CustomDomainResolver
	customDomainLimiter *ratelimit.Limiter
	recordActive        func(userID int64)
}

// NewHandler wires the WebSocket handler. recordActive may be nil; when set it
// is called with the user ID of each authenticated connection so WS users count
// toward the active-user metrics. allowedOrigins enforces the browser Origin
// against that allowlist (CSWSH protection); InsecureSkipVerify is never set.
//
// config.Load defaults GATEWAY_WS_ALLOWED_ORIGINS to the platform apex plus
// the "*.owt.craazzzyyfoxx.me" wildcard (coder/websocket's OriginPatterns
// supports "*" globs, so this also covers every tenant subdomain), so a
// default deployment always has a non-empty allowlist. If an operator
// explicitly overrides GATEWAY_WS_ALLOWED_ORIGINS to an empty value, we do
// NOT fall back to InsecureSkipVerify: coder/websocket's Accept always
// authorizes the request's own Host regardless of OriginPatterns (see
// authenticateOrigin in its accept.go), so an empty allowlist degrades to
// same-origin-only enforcement rather than "accept any origin". That keeps a
// same-host WS connection (e.g. a tenant subdomain talking to itself)
// working while still rejecting foreign cross-site handshakes.
//
// customDomains resolves white-label workspace custom domains (Phase 2, see
// docs/superpowers/specs/2026-07-06-workspace-multidomain-design.md): an
// Origin whose host is not covered by allowedOrigins is looked up dynamically
// per-request in ServeHTTP (see acceptOptionsFor), and only a VERIFIED custom
// domain is ever added to the accepted patterns — and only for that one
// request, never mutating the shared static allowlist. customDomains may be
// nil, which simply disables that dynamic path (every request then uses the
// static allowlist only); it never causes InsecureSkipVerify to be set.
//
// customDomainLimiter bounds how often the customDomains lookup itself may
// run per client IP (see acceptOptionsFor): /ws has neither auth nor a
// rate limiter in front of it (contrast /api/auth/* in cmd/gateway/main.go),
// so without this an unauthenticated flood of distinct fake Origin headers
// could otherwise drive one DB query + one cache write per unique host,
// unbounded in rate. May be nil (and a disabled *ratelimit.Limiter, i.e. one
// built from a non-positive limit, behaves the same way) to disable the
// throttle — acceptOptionsFor never dereferences a nil limiter directly, it
// only ever calls its nil-safe Allow method.
func NewHandler(hub *Hub, a *auth.Authenticator, authz Authorizer, rep Replayer, idleTimeout time.Duration, log *slog.Logger, allowedOrigins []string, customDomains CustomDomainResolver, customDomainLimiter *ratelimit.Limiter, recordActive func(userID int64)) *Handler {
	if len(allowedOrigins) == 0 {
		log.Warn("GATEWAY_WS_ALLOWED_ORIGINS is empty; WebSocket origin checking is degraded to same-origin-only")
	}
	accept := &websocket.AcceptOptions{
		// Enforce the Origin header against the configured allowlist so a hostile
		// page cannot open an authenticated cross-site WebSocket (CSWSH). Never
		// set InsecureSkipVerify: an empty allowedOrigins still fails closed to
		// same-origin (see the doc comment above), never open.
		OriginPatterns: allowedOrigins,
	}
	return &Handler{
		hub:                 hub,
		auth:                a,
		authz:               authz,
		replay:              rep,
		idleTimeout:         idleTimeout,
		log:                 log,
		recordActive:        recordActive,
		accept:              accept,
		customDomains:       customDomains,
		customDomainLimiter: customDomainLimiter,
	}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	user := h.auth.UserFromRequest(r)
	if user != nil && h.recordActive != nil {
		h.recordActive(user.ID)
	}

	// Per-connection logger carrying the correlation id (this path bypasses the
	// REST httplog middleware, so resolve the id here).
	connLog := h.log.With("correlation_id", httplog.CorrelationID(r))

	c, err := websocket.Accept(w, r, h.acceptOptionsFor(r))
	if err != nil {
		return // Accept already wrote the error response.
	}
	c.SetReadLimit(readLimit)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	conn := newConn(ctx, c, user, connLog)
	h.hub.add(conn)
	defer h.cleanup(conn)

	h.readLoop(ctx, conn)
}

// acceptOptionsFor resolves the *websocket.AcceptOptions to hand to
// websocket.Accept for this one handshake. It returns the shared static
// options (h.accept) unmodified — never mutated — in every case except one:
//
//   - not a genuine WebSocket-upgrade request (missing/wrong Upgrade or
//     Connection headers): websocket.Accept's own verifyClientRequest checks
//     this same pair of headers and rejects anything else regardless, so
//     this changes nothing about the eventual outcome — it only stops a bare
//     `GET /ws` (with an attacker-chosen Origin and no upgrade headers at
//     all) from reaching the DB/cache below. /ws carries no auth and no rate
//     limit in front of it, so this is the FIRST check, before anything else
//     touches the Origin header at all.
//   - no Origin header: same-origin / non-browser client. websocket.Accept
//     authorizes the request's own Host regardless of OriginPatterns, so the
//     static options are enough.
//   - a malformed Origin (fails to parse, or has no host): websocket.Accept
//     parses the same header itself and will reject it identically.
//   - an Origin whose host already matches one of the static patterns
//     (apex/*.owt): no need to touch the database for a host we already
//     allow unconditionally.
//   - customDomains is nil: the dynamic path is disabled.
//   - an Origin host equal to the request's own Host (a white-label domain
//     talking to itself — the common real case): coder/websocket's
//     authenticateOrigin always authorizes the request's own Host before it
//     even consults OriginPatterns, so this needs no DB lookup either.
//   - an Origin host longer than a DNS name can ever be (maxOriginHostLen):
//     no verified custom_domain row can match it, so it's rejected before
//     being used as a query parameter or cache key.
//   - the pre-handshake rate limit for this client IP is exceeded: falls
//     through to the static options (which reject this non-static Origin)
//     rather than performing the lookup, bounding worst-case DB/cache-write
//     load from a flood of distinct fake Origins.
//   - the custom-domain lookup errors: fail-closed. A transient DB failure
//     must never be treated as "allowed" — it falls through to the static
//     options, which will then reject this non-static Origin.
//   - the host is not a verified custom domain: same fall-through/reject.
//
// Only when the lookup succeeds and reports a VERIFIED custom domain do we
// return a fresh *websocket.AcceptOptions carrying the static patterns plus
// that exact origin host, scoped to this single request. InsecureSkipVerify
// is never set on either path.
func (h *Handler) acceptOptionsFor(r *http.Request) *websocket.AcceptOptions {
	// Gate everything below on this actually being a WS-upgrade request. See
	// the bullet above: this is purely a cost-avoidance short-circuit, not a
	// new security boundary — websocket.Accept enforces the real check.
	if !isWebSocketUpgrade(r) {
		return h.accept
	}

	origin := r.Header.Get("Origin")
	if origin == "" {
		return h.accept
	}
	if h.customDomains == nil {
		return h.accept
	}

	u, err := url.Parse(origin)
	if err != nil || u.Host == "" {
		// Malformed/hostless Origin: websocket.Accept re-parses the header
		// itself and rejects it the same way, so just defer to the static path.
		return h.accept
	}

	// A trailing dot denotes an absolute FQDN (RFC 1035 §3.1) and is otherwise
	// the same host as the dot-less form; Python's normalize_custom_domain
	// (backend/shared/tenancy/hostnames.py) strips it before comparing against
	// or storing a custom_domain. Normalize it here, once, immediately after
	// parsing and BEFORE every check below (static-pattern match, same-host
	// short-circuit, length bound, DB lookup, and the appended OriginPatterns
	// entry) — otherwise a trailing-dot origin could pass one check under the
	// dotted form and fail another under the dot-less one. u.Host is updated
	// in place (preserving any port) so every subsequent read of it agrees.
	if host := u.Hostname(); strings.HasSuffix(host, ".") {
		trimmed := strings.TrimSuffix(host, ".")
		if port := u.Port(); port != "" {
			u.Host = trimmed + ":" + port
		} else {
			u.Host = trimmed
		}
	}

	if matchesAnyOriginPattern(u, h.accept.OriginPatterns) {
		return h.accept // already covered by the static allowlist.
	}

	// Same-host short-circuit, mirroring coder/websocket's own
	// authenticateOrigin (which checks strings.EqualFold(r.Host, u.Host)
	// before ever consulting OriginPatterns): a custom domain whose Origin
	// is its own Host needs no DB round-trip — Accept will authorize it
	// unconditionally either way.
	if strings.EqualFold(r.Host, u.Host) {
		return h.accept
	}

	// hostname is the normalized (lowercase, no port) form used for BOTH the
	// length bound and the DB/cache key: the custom_domain column, like DNS
	// itself, never carries a port, so a port on the Origin is irrelevant to
	// "is this host verified".
	hostname := strings.ToLower(u.Hostname())
	if hostname == "" || len(hostname) > maxOriginHostLen {
		// Oversized (or, degenerately, empty-after-stripping-port) host: no
		// verified custom_domain row can ever match, so never pass this to
		// the DB or use it as a cache key.
		return h.accept
	}

	// Rate-limit the lookup itself, keyed by client IP, before running it.
	// Exceeding the limit only skips the dynamic check for THIS request
	// (falling through to the static allowlist, which rejects it); it never
	// refuses a request outright, so a legitimate reconnect burst against an
	// already-allowed static origin or same-host connection (both handled
	// above, before this point) is never affected.
	if !h.customDomainLimiter.Allow(clientip.From(r)) {
		return h.accept
	}

	// Bound the lookup itself: this is an unauthenticated pre-handshake DB
	// call against a pool with no statement_timeout backstop (see
	// customDomainLookupTimeout's doc comment). A timeout surfaces as ctx's
	// DeadlineExceeded error from IsVerifiedCustomDomain, which the fail-closed
	// handling right below treats exactly like any other lookup error.
	lookupCtx, cancel := context.WithTimeout(r.Context(), customDomainLookupTimeout)
	verified, err := h.customDomains.IsVerifiedCustomDomain(lookupCtx, hostname)
	cancel()
	if err != nil {
		h.log.Error("verified custom-domain lookup failed; rejecting WS origin", "origin", origin, "err", err)
		return h.accept // fail-closed: never allow on a lookup error (including a timeout).
	}
	if !verified {
		return h.accept // not a verified custom domain: let the static Accept reject it.
	}

	// Augment a *copy* of the static patterns with this exact, now-verified
	// origin host. h.accept itself is never mutated, and no wildcard/skip is
	// introduced — only the literal host that was just verified.
	//
	// The scheme is pinned to https://, matching how the static defaults are
	// written (config.defaultWSAllowedOrigins: "https://owt.craazzzyyfoxx.me,
	// https://*.owt.craazzzyyfoxx.me") — an http:// Origin for this same host
	// must NOT be accepted just because the https:// form was verified.
	//
	// Port handling, deliberately: coder/websocket's own authenticateOrigin
	// matches a scheme-carrying pattern against "u.Scheme://u.Host" (i.e. WITH
	// any port), so the appended pattern must carry the same port the actual
	// Origin did for Accept's own matching to succeed — using hostname (no
	// port) here would silently reject a verified domain whose Origin happened
	// to include an explicit port. Only the letter case is normalized
	// (lowercase), to stay consistent with hostname and with
	// matchesAnyOriginPattern above; case doesn't otherwise matter since
	// coder/websocket's own match() lowercases both sides before comparing.
	patterns := make([]string, 0, len(h.accept.OriginPatterns)+1)
	patterns = append(patterns, h.accept.OriginPatterns...)
	patterns = append(patterns, "https://"+strings.ToLower(u.Host))
	return &websocket.AcceptOptions{OriginPatterns: patterns}
}

// isWebSocketUpgrade reports whether r carries the Connection/Upgrade header
// pair a genuine WebSocket handshake requires. It mirrors (loosely — it does
// not need to be byte-for-byte identical) coder/websocket's own
// verifyClientRequest (see its accept.go), which is the actual authority on
// "is this a WS request" and will reject anything failing that same pair of
// checks no matter what this function returns. This exists solely so
// acceptOptionsFor can skip its DB/cache work for a request that was always
// going to be rejected — such as a bare `GET /ws` carrying a hostile Origin
// but no upgrade headers at all.
func isWebSocketUpgrade(r *http.Request) bool {
	return headerContainsToken(r.Header, "Connection", "upgrade") &&
		headerContainsToken(r.Header, "Upgrade", "websocket")
}

// headerContainsToken reports whether any comma-separated token across all
// occurrences of header key case-insensitively equals token.
func headerContainsToken(h http.Header, key, token string) bool {
	for _, v := range h.Values(key) {
		for _, t := range strings.Split(v, ",") {
			if strings.EqualFold(strings.TrimSpace(t), token) {
				return true
			}
		}
	}
	return false
}

// matchesAnyOriginPattern reports whether the parsed origin already satisfies
// one of patterns, mirroring coder/websocket's own matching (see match and
// authenticateOrigin in its accept.go): each pattern is matched case
// insensitively with path.Match against either the origin host, or
// "scheme://host" when the pattern itself carries a scheme. This is used only
// to decide whether the custom-domain DB lookup can be skipped; the actual
// authorization decision is still made by websocket.Accept itself, so a
// false negative here only costs an extra (cached) lookup, never a security
// regression.
func matchesAnyOriginPattern(u *url.URL, patterns []string) bool {
	for _, p := range patterns {
		target := u.Host
		if strings.Contains(p, "://") {
			target = u.Scheme + "://" + u.Host
		}
		if matched, err := path.Match(strings.ToLower(p), strings.ToLower(target)); err == nil && matched {
			return true
		}
	}
	return false
}

func (h *Handler) readLoop(ctx context.Context, conn *Conn) {
	for {
		readCtx, cancel := context.WithTimeout(ctx, h.idleTimeout)
		_, data, err := conn.ws.Read(readCtx)
		cancel()
		if err != nil {
			return // client closed, idle timeout, or read error
		}

		if len(data) > MaxClientFrameBytes {
			_ = conn.send(protocol.ErrorFrame("frame_too_large", "Frame exceeds the maximum allowed size", nil))
			continue
		}

		op, perr := protocol.ParseClientOp(data)
		if perr != nil {
			_ = conn.send(protocol.ErrorFrame(perr.Code, perr.Message, perr.Topic))
			continue
		}

		switch op.Op {
		case "ping":
			_ = conn.send(protocol.PongFrame())
		case "unsubscribe":
			h.handleUnsubscribe(conn, op.Topic)
		case "publish":
			h.handlePublish(conn, op)
		case "subscribe":
			h.handleSubscribe(ctx, conn, op)
		}
	}
}

func (h *Handler) handleSubscribe(ctx context.Context, conn *Conn, op *protocol.ClientOp) {
	topicPtr := &op.Topic

	// Ignore a duplicate subscribe to an already-subscribed topic: it would
	// otherwise re-run the ACL/replay queries and re-deliver replay events.
	if conn.hasTopic(op.Topic) {
		return
	}

	allowed, err := h.authz.Allow(ctx, conn.user, op.Topic)
	if err != nil {
		conn.log.Error("acl check failed", "topic", op.Topic, "err", err)
		_ = conn.send(protocol.ErrorFrame("internal_error", "Could not authorize the subscription", topicPtr))
		return
	}
	if !allowed {
		_ = conn.send(protocol.ErrorFrame("forbidden", "You are not allowed to subscribe to this topic", topicPtr))
		return
	}

	cursor, err := h.replay.CurrentCursor(ctx, op.Topic)
	if err != nil {
		conn.log.Error("cursor lookup failed", "topic", op.Topic, "err", err)
		_ = conn.send(protocol.ErrorFrame("internal_error", "Could not load the subscription", topicPtr))
		return
	}

	events, err := h.replay.EventsSince(ctx, op.Topic, op.AfterEventID, cursor)
	if errors.Is(err, replay.ErrGapTooLarge) {
		_ = conn.send(protocol.ErrorFrame(
			"replay_gap_too_large",
			"Too many missed events; refetch a fresh snapshot before subscribing again",
			topicPtr,
		))
		return
	}
	if err != nil {
		conn.log.Error("replay failed", "topic", op.Topic, "err", err)
		_ = conn.send(protocol.ErrorFrame("internal_error", "Could not load the subscription", topicPtr))
		return
	}

	conn.subscribe(op.Topic)
	for _, ev := range events {
		_ = conn.send(protocol.EventFrame(op.Topic, ev))
	}
	_ = conn.send(protocol.SubscribedFrame(op.Topic, cursor))

	if IsPresenceTopic(op.Topic) {
		h.broadcastPresence(op.Topic)
	}
}

func (h *Handler) handleUnsubscribe(conn *Conn, topic string) {
	conn.unsubscribe(topic)
	if IsPresenceTopic(topic) {
		h.broadcastPresence(topic)
	}
}

// handlePublish fans a client-originated ephemeral frame to a topic's other
// subscribers. Security boundary: authenticated users only, must already be
// subscribed, event type must be on the allowlist, actor is stamped server-side,
// event_id stays 0 (ephemeral), and the sender is excluded from fan-out.
func (h *Handler) handlePublish(conn *Conn, op *protocol.ClientOp) {
	topicPtr := &op.Topic

	if conn.user == nil {
		_ = conn.send(protocol.ErrorFrame("forbidden", "Authentication required to publish", topicPtr))
		return
	}
	if !conn.hasTopic(op.Topic) {
		_ = conn.send(protocol.ErrorFrame("not_subscribed", "Subscribe to the topic before publishing", topicPtr))
		return
	}
	if op.EventType != BalancerDrag {
		_ = conn.send(protocol.ErrorFrame("forbidden_event", "This event type cannot be published by clients", topicPtr))
		return
	}
	if !conn.allowPublish(time.Now()) {
		return // silently drop abusive bursts
	}

	actor := conn.user.ID
	env := protocol.Envelope{
		EventID:       0,
		EventType:     op.EventType,
		SchemaVersion: 1,
		OccurredAt:    time.Now().UTC(),
		ActorUserID:   &actor,
		Data:          op.Data,
	}
	h.hub.Route(op.Topic, protocol.EventFrame(op.Topic, env), conn)
}

func (h *Handler) broadcastPresence(topic string) {
	ids, anonymousViewerCount := h.hub.presenceStats(topic)
	env := protocol.Envelope{
		EventID:       0,
		EventType:     presenceEventType(topic),
		SchemaVersion: 1,
		OccurredAt:    time.Now().UTC(),
		ActorUserID:   nil,
		Data: map[string]any{
			"user_ids":              ids,
			"anonymous_viewer_count": anonymousViewerCount,
		},
	}
	h.hub.Route(topic, protocol.EventFrame(topic, env), nil)
}

func (h *Handler) cleanup(conn *Conn) {
	var presenceTopics []string
	for _, t := range conn.subscribedTopics() {
		if IsPresenceTopic(t) {
			presenceTopics = append(presenceTopics, t)
		}
	}
	h.hub.remove(conn)
	conn.close()
	for _, t := range presenceTopics {
		h.broadcastPresence(t)
	}
}
