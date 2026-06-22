package ws

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/golang-jwt/jwt/v5"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/protocol"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/replay"
)

const wsSecret = "ws-test-secret"

type allowAuthorizer struct {
	allow bool
	err   error
}

func (a allowAuthorizer) Allow(context.Context, *auth.User, string) (bool, error) {
	return a.allow, a.err
}

type fakeReplayer struct {
	cursor int64
	events []protocol.Envelope
	err    error
}

func (f fakeReplayer) CurrentCursor(context.Context, string) (int64, error) {
	return f.cursor, nil
}

func (f fakeReplayer) EventsSince(context.Context, string, *int64, int64) ([]protocol.Envelope, error) {
	return f.events, f.err
}

func newServer(t *testing.T, authz Authorizer, rep Replayer) string {
	t.Helper()
	h := NewHandler(NewHub(), auth.New(wsSecret), authz, rep, 30*time.Second,
		slog.New(slog.NewTextHandler(io.Discard, nil)), nil)
	mux := http.NewServeMux()
	mux.Handle("/ws", h)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv.URL
}

func mintToken(t *testing.T, sub string) string {
	t.Helper()
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": sub, "type": "access", "exp": time.Now().Add(time.Hour).Unix(),
	})
	s, err := tok.SignedString([]byte(wsSecret))
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func dial(t *testing.T, ctx context.Context, serverURL, token string) *websocket.Conn {
	t.Helper()
	u := "ws" + strings.TrimPrefix(serverURL, "http") + "/ws"
	if token != "" {
		u += "?token=" + token
	}
	c, _, err := websocket.Dial(ctx, u, nil)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	t.Cleanup(func() { c.CloseNow() })
	return c
}

func writeJSON(t *testing.T, ctx context.Context, c *websocket.Conn, v any) {
	t.Helper()
	b, _ := json.Marshal(v)
	if err := c.Write(ctx, websocket.MessageText, b); err != nil {
		t.Fatalf("write: %v", err)
	}
}

func readJSON(t *testing.T, ctx context.Context, c *websocket.Conn) map[string]any {
	t.Helper()
	rctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	_, data, err := c.Read(rctx)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	var m map[string]any
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("unmarshal %q: %v", data, err)
	}
	return m
}

func TestWS_SubscribePublic(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{cursor: 5})
	ctx := context.Background()
	c := dial(t, ctx, url, "")

	writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:bracket"})
	m := readJSON(t, ctx, c)
	if m["op"] != "subscribed" || m["topic"] != "tournament:1:bracket" || m["cursor"] != float64(5) {
		t.Fatalf("unexpected subscribed frame: %v", m)
	}
}

func TestWS_SubscribeForbidden(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: false}, fakeReplayer{})
	ctx := context.Background()
	c := dial(t, ctx, url, "")

	writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:balancer"})
	m := readJSON(t, ctx, c)
	if m["op"] != "error" || m["code"] != "forbidden" {
		t.Fatalf("expected forbidden error, got %v", m)
	}
}

func TestWS_ReplayGap(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{err: replay.ErrGapTooLarge})
	ctx := context.Background()
	c := dial(t, ctx, url, "")

	writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:bracket", "after_event_id": 1})
	m := readJSON(t, ctx, c)
	if m["op"] != "error" || m["code"] != "replay_gap_too_large" {
		t.Fatalf("expected replay_gap_too_large, got %v", m)
	}
}

func TestWS_Ping(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{})
	ctx := context.Background()
	c := dial(t, ctx, url, "")

	writeJSON(t, ctx, c, map[string]any{"op": "ping"})
	if m := readJSON(t, ctx, c); m["op"] != "pong" {
		t.Fatalf("expected pong, got %v", m)
	}
}

