package ws

import (
	"bufio"
	"context"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/coder/websocket"
	"github.com/redis/go-redis/v9"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/events"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/protocol"
)

// Gate the upgraded transport, not a fake websocket: no kernel buffer or sleep
// is needed to establish that a socket write is stalled.
type gatedSocket struct {
	net.Conn
	started   chan struct{}
	release   chan struct{}
	closed    chan struct{}
	startOnce sync.Once
	closeOnce sync.Once
}

func (c *gatedSocket) Write(p []byte) (int, error) {
	c.startOnce.Do(func() { close(c.started) })
	select {
	case <-c.release:
		return c.Conn.Write(p)
	case <-c.closed:
		return 0, net.ErrClosed
	}
}

func (c *gatedSocket) Close() error {
	c.closeOnce.Do(func() { close(c.closed) })
	return c.Conn.Close()
}

type gatedUpgrade struct {
	http.ResponseWriter
	gate *gatedSocket
}

func (w gatedUpgrade) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	c, rw, err := w.ResponseWriter.(http.Hijacker).Hijack()
	if err != nil {
		return nil, nil, err
	}
	w.gate.Conn = c
	if err := rw.Writer.Flush(); err != nil {
		_ = c.Close()
		return nil, nil, err
	}
	rw.Writer.Reset(w.gate)
	return w.gate, rw, nil
}

func writerSocket(t *testing.T, hub *Hub, stalled bool) (*Conn, *websocket.Conn, *gatedSocket) {
	t.Helper()
	gate := &gatedSocket{started: make(chan struct{}), release: make(chan struct{}), closed: make(chan struct{})}
	if !stalled {
		close(gate.release)
	}
	accepted := make(chan *Conn, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ws, err := websocket.Accept(gatedUpgrade{w, gate}, r, nil)
		if err != nil {
			return
		}
		c := newConn(context.Background(), ws, &auth.User{ID: 42}, discardLogger())
		hub.add(c)
		accepted <- c
		<-c.done
	}))
	t.Cleanup(srv.Close)
	client := dial(t, context.Background(), srv.URL, "")
	var c *Conn
	select {
	case c = <-accepted:
	case <-time.After(time.Second):
		t.Fatal("server did not accept connection")
	}
	t.Cleanup(func() {
		c.close()
		select {
		case <-c.writerDone:
		case <-time.After(time.Second):
			t.Error("writer goroutine did not stop")
		}
	})
	return c, client, gate
}

func awaitSignal(t *testing.T, ch <-chan struct{}, what string) {
	t.Helper()
	select {
	case <-ch:
	case <-time.After(time.Second):
		t.Fatalf("timed out waiting for %s", what)
	}
}

// subscribeLive registers topic with nothing to catch up on, like an empty
// replay, but without queuing the acknowledgement frame.
func subscribeLive(c *Conn, topic string) {
	c.subscribe(topic)
	c.sendMu.Lock()
	c.goLive(topic)
	c.sendMu.Unlock()
}

func pendingBytes(c *Conn) int {
	c.sendMu.Lock()
	defer c.sendMu.Unlock()
	return c.pendingBytes
}

// Fan-out goes through the topic index: a frame reaches only that topic's
// subscribers, and unsubscribe/close leave no index entries behind.
func TestHubTopicIndex(t *testing.T) {
	hub := NewHub()
	a, _, _ := writerSocket(t, hub, true)
	b, _, _ := writerSocket(t, hub, true)
	subscribeLive(a, "room-a")
	subscribeLive(b, "room-b")
	payload := protocol.PongFrame()
	hub.Broadcast("room-a", payload)
	if got := pendingBytes(a); got != len(payload) {
		t.Fatalf("subscriber has %d bytes queued, want %d", got, len(payload))
	}
	if got := pendingBytes(b); got != 0 {
		t.Fatalf("non-subscriber was routed %d bytes", got)
	}
	// Both sockets belong to user 42: the gauge counts connections.
	if n := hub.AuthenticatedCount(); n != 2 {
		t.Fatalf("AuthenticatedCount = %d, want 2", n)
	}
	a.unsubscribe("room-a")
	b.close()
	hub.mu.RLock()
	left := len(hub.topics)
	hub.mu.RUnlock()
	if left != 0 {
		t.Fatalf("topic index keeps %d topics after unsubscribe and close", left)
	}
}

