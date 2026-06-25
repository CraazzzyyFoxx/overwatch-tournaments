package events

import (
	"context"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

type captured struct {
	topic   string
	payload string
}

type fakeBroadcaster struct {
	mu  sync.Mutex
	got []captured
	ch  chan captured
}

func newFakeBroadcaster() *fakeBroadcaster {
	return &fakeBroadcaster{ch: make(chan captured, 16)}
}

func (f *fakeBroadcaster) Broadcast(topic string, payload []byte) {
	c := captured{topic: topic, payload: string(payload)}
	f.mu.Lock()
	f.got = append(f.got, c)
	f.mu.Unlock()
	f.ch <- c
}

func discardLog() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

func TestDispatch(t *testing.T) {
	t.Run("valid channel routes by topic", func(t *testing.T) {
		fb := newFakeBroadcaster()
		s := New(nil, fb, discardLog())
		s.dispatch("realtime:tournament:1:bracket", []byte(`{"op":"event"}`))
		select {
		case c := <-fb.ch:
			if c.topic != "tournament:1:bracket" || c.payload != `{"op":"event"}` {
				t.Fatalf("unexpected broadcast: %+v", c)
			}
		default:
			t.Fatal("expected a broadcast")
		}
	})

	t.Run("channel without prefix is dropped", func(t *testing.T) {
		fb := newFakeBroadcaster()
		s := New(nil, fb, discardLog())
		s.dispatch("other:channel", []byte(`{}`))
		if len(fb.got) != 0 {
			t.Fatalf("expected drop, got %v", fb.got)
		}
	})
}

// TestRun_RelaysFromRedis exercises the full PSUBSCRIBE -> relay path against an
// in-memory Redis.
func TestRun_RelaysFromRedis(t *testing.T) {
	mr, err := miniredis.Run()
	if err != nil {
		t.Fatalf("miniredis: %v", err)
	}
	defer mr.Close()

	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	fb := newFakeBroadcaster()
	sub := New(client, fb, discardLog())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = sub.Run(ctx) }()

	// Re-publish on a tick until the relay observes the frame; this rides out
	// the small window before the PSUBSCRIBE is established.
	frame := `{"op":"event","topic":"tournament:7:balancer","event":{}}`
	deadline := time.After(3 * time.Second)
	for {
		_ = client.Publish(ctx, "realtime:tournament:7:balancer", frame).Err()
		select {
		case c := <-fb.ch:
			if c.topic != "tournament:7:balancer" || c.payload != frame {
				t.Fatalf("unexpected relay: %+v", c)
			}
			return
		case <-time.After(50 * time.Millisecond):
		case <-deadline:
			t.Fatal("timed out waiting for relayed frame")
		}
	}
}
