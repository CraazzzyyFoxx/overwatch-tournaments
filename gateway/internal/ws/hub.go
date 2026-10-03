package ws

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"sort"
	"sync"
	"time"

	"github.com/coder/websocket"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/protocol"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/safego"
)

const (
	sendTimeout    = 2 * time.Second
	sendQueueSize  = 64
	sendQueueBytes = 4 << 20
)

var errSendBacklog = errors.New("websocket send backlog exceeded")

type outboundFrame struct {
	topic   string // empty for direct replies; topic frames are dropped after revocation
	payload []byte
	replay  [][]byte // one ordered subscription replay + acknowledgement
	bytes   int
}

// Conn is a single live WebSocket connection and its subscription state.
type Conn struct {
	ws      *websocket.Conn
	user    *auth.User // nil => anonymous
	baseCtx context.Context
	log     *slog.Logger // request-scoped: carries correlation_id

	sendMu       sync.Mutex // guards enqueue, close, byte budget and hub ownership
	outbound     chan outboundFrame
	done         chan struct{} // outbound is never closed: producers may race cleanup
	writerDone   chan struct{}
	pendingBytes int // includes the frame currently being written
	cancel       context.CancelFunc
	hub          *Hub
	closed       bool

	topicsMu sync.RWMutex
	topics   map[string]struct{}

	pubMu          sync.Mutex // guards the publish rate-limit window
	pubWindowStart time.Time
	pubWindowCount int
}

func newConn(ctx context.Context, c *websocket.Conn, user *auth.User, log *slog.Logger) *Conn {
	if log == nil {
		log = slog.Default()
	}
	ctx, cancel := context.WithCancel(ctx)
	conn := &Conn{
		ws: c, user: user, baseCtx: ctx, log: log, topics: make(map[string]struct{}),
		outbound: make(chan outboundFrame, sendQueueSize), done: make(chan struct{}),
		writerDone: make(chan struct{}), cancel: cancel,
	}
	safego.Go(conn.writeLoop)
	return conn
}

// send only enqueues. All socket writes, including direct replies, use one pump.
// Payloads are immutable after enqueue; fan-out shares the serialized bytes.
func (c *Conn) send(payload []byte) error {
	return c.enqueue(outboundFrame{payload: payload, bytes: len(payload)})
}

func (c *Conn) enqueue(frame outboundFrame) error {
	c.sendMu.Lock()
	err := c.enqueueLocked(frame)
	c.sendMu.Unlock()
	if err != nil {
		c.close()
	}
	return err
}

func (c *Conn) enqueueLocked(frame outboundFrame) error {
	if c.closed {
		return net.ErrClosed
	}
	if frame.topic != "" && !c.hasTopic(frame.topic) {
		return nil
	}
	if frame.bytes > sendQueueBytes-c.pendingBytes {
		return errSendBacklog
	}
	select {
	case c.outbound <- frame:
		c.pendingBytes += frame.bytes
		return nil
	default:
		return errSendBacklog
	}
}

// Subscribe and queue catch-up atomically with respect to live enqueue. A replay
// is one queue item so a valid replay larger than 64 events doesn't overflow the
// live-event slot budget or interleave live frames before its acknowledgement.
func (c *Conn) sendSubscription(topic string, events []protocol.Envelope, cursor int64) error {
	frame := outboundFrame{topic: topic, replay: make([][]byte, 0, len(events)+1)}
	for _, ev := range events {
		payload := protocol.EventFrame(topic, ev)
		frame.bytes += len(payload)
		if frame.bytes > sendQueueBytes {
			c.close()
			return errSendBacklog
		}
		frame.replay = append(frame.replay, payload)
	}
	ack := protocol.SubscribedFrame(topic, cursor)
	frame.replay = append(frame.replay, ack)
	frame.bytes += len(ack)
	c.sendMu.Lock()
	if !c.closed {
		c.subscribe(topic)
	}
	err := c.enqueueLocked(frame)
	c.sendMu.Unlock()
	if err != nil {
		c.close()
	}
	return err
}

func (c *Conn) writeLoop() {
	defer close(c.writerDone)
	// Release any queued payload references on exit, even if a revoker still
	// holds this Conn in its subscriber snapshot.
	defer func() {
		c.close()
		// Never perform even socket-close I/O on the Redis fan-in goroutine.
		// CloseNow interrupts the reader without waiting for a peer handshake;
		// the read handler still owns presence/IP cleanup.
		_ = c.ws.CloseNow()
		c.sendMu.Lock()
		defer c.sendMu.Unlock()
		for len(c.outbound) > 0 {
			<-c.outbound
		}
		c.pendingBytes = 0
	}()
	for {
		select {
		case <-c.baseCtx.Done():
			return
		case <-c.done:
			return
		case frame := <-c.outbound:
			if c.baseCtx.Err() != nil {
				return
			}
			write := func(payload []byte) error {
				if frame.topic != "" && !c.hasTopic(frame.topic) {
					return nil
				}
				ctx, cancel := context.WithTimeout(c.baseCtx, sendTimeout)
				defer cancel()
				return c.ws.Write(ctx, websocket.MessageText, payload)
			}
			var err error
			if frame.replay != nil {
				for _, payload := range frame.replay {
					if err = write(payload); err != nil {
						break
					}
				}
			} else {
				err = write(frame.payload)
			}
			if err != nil {
				return
			}
			c.sendMu.Lock()
			c.pendingBytes -= frame.bytes
			c.sendMu.Unlock()
		}
	}
}

func (c *Conn) subscribe(topic string) {
	c.topicsMu.Lock()
	c.topics[topic] = struct{}{}
	c.topicsMu.Unlock()
}