func TestHubSlowSocketIsolation(t *testing.T) {
	hub := NewHub()
	slow, _, gate := writerSocket(t, hub, true)
	fast, client, _ := writerSocket(t, hub, false)
	subscribeLive(slow, "slow-room")
	subscribeLive(fast, "fast-room")
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = rdb.Close() })
	ctx, cancel := context.WithCancel(context.Background())
	stopped := make(chan struct{})
	go func() {
		defer close(stopped)
		_ = events.New(rdb, hub, discardLogger()).Run(ctx)
	}()
	t.Cleanup(func() {
		cancel()
		awaitSignal(t, stopped, "Redis subscriber shutdown")
	})
	// Publish until Redis reports the pattern subscription is established.
	// Frames published before that point have no recipient, so none duplicate.
	readyCtx, readyCancel := context.WithTimeout(ctx, time.Second)
	defer readyCancel()
	ticker := time.NewTicker(10 * time.Millisecond)
	defer ticker.Stop()
	for {
		n, err := rdb.Publish(readyCtx, "realtime:slow-room", protocol.PongFrame()).Result()
		if err != nil {
			t.Fatal(err)
		}
		if n > 0 {
			break
		}
		select {
		case <-ticker.C:
		case <-readyCtx.Done():
			t.Fatal("Redis subscription never became ready")
		}
	}
	awaitSignal(t, gate.started, "stalled write")
	if err := rdb.Publish(ctx, "realtime:fast-room", protocol.PongFrame()).Err(); err != nil {
		t.Fatal(err)
	}
	// A response within 1s proves the shared Redis consume loop did not wait
	// for the stalled socket's 2s write deadline.
	readCtx, readCancel := context.WithTimeout(ctx, time.Second)
	defer readCancel()
	if m := readJSON(t, readCtx, client); m["op"] != "pong" {
		t.Fatalf("healthy room received %v", m)
	}
}

func TestConnWriterFIFOAndRevokedBacklog(t *testing.T) {
	hub := NewHub()
	c, client, gate := writerSocket(t, hub, true)
	subscribeLive(c, "chat")
	if err := c.send(protocol.PongFrame()); err != nil {
		t.Fatal(err)
	}
	awaitSignal(t, gate.started, "first frame")
	hub.Broadcast("chat", protocol.EventFrame("chat", protocol.Envelope{EventType: "secret"}))
	c.unsubscribe("chat")
	for i := range 10 {
		if err := c.send([]byte(fmt.Sprintf(`{"op":"reply","seq":%d}`, i))); err != nil {
			t.Fatal(err)
		}
	}
	close(gate.release)
	if m := readJSON(t, context.Background(), client); m["op"] != "pong" {
		t.Fatalf("first frame = %v", m)
	}
	for i := range 10 {
		m := readJSON(t, context.Background(), client)
		if m["op"] != "reply" || m["seq"] != float64(i) {
			t.Fatalf("reply %d = %v (revoked events must not leak)", i, m)
		}
	}
}

func TestConnOverflowClosesAndRemoves(t *testing.T) {
	hub := NewHub()
	c, _, gate := writerSocket(t, hub, true)
	subscribeLive(c, "room")
	hub.Broadcast("room", protocol.PongFrame())
	awaitSignal(t, gate.started, "stalled frame")
	for range sendQueueSize + 1 {
		hub.Broadcast("room", protocol.PongFrame())
	}
	awaitSignal(t, c.done, "overflow disconnect")
	awaitSignal(t, c.writerDone, "writer shutdown")
	if hub.Count() != 0 || hub.AuthenticatedCount() != 0 {
		t.Fatal("disconnected socket is still accounted")
	}
	if err := c.send(protocol.PongFrame()); err == nil {
		t.Fatal("send after close succeeded")
	}
}

