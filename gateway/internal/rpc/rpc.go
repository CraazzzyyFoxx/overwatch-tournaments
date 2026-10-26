// Package rpc is a RabbitMQ request-reply client for calling FastStream
// services from the (non-Python) gateway. It speaks the standard AMQP RPC
// contract — publish with reply_to + correlation_id, await the reply — so a
// FastStream subscriber that returns a value answers transparently.
//
// The client maintains a single connection with a background reconnect loop:
// on connection loss it fails in-flight calls and re-establishes the channel,
// reply queue, and consumer.
package rpc

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"sync"
	"sync/atomic"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/safego"
)

const (
	contentTypeJSON   = "application/json"
	maxReconnectDelay = 30 * time.Second
	// publishChannels is the size of the publish-only channel pool. amqp091-go
	// serializes writes per channel under an internal mutex, so with a single
	// channel every concurrent Call queues behind one network writer. A small
	// pool spreads publishes across channels on the same connection; the reply
	// consumer keeps its own dedicated channel.
	publishChannels = 4
	// writeTimeout bounds one socket write (see writeBoundedConn). amqp091-go's
	// I/O is not context-aware — PublishWithContext checks ctx only before it
	// starts writing — so a publish stuck on TCP backpressure (a stalled
	// broker not reading the socket) outlived its request deadline, holding the
	// HTTP goroutine, its bulkhead slot and the payload. Writes are at most one
	// frame (frame_max, 128 KiB on RabbitMQ), so 10s is far beyond any healthy
	// link.
	writeTimeout = 10 * time.Second
)

// ErrNotConnected is returned when a call is made before the client has
// established its first connection (or after Close).
var ErrNotConnected = errors.New("rpc: not connected")

// ErrDisconnected is returned when the connection drops while a call is in flight.
var ErrDisconnected = errors.New("rpc: connection lost during call")

// ErrOverloaded is returned when the per-queue in-flight cap is reached, or
// while the broker has blocked the connection (memory/disk alarm). The caller
// should shed the request immediately (HTTP 503) instead of adding it to the
// broker backlog — that backlog growth is what feeds the avalanche.
var ErrOverloaded = errors.New("rpc: queue overloaded")

// ErrUnroutable is returned when the broker bounced the request because no
// queue is bound for it: the worker has not declared its queue yet (cold
// start, deploy) or is not running at all.
var ErrUnroutable = errors.New("rpc: no queue bound for request")

// IsUnavailable reports whether err should map to an immediate 503: the client
// is not connected, the connection dropped mid-call, the request was shed (the
// per-queue in-flight cap, a blocked broker connection), or no queue exists for
// it.
func IsUnavailable(err error) bool {
	return errors.Is(err, ErrNotConnected) || errors.Is(err, ErrDisconnected) ||
		errors.Is(err, ErrOverloaded) || errors.Is(err, ErrUnroutable)
}

// Client owns an AMQP connection, a reply queue, and correlates replies back to
// in-flight calls by correlation_id. It is safe for concurrent use.
type Client struct {
	url string
	log *slog.Logger

	mu         sync.RWMutex
	conn       *amqp.Connection
	ch         *amqp.Channel   // reply-queue channel (declare + consume only)
	pubChs     []*amqp.Channel // publish-only pool; recreated on each connect
	replyQueue string
	connected  bool
	disconnect chan struct{} // closed on disconnect; replaced on each connect
	blocked    *atomic.Bool  // broker connection.blocked; replaced on each connect
	replyDone  chan struct{} // closed when the reply consumer stops; replaced on each connect

	pubSeq atomic.Uint64 // round-robin cursor over pubChs

	pendingMu sync.Mutex
	pending   map[string]chan amqp.Delivery // closed, not sent to, when the broker returns the request

	limiter *limiter
	onShed  func(queue string)

	closeCh   chan struct{}
	closeOnce sync.Once
}

// Option configures a Client at construction time.
type Option func(*Client)

// WithMaxInFlight caps concurrent in-flight calls per queue (bulkhead).
// n <= 0 disables the cap.
func WithMaxInFlight(n int) Option { return func(c *Client) { c.limiter = newLimiter(n) } }

// WithShedHook registers a callback invoked with the queue name every time a
// call is rejected by the in-flight cap — used to feed metrics.
func WithShedHook(fn func(queue string)) Option { return func(c *Client) { c.onShed = fn } }

// New creates a client and starts its background connect/reconnect loop. It
// never blocks: calls made before the first connection return ErrNotConnected.
func New(url string, log *slog.Logger, opts ...Option) *Client {
	if log == nil {
		log = slog.New(slog.NewTextHandler(io.Discard, nil))
	}
	c := &Client{
		url:        url,
		log:        log,
		pending:    make(map[string]chan amqp.Delivery),
		closeCh:    make(chan struct{}),
		disconnect: make(chan struct{}),
		limiter:    newLimiter(0),
	}
	for _, opt := range opts {
		opt(c)
	}
	close(c.disconnect) // start in the disconnected state
	safego.Go(c.run)    // recover panics so a bad reply can't crash the process
	return c
}

