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
	"sync"
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
)

// ErrNotConnected is returned when a call is made before the client has
// established its first connection (or after Close).
var ErrNotConnected = errors.New("rpc: not connected")

// ErrDisconnected is returned when the connection drops while a call is in flight.
var ErrDisconnected = errors.New("rpc: connection lost during call")

// ErrOverloaded is returned when the per-queue in-flight cap is reached. The
// caller should shed the request immediately (HTTP 503) instead of adding it
// to the broker backlog — that backlog growth is what feeds the avalanche.
var ErrOverloaded = errors.New("rpc: queue overloaded")

// IsUnavailable reports whether err should map to an immediate 503: the client
// is not connected, the connection dropped mid-call, or the request was shed
// by the per-queue in-flight cap.
func IsUnavailable(err error) bool {
	return errors.Is(err, ErrNotConnected) || errors.Is(err, ErrDisconnected) || errors.Is(err, ErrOverloaded)
}

// Client owns an AMQP connection, a reply queue, and correlates replies back to
// in-flight calls by correlation_id. It is safe for concurrent use.
type Client struct {
	url string
	log *slog.Logger

	mu         sync.RWMutex
	conn       *amqp.Connection
	ch         *amqp.Channel
	replyQueue string
	connected  bool
	disconnect chan struct{} // closed on disconnect; replaced on each connect

	pendingMu sync.Mutex
	pending   map[string]chan amqp.Delivery

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
	conn, err := amqp.Dial(c.url)
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

	notify := conn.NotifyClose(make(chan *amqp.Error, 1))
	c.mu.Lock()
	c.conn = conn
	c.ch = ch
	c.replyQueue = replyQ.Name
	c.connected = true
	c.disconnect = make(chan struct{})
	c.mu.Unlock()

	safego.Go(func() { c.dispatchReplies(deliveries) })
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
		c.pendingMu.Lock()
		waiter, ok := c.pending[d.CorrelationId]
		if ok {
			delete(c.pending, d.CorrelationId)
		}
		c.pendingMu.Unlock()
		if ok {
			waiter <- d
		}
	}
}

// Call publishes a request to queue and waits for the reply (JSON bytes), or
// until ctx is done / the connection drops. The body is sent as-is with
// content-type application/json.
func (c *Client) Call(ctx context.Context, queue string, body []byte) ([]byte, error) {
	c.mu.RLock()
	ch := c.ch
	replyQ := c.replyQueue
	connected := c.connected
	discCh := c.disconnect
	c.mu.RUnlock()

	if !connected || ch == nil {
		return nil, ErrNotConnected
	}

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

	if err := ch.PublishWithContext(ctx, "", queue, false, false, buildPublishing(ctx, id, replyQ, body, headers)); err != nil {
		err = fmt.Errorf("publish rpc request to %q: %w", queue, err)
		span.RecordError(err)
		span.SetStatus(codes.Error, "publish failed")
		return nil, err
	}

	select {
	case d := <-waiter:
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
