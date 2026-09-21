package ws

import (
	"context"
	"encoding/json"
	"log/slog"
	"strconv"
	"strings"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/protocol"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/safego"
)

// revokeTimeout bounds one re-authorization pass. It is generous next to a
// handful of cached ACL lookups and exists only so a wedged database cannot
// leave the goroutine (and the connection snapshot it holds) alive forever.
const revokeTimeout = 10 * time.Second

// visibilityChangedEvent is the only event this file reacts to: the chat
// service publishes it when an organizer flips a room's spectators_can_read.
const visibilityChangedEvent = "chat.visibility_changed"

// RoomSettingsInvalidator drops a cached chat-room setting. Implemented by
// workspace.Store; the revoker needs it because the ACL answer it is about to
// re-compute is exactly the value this event says has just changed.
type RoomSettingsInvalidator interface {
	InvalidateRoomSpectatorRead(roomKind string, refID int64)
}

// TopicRevoker re-authorizes a chat room's live subscribers when the organizer
// changes who may read it.
//
// The topic ACL is evaluated at SUBSCRIBE time only, so closing a chat does not
// by itself stop a spectator who is already subscribed from receiving
// everything said afterwards — which is precisely the case the toggle exists
// for. A cooperative client-side unsubscribe would make the setting advisory,
// so the revocation happens here, on the server, off the same realtime frame
// every other subscriber receives.
//
// It implements events.Broadcaster and is registered in the existing
// events.Fanout alongside the hub and the response cache.
type TopicRevoker struct {
	hub   *Hub
	authz Authorizer
	rooms RoomSettingsInvalidator
	log   *slog.Logger
}

// NewTopicRevoker returns a revoker over hub, deciding with authz and
// invalidating rooms' cached settings before it asks.
func NewTopicRevoker(hub *Hub, authz Authorizer, rooms RoomSettingsInvalidator, log *slog.Logger) *TopicRevoker {
	if log == nil {
		log = slog.Default()
	}
	return &TopicRevoker{hub: hub, authz: authz, rooms: rooms, log: log}
}

// Broadcast implements events.Broadcaster. It is called for EVERY realtime
// frame, so it does the cheapest possible rejection first (a narrow JSON probe
// for the event type, like protocol.EventFrameTopic) and never runs an ACL
// query on the fan-out path: the re-authorization runs in its own goroutine.
func (t *TopicRevoker) Broadcast(topic string, payload []byte) {
	if !isVisibilityChanged(payload) {
		return
	}
	roomKind, refID, ok := chatRoomOf(topic)
	if !ok {
		return
	}
	safego.Go(func() { t.reauthorize(topic, roomKind, refID) })
}

func (t *TopicRevoker) reauthorize(topic, roomKind string, refID int64) {
	t.rooms.InvalidateRoomSpectatorRead(roomKind, refID)

	subs := t.hub.SubscribersOf(topic)
	if len(subs) == 0 {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), revokeTimeout)
	defer cancel()

	topicPtr := &topic
	for _, c := range subs {
		// Fail closed: a lookup error means we cannot show this connection is
		// still entitled, and the event we are reacting to is a deliberate
		// "stop showing this to people" — so the subscription goes. The client
		// can resubscribe once the lookup works again, and the subscribe path
		// applies the same rule.
		allowed, err := t.authz.Allow(ctx, c.user, topic)
		if err != nil {
			t.log.Warn("chat visibility re-authorization failed", "topic", topic, "err", err)
		}
		if allowed && err == nil {
			continue
		}
		c.unsubscribe(topic)
		_ = c.send(protocol.ErrorFrame("forbidden", "You are no longer allowed to read this chat", topicPtr))
	}
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