// Dial creates a client and waits up to 5s for the first connection, returning
// an error if it cannot connect. Convenient for tests and fail-fast startup.
func Dial(url string) (*Client, error) {
	c := New(url, nil)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := c.waitConnected(ctx); err != nil {
		_ = c.Close()
		return nil, err
	}
	return c, nil
}

func (c *Client) waitConnected(ctx context.Context) error {
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	for {
		c.mu.RLock()
		ok := c.connected
		c.mu.RUnlock()
		if ok {
			return nil
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("%w: %v", ErrNotConnected, ctx.Err())
		case <-ticker.C:
		}
	}
}

func (c *Client) run() {
	backoff := time.Second
	for {
		select {
		case <-c.closeCh:
			return
		default:
		}

		notify, err := c.connect()
		if err != nil {
			c.log.Warn("rpc connect failed", "err", err)
			select {
			case <-c.closeCh:
				return
			case <-time.After(backoff):
			}
			backoff = min(backoff*2, maxReconnectDelay)
			continue
		}
		backoff = time.Second
		c.log.Info("rpc connected")

		select {
		case amqpErr := <-notify:
			c.log.Warn("rpc connection closed", "err", amqpErr)
			c.onDisconnect()
		case <-c.closeCh:
			c.onDisconnect()
			return
		}
	}
}

func (c *Client) connect() (chan *amqp.Error, error) {
	conn, err := amqp.DialConfig(c.url, amqp.Config{Dial: dialWriteBounded})
	if err != nil {
		return nil, fmt.Errorf("amqp dial: %w", err)
	}
	ch, err := conn.Channel()
	if err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("amqp channel: %w", err)
	}
	replyQ, err := ch.QueueDeclare("", false, true, true, false, nil)
	if err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("declare reply queue: %w", err)
	}
	deliveries, err := ch.Consume(replyQ.Name, "", true, true, false, false, nil)
	if err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("consume reply queue: %w", err)
	}

	// Publish-only channel pool on the same connection (see publishChannels).
	// They live and die with the connection, and onDisconnect drops the pool
	// wholesale.
	pubChs := make([]*amqp.Channel, 0, publishChannels)
	for range publishChannels {
		pch, err := conn.Channel()
		if err != nil {
			_ = conn.Close()
			return nil, fmt.Errorf("amqp publish channel: %w", err)
		}
		// Call publishes mandatory, so a request no queue is bound for comes
		// back here (failReturned). Registered before the channel is ever
		// published on: a return with no listener is dropped. The connection's
		// reader goroutine delivers returns synchronously; the buffer absorbs
		// a burst (every call to a missing queue bounces) without stalling it.
		returns := pch.NotifyReturn(make(chan amqp.Return, 16))
		safego.Go(func() { c.failReturned(returns) })
		pubChs = append(pubChs, pch)
	}

	// A channel can also die on its own while the connection stays up (a
	// broker channel.close, a cancelled reply consumer), and conn.NotifyClose
	// never fires for that: the dead channel stayed in the pool failing every
	// publishChannels-th publish with "channel/connection is not open" — or,
	// for the reply channel, left every call waiting out its deadline — until
	// the next connection drop (Sentry OWT-TOURNAMENTS-2AA/2AB/2A8). Closing
	// the connection routes it through run()'s normal reconnect instead.
	// ponytail: one dead channel recycles the whole connection; reopen just
	// that channel if channel errors ever become routine.
	for _, pch := range pubChs {
		closed := pch.NotifyClose(make(chan *amqp.Error, 1))
		safego.Go(func() {
			if err := <-closed; err != nil && !conn.IsClosed() {
				c.log.Warn("rpc publish channel closed, reconnecting", "err", err)
				_ = conn.Close()
			}
		})
	}

	// connection.blocked (broker memory/disk alarm): the broker stops reading
	// a publishing connection's socket, so every publish would sit in the TCP
	// buffers until its deadline — or, once they fill, until writeTimeout
	// tears the connection down. Call sheds instead while it lasts. The flag
	// is per connection: a new one starts unblocked, and the broker announces
	// an alarm still in effect when it blocks that one too.
	blocked := new(atomic.Bool)
	blocks := conn.NotifyBlocked(make(chan amqp.Blocking, 1))
	safego.Go(func() {
		for b := range blocks {
			blocked.Store(b.Active)
			if b.Active {
				c.log.Warn("rpc connection blocked by broker", "reason", b.Reason)
			} else {
				c.log.Info("rpc connection unblocked by broker")
			}
		}
	})

	notify := conn.NotifyClose(make(chan *amqp.Error, 1))
	replyDone := make(chan struct{})
	c.mu.Lock()
	c.conn = conn
	c.ch = ch
	c.pubChs = pubChs
	c.replyQueue = replyQ.Name
	c.connected = true
	c.disconnect = make(chan struct{})
	c.blocked = blocked
	c.replyDone = replyDone
	c.mu.Unlock()

	safego.Go(func() {
		// Deferred so a dispatcher panic (recovered by safego) also marks the
		// client not Ready and recycles the connection, instead of leaving
		// every call to wait out its deadline on a dead consumer.
		defer func() {
			close(replyDone)
			if !conn.IsClosed() {
				c.log.Warn("rpc reply consumer stopped, reconnecting")
				_ = conn.Close()
			}
		}()
		c.dispatchReplies(deliveries)
	})
	return notify, nil
}

