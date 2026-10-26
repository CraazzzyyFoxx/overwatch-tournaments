package rpc

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	"sync/atomic"
	"testing"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

// TestRPCInterop is the Go<->FastStream interop spike. It requires:
//   - RabbitMQ on GATEWAY_RPC_URL (default amqp://guest:guest@localhost:5672)
//   - the FastStream responder running (scripts/rpc-spike/responder.py)
//
// Run: GATEWAY_RPC_SPIKE=1 go test ./internal/rpc/ -run TestRPCInterop -v
func TestRPCInterop(t *testing.T) {
	if os.Getenv("GATEWAY_RPC_SPIKE") == "" {
		t.Skip("set GATEWAY_RPC_SPIKE=1 (and run the FastStream responder) to run the interop spike")
	}
	url := os.Getenv("GATEWAY_RPC_URL")
	if url == "" {
		url = "amqp://guest:guest@localhost:5672"
	}

	c, err := Dial(url)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer c.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := c.Call(ctx, "rpc.spike.echo", []byte(`{"hello":"world","n":42}`))
	if err != nil {
		t.Fatalf("rpc call: %v", err)
	}

	var got map[string]any
	if err := json.Unmarshal(resp, &got); err != nil {
		t.Fatalf("unmarshal reply %q: %v", resp, err)
	}
	t.Logf("reply: %s", resp)

	if got["pong"] != true || got["service"] != "faststream" {
		t.Fatalf("unexpected reply: %v", got)
	}
	echo, ok := got["echo"].(map[string]any)
	if !ok || echo["hello"] != "world" || echo["n"] != float64(42) {
		t.Fatalf("echo mismatch: %v", got["echo"])
	}
}

