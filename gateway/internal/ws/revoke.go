package ws

import (
	"context"
	"encoding/json"
	"log/slog"
	"strconv"
	"strings"
	"time"

	"github.com/coder/websocket"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/principal"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/protocol"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/safego"
)

// revokeTimeout bounds one re-authorization pass. It is generous next to a
// handful of cached ACL lookups and exists only so a wedged database cannot
// leave the goroutine (and the connection snapshot it holds) alive forever.
const revokeTimeout = 10 * time.Second

// visibilityChangedEvent is the chat event this file reacts to: the chat
// service publishes it when an organizer flips a room's spectators_can_read,
// and at the unchanged value when a room's participants change (a draft's
// replaced captain).
const visibilityChangedEvent = "chat.visibility_changed"

// ACLCache drops cached topic-ACL answers the realtime bus says have changed.
// Implemented by workspace.Store; the revoker needs it because the answer it
// is about to re-compute is exactly the one the frame contradicts, and Reset
// because a bus that lost frames contradicts every answer.
type ACLCache interface {
	InvalidateRoomAccess(roomKind string, refID int64)
	EvictUser(userID int64)
	Reset()
}

// TopicRevoker re-authorizes live subscribers when who may read a topic
// changes: an organizer toggling a chat room's spectator read, or a draft's
// captain being replaced (chat.visibility_changed on that room's topic), or
// identity-svc announcing that a user's sessions, memberships or roles changed
// (realtime:user:{id}:rbac).
//
// The topic ACL is evaluated at SUBSCRIBE time only, so closing a chat or
// removing a member does not by itself stop a connection that is already
// subscribed from receiving everything published afterwards. A cooperative
// client-side unsubscribe would make the revocation advisory, so it happens
// here, on the server, off the realtime frame announcing the change.
//
// It implements events.Broadcaster and events.Resetter and is registered in
// the existing events.Fanout alongside the hub and the response cache — AFTER
// principal.Resolver, whose leg evicts the user's cached verdicts first, so
// the re-validation here reaches identity-svc rather than the old answer.
type TopicRevoker struct {
	hub        *Hub
	authz      Authorizer
	cache      ACLCache
	principals PrincipalFunc
	log        *slog.Logger
}

// NewTopicRevoker returns a revoker over hub, deciding with authz, dropping
// the contradicted cache entries before it asks, and re-judging a user's
// sockets through principals (the handshake's own rules, see Principals).
func NewTopicRevoker(hub *Hub, authz Authorizer, cache ACLCache, principals PrincipalFunc, log *slog.Logger) *TopicRevoker {
	if log == nil {
		log = slog.Default()
	}
	return &TopicRevoker{hub: hub, authz: authz, cache: cache, principals: principals, log: log}
}

// Broadcast implements events.Broadcaster. It is called for EVERY realtime
// frame, so it does the cheapest possible rejection first (a topic parse, then
// a narrow JSON probe for the event type, like protocol.EventFrameTopic) and
// never runs an ACL query on the fan-out path: the re-authorization runs in its
// own goroutine. A user's cached answers are evicted synchronously, before the
// frame reaches the next leg, so no subscribe handled after it sees them.
func (t *TopicRevoker) Broadcast(topic string, payload []byte) {
	if userID, ok := principal.RBACTopicUser(topic); ok {
		t.cache.EvictUser(userID)
		safego.Go(func() { t.reauthorizeUser(userID) })
		return
	}
	if !isVisibilityChanged(payload) {
		return
	}
	roomKind, refID, ok := chatRoomOf(topic)
	if !ok {
		return
	}
	safego.Go(func() { t.reauthorize(topic, roomKind, refID) })
}

// Reset implements events.Resetter: the bus lost frames, so any of them may
// have been the RBAC or visibility change a cached ACL answer predates, and
// every answer goes. Nothing is re-authorized here — the hub's own Reset, a
// later leg of the same fan-out, closes every socket, and the clients'
// resubscribes run the topic ACL against the emptied cache.
func (t *TopicRevoker) Reset() { t.cache.Reset() }

func (t *TopicRevoker) reauthorize(topic, roomKind string, refID int64) {
	t.cache.InvalidateRoomAccess(roomKind, refID)

	subs := t.hub.SubscribersOf(topic)
	if len(subs) == 0 {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), revokeTimeout)
	defer cancel()

	for _, c := range subs {
		t.revokeUnlessAllowed(ctx, c, topic, "You are no longer allowed to read this chat")
	}
}

// reauthorizeUser re-judges each of the user's live connections, then
// re-checks every topic a surviving one holds. Most answers are unchanged and
// come straight from the cache; the ones that hinge on the membership or role
// that just changed are re-read.
func (t *TopicRevoker) reauthorizeUser(userID int64) {
	conns := t.hub.connsOf(userID)
	if len(conns) == 0 {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), revokeTimeout)
	defer cancel()

	for _, c := range conns {
		if !t.revalidate(ctx, c) {
			continue
		}
		for _, topic := range c.subscribedTopics() {
			t.revokeUnlessAllowed(ctx, c, topic, "You are no longer allowed to subscribe to this topic")
		}
	}
}

// revalidate judges c's credential again: identity-svc publishes the user's
// rbac frame after every session revocation too (logout, password change, an
// admin's revoke), and an open socket must not outlive its session. A
// credential no longer valid closes the socket (policy violation); a valid one
// gets its fresh principal, whose superuser bit may have flipped. When
// identity-svc cannot answer, the socket keeps the principal it has — an
// outage must not drop every live socket — and its topics are still re-checked.
func (t *TopicRevoker) revalidate(ctx context.Context, c *Conn) bool {
	fresh, err := t.principals(ctx, c.principal().Token)
	switch {
	case err != nil:
		t.log.Warn("socket re-validation failed; keeping its principal", "err", err)
	case fresh == nil:
		c.closeWith(websocket.StatusPolicyViolation, "credential revoked")
		return false
	default:
		c.user.Store(fresh)
	}
	return true
}

func (t *TopicRevoker) revokeUnlessAllowed(ctx context.Context, c *Conn, topic, message string) {
	// Fail closed: a lookup error means we cannot show this connection is
	// still entitled, and the frame we are reacting to says the entitlement
	// just changed — so the subscription goes. The client can resubscribe once
	// the lookup works again, and the subscribe path applies the same rule.
	allowed, err := t.authz.Allow(ctx, c.principal(), topic)
	if err != nil {
		t.log.Warn("topic re-authorization failed", "topic", topic, "err", err)
	}
	if allowed && err == nil {
		return
	}
	c.unsubscribe(topic)
	revoked := topic // only a revocation pays for the escaping copy
	_ = c.send(protocol.ErrorFrame("forbidden", message, &revoked))
}

// isVisibilityChanged reports whether raw is an event frame carrying the
// visibility event, decoding only that one field.
func isVisibilityChanged(raw []byte) bool {
	var probe struct {
		Event struct {
			EventType string `json:"event_type"`
		} `json:"event"`
	}
	if err := json.Unmarshal(raw, &probe); err != nil {
		return false
	}
	return probe.Event.EventType == visibilityChangedEvent
}

// chatRoomOf splits a chat topic into the room key the settings cache is keyed
// by: "encounter:12:chat" -> ("encounter", 12). Mirrors ChatRoom.topic in
// backend/shared/services/chat/room.py.
func chatRoomOf(topic string) (string, int64, bool) {
	parts := strings.Split(topic, ":")
	if len(parts) != 3 || parts[2] != "chat" {
		return "", 0, false
	}
	refID, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil {
		return "", 0, false
	}
	return parts[0], refID, true
}