func (c *Client) onDisconnect() {
	c.mu.Lock()
	if c.connected {
		c.connected = false
		close(c.disconnect) // wake any in-flight calls
	}
	conn := c.conn
	c.conn = nil
	c.ch = nil
	c.pubChs = nil
	c.mu.Unlock()
	if conn != nil {
		_ = conn.Close()
	}
	// Abandon in-flight waiters; their calls return via the closed disconnect chan.
	c.pendingMu.Lock()
	c.pending = make(map[string]chan amqp.Delivery)
	c.pendingMu.Unlock()
}

func (c *Client) dispatchReplies(deliveries <-chan amqp.Delivery) {
	for d := range deliveries {
		if waiter, ok := c.takePending(d.CorrelationId); ok {
			waiter <- d
		}
	}
}

// failReturned completes the calls whose requests the broker bounced: with
// mandatory set, a publish no queue is bound for comes back as basic.return
// instead of being dropped by the default exchange while its caller waits out
// the whole deadline (120 s on most routes). Closing the waiter is the signal
// Call maps to ErrUnroutable.
func (c *Client) failReturned(returns <-chan amqp.Return) {
	for r := range returns {
		if waiter, ok := c.takePending(r.CorrelationId); ok {
			close(waiter)
		}
	}
}

// takePending removes and returns the waiter for a correlation id. Removing it
// under pendingMu is what lets exactly one of a reply or a return complete a
// call.
func (c *Client) takePending(id string) (chan amqp.Delivery, bool) {
	c.pendingMu.Lock()
	defer c.pendingMu.Unlock()
	waiter, ok := c.pending[id]
	if ok {
		delete(c.pending, id)
	}
	return waiter, ok
}