func TestConnCloseAndEnqueueRace(t *testing.T) {
	hub := NewHub()
	c, _, gate := writerSocket(t, hub, true)
	if err := c.send(protocol.PongFrame()); err != nil {
		t.Fatal(err)
	}
	awaitSignal(t, gate.started, "stalled write")
	start := make(chan struct{})
	var wg sync.WaitGroup
	for i := range 40 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			if i%2 == 0 {
				c.close()
			} else {
				_ = c.send(protocol.PongFrame())
			}
		}()
	}
	close(start)
	wg.Wait()
	awaitSignal(t, c.writerDone, "raced writer shutdown")
	if hub.Count() != 0 {
		t.Fatal("racing producers revived a closed connection")
	}
}

func TestConnByteBacklogBound(t *testing.T) {
	hub := NewHub()
	c, _, gate := writerSocket(t, hub, true)
	payload := make([]byte, sendQueueBytes/2+1)
	if err := c.send(payload); err != nil {
		t.Fatal(err)
	}
	awaitSignal(t, gate.started, "large stalled frame")
	if err := c.send(payload); err == nil {
		t.Fatal("byte backlog overflow was accepted")
	}
	awaitSignal(t, c.writerDone, "byte overflow shutdown")
	if hub.Count() != 0 {
		t.Fatal("byte overflow left socket registered")
	}
}

func TestConnSubscriptionReplayBeforeLiveFrames(t *testing.T) {
	const topic = "tournament:1:bracket"
	hub := NewHub()
	c, client, gate := writerSocket(t, hub, true)
	if err := c.send(protocol.PongFrame()); err != nil {
		t.Fatal(err)
	}
	awaitSignal(t, gate.started, "initial stalled write")
	events := make([]protocol.Envelope, 150)
	for i := range events {
		events[i] = protocol.Envelope{EventID: int64(i + 1), EventType: "replayed"}
	}
	h := &Handler{hub: hub, authz: allowAuthorizer{allow: true}, replay: fakeReplayer{cursor: 150, events: events}}
	h.handleSubscribe(context.Background(), c, &protocol.ClientOp{Op: "subscribe", Topic: topic})
	hub.Broadcast(topic, protocol.EventFrame(topic, protocol.Envelope{EventID: 151, EventType: "live"}))
	if err := c.send(protocol.PongFrame()); err != nil {
		t.Fatal(err)
	}
	close(gate.release)
	if m := readJSON(t, context.Background(), client); m["op"] != "pong" {
		t.Fatalf("first reply = %v", m)
	}
	for i := range events {
		m := readJSON(t, context.Background(), client)
		ev, ok := m["event"].(map[string]any)
		if !ok || ev["event_id"] != float64(i+1) || ev["event_type"] != "replayed" {
			t.Fatalf("replay %d = %v", i+1, m)
		}
	}
	if m := readJSON(t, context.Background(), client); m["op"] != "subscribed" || m["cursor"] != float64(150) {
		t.Fatalf("subscription acknowledgement = %v", m)
	}
	if m := readJSON(t, context.Background(), client); m["event"].(map[string]any)["event_id"] != float64(151) {
		t.Fatalf("live frame = %v", m)
	}
	if m := readJSON(t, context.Background(), client); m["op"] != "pong" {
		t.Fatalf("last reply = %v", m)
	}
}

// hookReplayer runs during inside EventsSince: after the subscription's cursor
// snapshot, before its replay is queued.
type hookReplayer struct {
	fakeReplayer
	during func()
}

func (r hookReplayer) EventsSince(ctx context.Context, topic string, after *int64, upTo int64) ([]protocol.Envelope, error) {
	r.during()
	return r.fakeReplayer.EventsSince(ctx, topic, after, upTo)
}

