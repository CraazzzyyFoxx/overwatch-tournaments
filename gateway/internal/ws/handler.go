package ws

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/coder/websocket"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/protocol"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/replay"
)

// Authorizer decides whether a principal may subscribe to a topic.
type Authorizer interface {
	Allow(ctx context.Context, user *auth.User, topic string) (bool, error)
}

// Replayer supplies cursor-based catch-up on subscribe.
type Replayer interface {
	CurrentCursor(ctx context.Context, topic string) (int64, error)
	EventsSince(ctx context.Context, topic string, after *int64, upTo int64) ([]protocol.Envelope, error)
}

// Handler serves the WebSocket endpoint: it authenticates the connection,
// registers it with the hub, and runs the per-connection read loop.
type Handler struct {
	hub          *Hub
	auth         *auth.Authenticator
	authz        Authorizer
	replay       Replayer
	idleTimeout  time.Duration
	log          *slog.Logger
	accept       *websocket.AcceptOptions
	recordActive func(userID int64)
}

// NewHandler wires the WebSocket handler. recordActive may be nil; when set it
// is called with the user ID of each authenticated connection so WS users count
// toward the active-user metrics. allowedOrigins, when non-empty, enforces the
// browser Origin against that allowlist (CSWSH protection); when empty the
// previous permissive behaviour is kept (see accept setup below).
//
// config.Load defaults GATEWAY_WS_ALLOWED_ORIGINS to the platform apex plus
// the "*.owt.craazzzyyfoxx.me" wildcard (coder/websocket's OriginPatterns
// supports "*" globs, so this also covers every tenant subdomain), so a
// default deployment always takes the allowlist branch below. The
// InsecureSkipVerify fallback only fires if an operator explicitly overrides
// GATEWAY_WS_ALLOWED_ORIGINS to an empty value — it must never be relied on
// in production.
func NewHandler(hub *Hub, a *auth.Authenticator, authz Authorizer, rep Replayer, idleTimeout time.Duration, log *slog.Logger, allowedOrigins []string, recordActive func(userID int64)) *Handler {
	accept := &websocket.AcceptOptions{}
	if len(allowedOrigins) > 0 {
		// Enforce the Origin header against the configured allowlist so a hostile
		// page cannot open an authenticated cross-site WebSocket (CSWSH).
		accept.OriginPatterns = allowedOrigins
	} else {
		// No allowlist configured: preserve the previous behaviour (the gateway
		// runs behind nginx and is not exposed directly to untrusted browsers).
		// Set GATEWAY_WS_ALLOWED_ORIGINS to the frontend domain(s) to tighten this.
		accept.InsecureSkipVerify = true
	}
	return &Handler{
		hub:          hub,
		auth:         a,
		authz:        authz,
		replay:       rep,
		idleTimeout:  idleTimeout,
		log:          log,
		recordActive: recordActive,
		accept:       accept,
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

	c, err := websocket.Accept(w, r, h.accept)
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
	ids := h.hub.presenceUserIDs(topic)
	env := protocol.Envelope{
		EventID:       0,
		EventType:     BalancerPresence,
		SchemaVersion: 1,
		OccurredAt:    time.Now().UTC(),
		ActorUserID:   nil,
		Data:          map[string]any{"user_ids": ids},
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