// Call publishes a request to queue and waits for the reply (JSON bytes), or
// until ctx is done / the connection drops. The body is sent as-is with
// content-type application/json.
func (c *Client) Call(ctx context.Context, queue string, body []byte) ([]byte, error) {
	c.mu.RLock()
	pubChs := c.pubChs
	replyQ := c.replyQueue
	connected := c.connected
	discCh := c.disconnect
	blocked := c.blocked
	c.mu.RUnlock()

	if !connected || len(pubChs) == 0 {
		return nil, ErrNotConnected
	}
	if blocked.Load() {
		return nil, fmt.Errorf("rpc to %q: %w: broker blocked the connection", queue, ErrOverloaded)
	}
	// Round-robin over the publish pool; amqp091-go channels are safe for
	// concurrent use, the pool only spreads the per-channel write lock.
	ch := pubChs[c.pubSeq.Add(1)%uint64(len(pubChs))]

	if !c.limiter.acquire(queue) {
		if c.onShed != nil {
			c.onShed(queue)
		}
		return nil, fmt.Errorf("rpc to %q: %w", queue, ErrOverloaded)
	}
	defer c.limiter.release(queue)

	id, err := newCorrelationID()
	if err != nil {
		return nil, err
	}

	// One PRODUCER span per RPC covering publish + reply wait, mirroring the
	// Python consumer's "rabbitmq consume <queue>" span so Tempo links the two
	// through the traceparent injected below. No-op when tracing is disabled.
	ctx, span := otel.Tracer("gateway/rpc").Start(ctx, "rabbitmq publish "+queue,
		trace.WithSpanKind(trace.SpanKindProducer),
		trace.WithAttributes(
			attribute.String("messaging.system", "rabbitmq"),
			attribute.String("messaging.operation", "publish"),
			attribute.String("messaging.destination.name", queue),
			attribute.String("messaging.message.conversation_id", id),
		),
	)
	defer span.End()

	// AMQP headers: W3C trace context (the FastStream side does
	// propagate.extract(message.headers)) + the request correlation id (read by
	// observe_message_processing, so gateway and worker logs share one id).
	headers := amqp.Table{}
	otel.GetTextMapPropagator().Inject(ctx, headerCarrier(headers))
	if cid := httplog.CorrelationIDFromContext(ctx); cid != "" {
		headers[httplog.CorrelationIDHeader] = cid
	}

	waiter := make(chan amqp.Delivery, 1)
	c.pendingMu.Lock()
	c.pending[id] = waiter
	c.pendingMu.Unlock()
	defer func() {
		c.pendingMu.Lock()
		delete(c.pending, id)
		c.pendingMu.Unlock()
	}()

	// mandatory: a request no queue is bound for comes back as basic.return
	// and fails the call now (failReturned), rather than being dropped while
	// the caller waits out its deadline.
	if err := ch.PublishWithContext(ctx, "", queue, true, false, buildPublishing(ctx, id, replyQ, body, headers)); err != nil {
		// ErrClosed is the channel/connection dying under this call (the
		// window before run() notices), a *net.OpError the socket write
		// failing or hitting writeTimeout (which takes the connection down
		// with it): both the same 503 as a drop mid-call. Not net.Error: the
		// ctx's own DeadlineExceeded satisfies that and stays a 504.
		var opErr *net.OpError
		if errors.Is(err, amqp.ErrClosed) || errors.As(err, &opErr) {
			err = fmt.Errorf("%w: %w", ErrDisconnected, err)
		}
		err = fmt.Errorf("publish rpc request to %q: %w", queue, err)
		span.RecordError(err)
		span.SetStatus(codes.Error, "publish failed")
		return nil, err
	}

	select {
	case d, ok := <-waiter:
		if !ok { // closed by failReturned
			err := fmt.Errorf("rpc to %q: %w", queue, ErrUnroutable)
			span.RecordError(err)
			span.SetStatus(codes.Error, "unroutable")
			return nil, err
		}
		return d.Body, nil
	case <-discCh:
		span.RecordError(ErrDisconnected)
		span.SetStatus(codes.Error, "connection lost")
		return nil, ErrDisconnected
	case <-ctx.Done():
		err := fmt.Errorf("rpc to %q: %w", queue, ctx.Err())
		span.RecordError(err)
		span.SetStatus(codes.Error, "context done")
		return nil, err
	}
}

// headerCarrier adapts an amqp.Table to the OpenTelemetry TextMapCarrier so
// the propagator can write traceparent/tracestate into message headers.
type headerCarrier amqp.Table

func (c headerCarrier) Get(key string) string {
	if v, ok := c[key].(string); ok {
		return v
	}
	return ""
}

func (c headerCarrier) Set(key, value string) { c[key] = value }

func (c headerCarrier) Keys() []string {
	keys := make([]string, 0, len(c))
	for k := range c {
		keys = append(keys, k)
	}
	return keys
}

// Ready reports whether a call can be answered right now: connected, and the
// reply consumer still running — a call published without one waits out its
// whole deadline. For the readiness probe.
func (c *Client) Ready() bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if !c.connected {
		return false
	}
	select {
	case <-c.replyDone:
		return false
	default:
		return true
	}
}

// Close stops the reconnect loop and tears down the connection.
func (c *Client) Close() error {
	c.closeOnce.Do(func() { close(c.closeCh) })
	c.mu.RLock()
	conn := c.conn
	c.mu.RUnlock()
	if conn != nil {
		return conn.Close()
	}
	return nil
}

func newCorrelationID() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", fmt.Errorf("generate correlation id: %w", err)
	}
	return hex.EncodeToString(b), nil
}

// dialWriteBounded is amqp091's default dialer (30s for the TCP connect and
// the AMQP handshake, then cleared) with every socket write bounded by
// writeTimeout.
func dialWriteBounded(network, addr string) (net.Conn, error) {
	conn, err := amqp.DefaultDial(30*time.Second)(network, addr)
	if err != nil {
		return nil, err
	}
	return writeBoundedConn{Conn: conn, timeout: writeTimeout}, nil
}

// writeBoundedConn sets a fresh write deadline before every Write and closes
// the socket when a write fails or times out: a partly written frame leaves
// the AMQP stream unusable, and the close fails the connection's reader, which
// shuts the connection down into run()'s normal reconnect. Everything else —
// reads, the heartbeater's read deadlines, amqp091's own SetDeadline calls
// (it type-asserts net.Conn for them) — goes straight to the embedded conn.
type writeBoundedConn struct {
	net.Conn
	timeout time.Duration
}

func (c writeBoundedConn) Write(p []byte) (int, error) {
	if err := c.SetWriteDeadline(time.Now().Add(c.timeout)); err != nil {
		return 0, err
	}
	n, err := c.Conn.Write(p)
	if err != nil {
		_ = c.Conn.Close()
	}
	return n, err
}