func TestWS_PublishGuards(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{})
	ctx := context.Background()

	t.Run("anon cannot publish", func(t *testing.T) {
		c := dial(t, ctx, url, "")
		writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:bracket"})
		readJSON(t, ctx, c) // subscribed
		writeJSON(t, ctx, c, map[string]any{"op": "publish", "topic": "tournament:1:bracket", "event_type": "balancer.drag", "data": map[string]any{}})
		if m := readJSON(t, ctx, c); m["code"] != "forbidden" {
			t.Fatalf("expected forbidden, got %v", m)
		}
	})

	t.Run("not subscribed", func(t *testing.T) {
		c := dial(t, ctx, url, mintToken(t, "1"))
		writeJSON(t, ctx, c, map[string]any{"op": "publish", "topic": "tournament:1:balancer", "event_type": "balancer.drag", "data": map[string]any{}})
		if m := readJSON(t, ctx, c); m["code"] != "not_subscribed" {
			t.Fatalf("expected not_subscribed, got %v", m)
		}
	})

	t.Run("forbidden event type", func(t *testing.T) {
		c := dial(t, ctx, url, mintToken(t, "1"))
		writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:bracket"})
		readJSON(t, ctx, c) // subscribed
		writeJSON(t, ctx, c, map[string]any{"op": "publish", "topic": "tournament:1:bracket", "event_type": "tournament.updated", "data": map[string]any{}})
		if m := readJSON(t, ctx, c); m["code"] != "forbidden_event" {
			t.Fatalf("expected forbidden_event, got %v", m)
		}
	})
}

// TestWS_FanoutAndPresence is the end-to-end check: two authenticated clients
// on a balancer topic, presence reflects both, a published drag reaches the
// other client but not the sender.
func TestWS_FanoutAndPresence(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{cursor: 0})
	ctx := context.Background()
	const topic = "tournament:1:balancer"

	// Client A subscribes; drain its subscribed + presence[1] frames.
	a := dial(t, ctx, url, mintToken(t, "1"))
	writeJSON(t, ctx, a, map[string]any{"op": "subscribe", "topic": topic})
	if m := readJSON(t, ctx, a); m["op"] != "subscribed" {
		t.Fatalf("A expected subscribed, got %v", m)
	}
	if ids := presenceIDs(t, readJSON(t, ctx, a)); !equalInts(ids, []int{1}) {
		t.Fatalf("A expected presence [1], got %v", ids)
	}

	// Client B subscribes; B reads subscribed + presence[1,2].
	b := dial(t, ctx, url, mintToken(t, "2"))
	writeJSON(t, ctx, b, map[string]any{"op": "subscribe", "topic": topic})
	if m := readJSON(t, ctx, b); m["op"] != "subscribed" {
		t.Fatalf("B expected subscribed, got %v", m)
	}
	if ids := presenceIDs(t, readJSON(t, ctx, b)); !equalInts(ids, []int{1, 2}) {
		t.Fatalf("B expected presence [1,2], got %v", ids)
	}
	// A also receives the updated presence[1,2].
	if ids := presenceIDs(t, readJSON(t, ctx, a)); !equalInts(ids, []int{1, 2}) {
		t.Fatalf("A expected presence [1,2], got %v", ids)
	}

	// A publishes a drag; B must receive it, A must not.
	writeJSON(t, ctx, a, map[string]any{
		"op": "publish", "topic": topic, "event_type": "balancer.drag",
		"data": map[string]any{"x": 1},
	})

	m := readJSON(t, ctx, b)
	if m["op"] != "event" {
		t.Fatalf("B expected event, got %v", m)
	}
	ev := m["event"].(map[string]any)
	if ev["event_type"] != "balancer.drag" || ev["actor_user_id"] != float64(1) || ev["event_id"] != float64(0) {
		t.Fatalf("B got unexpected drag envelope: %v", ev)
	}

	// A (the sender) must not receive its own drag.
	rctx, cancel := context.WithTimeout(ctx, 400*time.Millisecond)
	defer cancel()
	if _, _, err := a.Read(rctx); err == nil {
		t.Fatal("sender should not receive its own published frame")
	}
}

func presenceIDs(t *testing.T, m map[string]any) []int {
	t.Helper()
	if m["op"] != "event" {
		t.Fatalf("expected event frame for presence, got %v", m)
	}
	ev := m["event"].(map[string]any)
	if ev["event_type"] != "balancer.presence" {
		t.Fatalf("expected balancer.presence, got %v", ev["event_type"])
	}
	raw := ev["data"].(map[string]any)["user_ids"].([]any)
	ids := make([]int, len(raw))
	for i, v := range raw {
		ids[i] = int(v.(float64))
	}
	return ids
}

func equalInts(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
