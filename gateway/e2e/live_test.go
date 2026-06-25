// Package e2e holds opt-in live tests that drive a running gateway container.
// They are skipped unless GATEWAY_E2E_WS is set, e.g.:
//
//	docker compose --profile gateway-go up -d gateway
//	GATEWAY_E2E_WS=ws://localhost:8080/ws go test ./e2e/ -run TestLive -v
package e2e

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/redis/go-redis/v9"
)

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// TestLiveFanout subscribes to a public topic on the running gateway, publishes
// an event on the Redis realtime bus, and asserts the gateway relays it to the
// WebSocket client — the core check that the fan-in path works end to end.
func TestLiveFanout(t *testing.T) {
	wsURL := os.Getenv("GATEWAY_E2E_WS")
	if wsURL == "" {
		t.Skip("set GATEWAY_E2E_WS (e.g. ws://localhost:8080/ws) to run live e2e")
	}
	redisAddr := envOr("GATEWAY_E2E_REDIS", "localhost:6379")
	const topic = "tournament:1:bracket" // public topic: no auth, no membership

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatalf("dial gateway: %v", err)
	}
	defer c.CloseNow()

	mustWrite(t, ctx, c, map[string]any{"op": "subscribe", "topic": topic})

	// Drain until the subscription is acknowledged.
	for {
		m := mustRead(t, ctx, c)
		if m["op"] == "subscribed" {
			break
		}
		if m["op"] == "error" {
			t.Fatalf("subscribe rejected: %v", m)
		}
	}

	rdb := redis.NewClient(&redis.Options{Addr: redisAddr})
	defer rdb.Close()

	frame := `{"op":"event","topic":"tournament:1:bracket","event":{"event_id":0,"event_type":"tournament.updated","schema_version":1,"occurred_at":"2026-06-18T00:00:00Z","actor_user_id":null,"data":{"reason":"e2e"}}}`

	deadline := time.After(10 * time.Second)
	for {
		if err := rdb.Publish(ctx, "realtime:"+topic, frame).Err(); err != nil {
			t.Fatalf("redis publish: %v", err)
		}
		rctx, rcancel := context.WithTimeout(ctx, 400*time.Millisecond)
		_, data, err := c.Read(rctx)
		rcancel()
		if err != nil {
			select {
			case <-deadline:
				t.Fatal("timed out waiting for relayed event")
			default:
				continue // retry publish/read
			}
		}
		var m map[string]any
		if err := json.Unmarshal(data, &m); err != nil {
			t.Fatalf("unmarshal %q: %v", data, err)
		}
		if m["op"] != "event" || m["topic"] != topic {
			continue
		}
		ev := m["event"].(map[string]any)
		if ev["event_type"] == "tournament.updated" && ev["data"].(map[string]any)["reason"] == "e2e" {
			return // success
		}
	}
}

func mustWrite(t *testing.T, ctx context.Context, c *websocket.Conn, v any) {
	t.Helper()
	b, _ := json.Marshal(v)
	if err := c.Write(ctx, websocket.MessageText, b); err != nil {
		t.Fatalf("write: %v", err)
	}
}

func mustRead(t *testing.T, ctx context.Context, c *websocket.Conn) map[string]any {
	t.Helper()
	rctx, cancel := context.WithTimeout(ctx, 3*time.Second)
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