func frameSummary(m map[string]any) string {
	if m["op"] == "subscribed" {
		return fmt.Sprintf("subscribed:%v", m["cursor"])
	}
	ev, _ := m["event"].(map[string]any)
	return fmt.Sprintf("%v:%v", ev["event_type"], ev["event_id"])
}

// An event published after the cursor snapshot but before the subscription
// went live used to reach neither the replay nor the socket. It must arrive
// exactly once, right after the acknowledgement — and a late live copy of an
// event the replay already carries must not arrive twice.
func TestConnSubscriptionCatchUpHasNoGap(t *testing.T) {
	const topic = "tournament:1:bracket"
	hub := NewHub()
	c, client, _ := writerSocket(t, hub, false)
	live := func(id int64) []byte {
		return protocol.EventFrame(topic, protocol.Envelope{EventID: id, EventType: "live"})
	}
	rep := hookReplayer{
		fakeReplayer: fakeReplayer{cursor: 5, events: []protocol.Envelope{
			{EventID: 4, EventType: "replayed"}, {EventID: 5, EventType: "replayed"},
		}},
		during: func() {
			hub.Broadcast(topic, live(5)) // persisted before the snapshot, published late
			hub.Broadcast(topic, live(6)) // persisted after the snapshot
			hub.Broadcast(topic, live(0)) // ephemeral
		},
	}
	h := &Handler{hub: hub, authz: allowAuthorizer{allow: true}, replay: rep}
	after := int64(3)
	h.handleSubscribe(context.Background(), c, &protocol.ClientOp{Op: "subscribe", Topic: topic, AfterEventID: &after})
	hub.Broadcast(topic, live(7))
	for _, want := range []string{"replayed:4", "replayed:5", "subscribed:5", "live:6", "live:0", "live:7"} {
		if got := frameSummary(readJSON(t, context.Background(), client)); got != want {
			t.Fatalf("frame = %s, want %s", got, want)
		}
	}
}

// A subscription still catching up is already visible to revocation, and once
// revoked it never goes live: no acknowledgement, none of its held frames.
func TestConnCatchingUpSubscriptionCanBeRevoked(t *testing.T) {
	const topic = "workspace:1:invalidation"
	hub := NewHub()
	c, client, _ := writerSocket(t, hub, false)
	rep := hookReplayer{during: func() {
		hub.Broadcast(topic, protocol.EventFrame(topic, protocol.Envelope{EventID: 9, EventType: "held"}))
		subs := hub.SubscribersOf(topic)
		if len(subs) != 1 {
			t.Errorf("revocation sees %d subscribers of a catching-up subscription, want 1", len(subs))
		}
		for _, s := range subs {
			s.unsubscribe(topic) // what TopicRevoker does on a denial
		}
	}}
	h := &Handler{hub: hub, authz: allowAuthorizer{allow: true}, replay: rep}
	h.handleSubscribe(context.Background(), c, &protocol.ClientOp{Op: "subscribe", Topic: topic})
	if err := c.send(protocol.PongFrame()); err != nil {
		t.Fatal(err)
	}
	if m := readJSON(t, context.Background(), client); m["op"] != "pong" {
		t.Fatalf("a revoked catching-up subscription delivered %v", m)
	}
	if subs := hub.SubscribersOf(topic); len(subs) != 0 {
		t.Fatalf("revoked subscription still indexed: %d", len(subs))
	}
}

func TestConnWriteTimeoutCleansUp(t *testing.T) {
	hub := NewHub()
	c, _, gate := writerSocket(t, hub, true)
	if err := c.send(protocol.PongFrame()); err != nil {
		t.Fatal(err)
	}
	awaitSignal(t, gate.started, "stalled write")
	select {
	case <-c.writerDone:
	case <-time.After(sendTimeout + time.Second):
		t.Fatal("write deadline did not stop the writer")
	}
	if hub.Count() != 0 {
		t.Fatal("write failure left socket registered")
	}
}