func (c *Conn) unsubscribe(topic string) {
	c.topicsMu.Lock()
	delete(c.topics, topic)
	c.topicsMu.Unlock()
}

func (c *Conn) hasTopic(topic string) bool {
	c.topicsMu.RLock()
	_, ok := c.topics[topic]
	c.topicsMu.RUnlock()
	return ok
}

func (c *Conn) topicCount() int {
	c.topicsMu.RLock()
	defer c.topicsMu.RUnlock()
	return len(c.topics)
}

func (c *Conn) subscribedTopics() []string {
	c.topicsMu.RLock()
	defer c.topicsMu.RUnlock()
	topics := make([]string, 0, len(c.topics))
	for t := range c.topics {
		topics = append(topics, t)
	}
	return topics
}

// allowPublish enforces a sliding 1-second window of at most
// MaxPublishPerSecond client-originated frames.
func (c *Conn) allowPublish(now time.Time) bool {
	c.pubMu.Lock()
	defer c.pubMu.Unlock()
	if now.Sub(c.pubWindowStart) >= time.Second {
		c.pubWindowStart = now
		c.pubWindowCount = 0
	}
	c.pubWindowCount++
	return c.pubWindowCount <= MaxPublishPerSecond
}

func (c *Conn) close() {
	c.sendMu.Lock()
	if c.closed {
		c.sendMu.Unlock()
		return
	}
	c.closed = true
	close(c.done)
	c.cancel()
	hub := c.hub
	c.sendMu.Unlock()
	if hub != nil {
		hub.remove(c)
	}
}

// Hub is the in-process registry of live connections.
type Hub struct {
	mu    sync.RWMutex
	conns map[*Conn]struct{}
}

// NewHub returns an empty connection registry.
func NewHub() *Hub {
	return &Hub{conns: make(map[*Conn]struct{})}
}

func (h *Hub) add(c *Conn) {
	c.sendMu.Lock()
	defer c.sendMu.Unlock()
	if c.closed {
		return
	}
	c.hub = h
	h.mu.Lock()
	h.conns[c] = struct{}{}
	h.mu.Unlock()
}

func (h *Hub) remove(c *Conn) {
	h.mu.Lock()
	delete(h.conns, c)
	h.mu.Unlock()
}

// Broadcast delivers a frame to every subscriber of topic. It is the entry
// point for the Redis fan-in path (server-originated events).
func (h *Hub) Broadcast(topic string, payload []byte) {
	h.Route(topic, payload, nil)
}

// Count returns the number of live connections (for diagnostics).
func (h *Hub) Count() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.conns)
}

// DistinctUsers returns the number of distinct authenticated users currently
// connected. Anonymous connections are ignored.
func (h *Hub) DistinctUsers() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	seen := make(map[int64]struct{}, len(h.conns))
	for c := range h.conns {
		if c.user != nil {
			seen[c.user.ID] = struct{}{}
		}
	}
	return len(seen)
}

// CloseAll disconnects every live connection on shutdown. HTTP Shutdown does
// not wait for hijacked sockets; cancellation also terminates their writers.
func (h *Hub) CloseAll() {
	h.mu.Lock()
	conns := make([]*Conn, 0, len(h.conns))
	for c := range h.conns {
		conns = append(conns, c)
	}
	h.conns = make(map[*Conn]struct{})
	h.mu.Unlock()

	for _, c := range conns {
		c.close()
	}
}

// SubscribersOf returns a snapshot of the connections currently subscribed to
// topic. The snapshot is taken under the same lock Route uses and is stale the
// moment it is returned — callers (TopicRevoker) must tolerate a connection
// that unsubscribed or closed in between, which unsubscribe/send already do.
func (h *Hub) SubscribersOf(topic string) []*Conn {
	h.mu.RLock()
	defer h.mu.RUnlock()
	subs := make([]*Conn, 0, len(h.conns))
	for c := range h.conns {
		if c.hasTopic(topic) {
			subs = append(subs, c)
		}
	}
	return subs
}

// Route queues a pre-serialized frame for every subscriber except exclude.
// Enqueue never waits for socket I/O; a bounded-backlog overflow disconnects
// that client, without delaying subsequent Redis events or other rooms.
func (h *Hub) Route(topic string, payload []byte, exclude *Conn) {
	h.mu.RLock()
	targets := make([]*Conn, 0, len(h.conns))
	for c := range h.conns {
		if c == exclude {
			continue
		}
		if c.hasTopic(topic) {
			targets = append(targets, c)
		}
	}
	h.mu.RUnlock()

	for _, c := range targets {
		_ = c.enqueue(outboundFrame{topic: topic, payload: payload, bytes: len(payload)})
	}
}

// presenceUserIDs returns the distinct authenticated user ids currently
// subscribed to topic, sorted ascending. Anonymous connections are excluded.
func (h *Hub) presenceUserIDs(topic string) []int64 {
	ids, _ := h.presenceStats(topic)
	return ids
}

// presenceStats returns distinct authenticated users and the exact number of
// anonymous connections subscribed to a topic.
func (h *Hub) presenceStats(topic string) ([]int64, int) {
	h.mu.RLock()
	seen := make(map[int64]struct{})
	anonymous := 0
	for c := range h.conns {
		if !c.hasTopic(topic) {
			continue
		}
		if c.user == nil {
			anonymous++
			continue
		}
		seen[c.user.ID] = struct{}{}
	}
	h.mu.RUnlock()

	ids := make([]int64, 0, len(seen))
	for id := range seen {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	return ids, anonymous
}