// TestIdentityValidateToken_Garbage hits the real identity-svc validate_token
// RPC method with an invalid token and asserts the error envelope. Requires the
// identity-svc worker running. Run:
//
//	GATEWAY_RPC_SPIKE=1 go test ./internal/rpc/ -run TestIdentityValidateToken -v
func TestIdentityValidateToken_Garbage(t *testing.T) {
	if os.Getenv("GATEWAY_RPC_SPIKE") == "" {
		t.Skip("set GATEWAY_RPC_SPIKE=1 (and run identity-svc) to run")
	}
	url := os.Getenv("GATEWAY_RPC_URL")
	if url == "" {
		url = "amqp://guest:guest@localhost:5672"
	}

	c, err := Dial(url)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer c.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := c.Call(ctx, "rpc.identity.validate_token", []byte(`{"token":"garbage.jwt.token"}`))
	if err != nil {
		t.Fatalf("rpc call: %v", err)
	}
	t.Logf("envelope: %s", resp)

	var env struct {
		OK    bool `json:"ok"`
		Error struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if err := json.Unmarshal(resp, &env); err != nil {
		t.Fatalf("unmarshal envelope %q: %v", resp, err)
	}
	if env.OK || env.Error.Code != "unauthorized" {
		t.Fatalf("expected ok=false code=unauthorized, got %+v", env)
	}
}

// spikeBroker returns the RabbitMQ URL for the broker-only tests below, or
// skips. They need no FastStream worker: each answers its own queue. Run:
//
//	GATEWAY_RPC_SPIKE=1 GATEWAY_RPC_URL=amqp://guest:guest@localhost:5672 go test ./internal/rpc/ -run Channel -v
func spikeBroker(t *testing.T) string {
	t.Helper()
	if os.Getenv("GATEWAY_RPC_SPIKE") == "" {
		t.Skip("set GATEWAY_RPC_SPIKE=1 (RabbitMQ on GATEWAY_RPC_URL) to run")
	}
	if url := os.Getenv("GATEWAY_RPC_URL"); url != "" {
		return url
	}
	return "amqp://guest:guest@localhost:5672"
}

// A channel the broker closes on its own while the connection stays up (here
// a publish to a missing exchange, answered with a 404 channel.close) must not
// survive: a dead publish channel failed every publishChannels-th call with
// "channel/connection is not open" until the next connection drop (Sentry
// OWT-TOURNAMENTS-2AA/2AB/2A8), and a dead reply channel left every call
// waiting out its deadline.
func TestChannelLossReconnects(t *testing.T) {
	url := spikeBroker(t)

	// Echo responder on a private queue.
	conn, err := amqp.Dial(url)
	if err != nil {
		t.Fatalf("responder dial: %v", err)
	}
	defer conn.Close()
	sub, err := conn.Channel()
	if err != nil {
		t.Fatalf("responder channel: %v", err)
	}
	pub, err := conn.Channel()
	if err != nil {
		t.Fatalf("responder channel: %v", err)
	}
	q, err := sub.QueueDeclare("", false, true, true, false, nil)
	if err != nil {
		t.Fatalf("declare: %v", err)
	}
	msgs, err := sub.Consume(q.Name, "", true, true, false, false, nil)
	if err != nil {
		t.Fatalf("consume: %v", err)
	}
	go func() {
		for d := range msgs {
			_ = pub.Publish("", d.ReplyTo, false, false, amqp.Publishing{CorrelationId: d.CorrelationId, Body: d.Body})
		}
	}()

	for name, pick := range map[string]func(*Client) *amqp.Channel{
		"publish channel": func(c *Client) *amqp.Channel { return c.pubChs[0] },
		"reply channel":   func(c *Client) *amqp.Channel { return c.ch },
	} {
		t.Run(name, func(t *testing.T) {
			c, err := Dial(url)
			if err != nil {
				t.Fatalf("dial: %v", err)
			}
			defer c.Close()

			c.mu.RLock()
			dead := pick(c)
			c.mu.RUnlock()
			_ = dead.Publish("gateway-test-no-such-exchange", "", false, false, amqp.Publishing{})
			deadline := time.Now().Add(5 * time.Second)
			for !dead.IsClosed() {
				if time.Now().After(deadline) {
					t.Fatal("broker never closed the channel")
				}
				time.Sleep(10 * time.Millisecond)
			}

			// Two full laps of the round-robin must all succeed once the
			// client has recovered; calls during the reconnect may be refused.
			for {
				var lapErr error
				for range 2 * publishChannels {
					ctx, cancel := context.WithTimeout(context.Background(), time.Second)
					_, lapErr = c.Call(ctx, q.Name, []byte(`{}`))
					cancel()
					if lapErr != nil {
						break
					}
				}
				if lapErr == nil {
					return
				}
				if time.Now().After(deadline) {
					t.Fatalf("client never recovered from a dead %s: %v", name, lapErr)
				}
				time.Sleep(50 * time.Millisecond)
			}
		})
	}
}

// A publish that lands on a channel closed under it is the broker link
// dropping mid-call: it must map to the immediate 503 (IsUnavailable), like
// ErrNotConnected/ErrDisconnected, not to the generic 504 "service timeout".
func TestClosedChannelPublishIsUnavailable(t *testing.T) {
	url := spikeBroker(t)
	conn, err := amqp.Dial(url)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	ch, err := conn.Channel()
	if err != nil {
		t.Fatalf("channel: %v", err)
	}
	_ = conn.Close()

	// The window between the connection dying and run()'s onDisconnect: the
	// client still believes it is connected.
	c := &Client{
		connected:  true,
		pubChs:     []*amqp.Channel{ch},
		disconnect: make(chan struct{}),
		blocked:    new(atomic.Bool),
		pending:    make(map[string]chan amqp.Delivery),
		limiter:    newLimiter(0),
	}
	_, err = c.Call(context.Background(), "q", []byte(`{}`))
	if !IsUnavailable(err) || !errors.Is(err, amqp.ErrClosed) {
		t.Fatalf("Call on a closed channel = %v, want ErrDisconnected wrapping amqp.ErrClosed", err)
	}
}

// A request to a queue nobody has declared yet (a worker still starting during
// a deploy) used to be dropped by the default exchange while the caller waited
// out the whole route deadline — 120 s by default — before a 504. Published
// mandatory, the broker returns it and the call fails at once with a 503.
func TestUnroutableCallFailsFast(t *testing.T) {
	url := spikeBroker(t)
	c, err := Dial(url)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer c.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	start := time.Now()
	_, err = c.Call(ctx, "gateway-test-no-such-queue", []byte(`{}`))
	if !errors.Is(err, ErrUnroutable) || !IsUnavailable(err) {
		t.Fatalf("Call to a missing queue = %v, want ErrUnroutable (503)", err)
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Fatalf("Call to a missing queue took %v, want an immediate failure", elapsed)
	}
}

// The broker-free half of the same contract: a basic.return completes exactly
// the call it names (Call maps the closed waiter to ErrUnroutable), and a
// return for a call that already finished is a no-op.
func TestReturnedRequestCompletesItsCall(t *testing.T) {
	bounced, other := make(chan amqp.Delivery, 1), make(chan amqp.Delivery, 1)
	c := &Client{pending: map[string]chan amqp.Delivery{"bounced": bounced, "other": other}}
	returns := make(chan amqp.Return, 2)
	returns <- amqp.Return{CorrelationId: "bounced"}
	returns <- amqp.Return{CorrelationId: "finished"}
	close(returns)

	c.failReturned(returns)

	if _, ok := <-bounced; ok {
		t.Fatal("the returned call's waiter received a reply instead of being closed")
	}
	if _, waiting := c.pending["other"]; !waiting || len(c.pending) != 1 {
		t.Fatalf("pending = %v, want only the unrelated call left waiting", c.pending)
	}
}

// While the broker reports the connection blocked (memory/disk alarm) it stops
// reading the socket: a publish would sit in the TCP buffers until its
// deadline. Call must shed at once with the 503 the in-flight cap uses.
func TestBlockedConnectionShedsCall(t *testing.T) {
	blocked := new(atomic.Bool)
	blocked.Store(true)
	c := &Client{
		connected:  true,
		pubChs:     make([]*amqp.Channel, 1), // never reached: shed before publish
		disconnect: make(chan struct{}),
		blocked:    blocked,
		pending:    make(map[string]chan amqp.Delivery),
		limiter:    newLimiter(0),
	}
	_, err := c.Call(context.Background(), "q", []byte(`{}`))
	if !errors.Is(err, ErrOverloaded) || !IsUnavailable(err) {
		t.Fatalf("Call on a blocked connection = %v, want ErrOverloaded (503)", err)
	}
}

// A write the broker never drains (TCP backpressure from a stalled broker)
// must fail within the bound and close the socket — the close is what fails
// the connection's reader into the reconnect — instead of blocking the publish
// past its request deadline.
func TestStalledWriteFailsAndClosesSocket(t *testing.T) {
	client, broker := net.Pipe()
	defer broker.Close()
	conn := writeBoundedConn{Conn: client, timeout: 20 * time.Millisecond}

	_, err := conn.Write([]byte("frame"))
	var netErr net.Error
	if !errors.As(err, &netErr) || !netErr.Timeout() {
		t.Fatalf("stalled write = %v, want a timeout", err)
	}
	if _, err := broker.Read(make([]byte, 1)); err != io.EOF {
		t.Fatalf("peer read = %v, want io.EOF (socket closed)", err)
	}
}
