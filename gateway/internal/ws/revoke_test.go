package ws

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/protocol"
)

// perUserAuthorizer allows every subscribe until a user is denied, so one test
// can subscribe both connections and then take the decision away from one of
// them — exactly what an organizer hiding a chat does.
type perUserAuthorizer struct {
	mu     sync.Mutex
	denied map[int64]bool
}

func (a *perUserAuthorizer) Allow(_ context.Context, user *auth.User, _ string) (bool, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if user == nil {
		return true, nil
	}
	return !a.denied[user.ID], nil
}

func (a *perUserAuthorizer) deny(userID int64) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.denied[userID] = true
}

type roomCall struct {
	kind  string
	refID int64
}

type fakeRoomInvalidator struct {
	mu    sync.Mutex
	calls []roomCall
}

func (f *fakeRoomInvalidator) InvalidateRoomSpectatorRead(roomKind string, refID int64) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, roomCall{roomKind, refID})
}

func (f *fakeRoomInvalidator) seen() []roomCall {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]roomCall(nil), f.calls...)
}

// newServerWithHub is newServer with the hub supplied by the caller, so a test
// can inspect and fan out to the same registry the handler uses.
func newServerWithHub(t *testing.T, hub *Hub, authz Authorizer) string {
	t.Helper()
	h := NewHandler(hub, auth.New(wsSecret), authz, fakeReplayer{}, 30*time.Second,
		slog.New(slog.NewTextHandler(io.Discard, nil)), nil, nil, nil, nil, Limits{})
	mux := http.NewServeMux()
	mux.Handle("/ws", h)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv.URL
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func visibilityFrame(topic string, canRead bool) []byte {
	return protocol.EventFrame(topic, protocol.Envelope{
		EventType: "chat.visibility_changed",
		Data:      map[string]any{"spectators_can_read": canRead},
	})
}

// The whole point of the revoker: an organizer closing the chat must drop the
// spectators already subscribed, and must not disturb the participants.
func TestTopicRevoker_DropsSubscribersNowDenied(t *testing.T) {
	const topic = "encounter:1:chat"
	ctx := context.Background()

	hub := NewHub()
	authz := &perUserAuthorizer{denied: map[int64]bool{}}
	url := newServerWithHub(t, hub, authz)

	// 1 stays allowed (a captain), 2 loses access (a spectator).
	captain := dial(t, ctx, url, mintToken(t, "1"))
	writeJSON(t, ctx, captain, map[string]any{"op": "subscribe", "topic": topic})
	if m := readJSON(t, ctx, captain); m["op"] != "subscribed" {
		t.Fatalf("captain expected subscribed, got %v", m)
	}
	spectator := dial(t, ctx, url, mintToken(t, "2"))
	writeJSON(t, ctx, spectator, map[string]any{"op": "subscribe", "topic": topic})
	if m := readJSON(t, ctx, spectator); m["op"] != "subscribed" {
		t.Fatalf("spectator expected subscribed, got %v", m)
	}

	rooms := &fakeRoomInvalidator{}
	revoker := NewTopicRevoker(hub, authz, rooms, discardLogger())

	authz.deny(2)
	revoker.Broadcast(topic, visibilityFrame(topic, false))

	m := readJSON(t, ctx, spectator)
	if m["op"] != "error" || m["code"] != "forbidden" || m["topic"] != topic {
		t.Fatalf("spectator expected a forbidden revocation frame for %s, got %v", topic, m)
	}
	if subs := hub.SubscribersOf(topic); len(subs) != 1 {
		t.Fatalf("expected exactly one surviving subscriber, got %d", len(subs))
	}

	// The survivor is still receiving the room's traffic.
	hub.Broadcast(topic, protocol.EventFrame(topic, protocol.Envelope{EventType: "chat.message"}))
	if m := readJSON(t, ctx, captain); m["op"] != "event" {
		t.Fatalf("captain should still receive room events, got %v", m)
	}

	// The cached setting is dropped before the re-check, or the re-check would
	// be answered from the value the event just contradicted.
	if calls := rooms.seen(); len(calls) != 1 || calls[0] != (roomCall{"encounter", 1}) {
		t.Fatalf("expected one invalidation of (encounter, 1), got %v", calls)
	}
}

// Every realtime frame passes through Broadcast, so anything that is not a
// visibility change must cost nothing: no invalidation, no ACL pass.
func TestTopicRevoker_IgnoresOtherEvents(t *testing.T) {
	hub := NewHub()
	rooms := &fakeRoomInvalidator{}
	revoker := NewTopicRevoker(hub, &perUserAuthorizer{denied: map[int64]bool{}}, rooms, discardLogger())

	revoker.Broadcast("encounter:1:chat", protocol.EventFrame("encounter:1:chat", protocol.Envelope{EventType: "chat.message"}))
	revoker.Broadcast("tournament:1:bracket", visibilityFrame("tournament:1:bracket", false))

	if calls := rooms.seen(); len(calls) != 0 {
		t.Fatalf("expected no invalidation, got %v", calls)
	}
}
