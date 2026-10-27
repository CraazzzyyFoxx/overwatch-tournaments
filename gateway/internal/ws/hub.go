package ws

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"sort"
	"sync"
	"sync/atomic"
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

var (
	errSendBacklog = errors.New("websocket send backlog exceeded")
	errRevoked     = errors.New("subscription revoked while catching up")
)

type outboundFrame struct {
	topic   string // empty for direct replies; topic frames are dropped after revocation
	payload []byte
	replay  [][]byte // one ordered subscription replay + acknowledgement
	bytes   int
}

// catchUp holds the live frames that reach a subscription while its replay is
// still being read, so nothing published between the replay cursor and going
// live is lost. Its fields are guarded by the connection's sendMu.
type catchUp struct {
	frames [][]byte
	bytes  int
}

// Conn is a single live WebSocket connection and its subscription state.
type Conn struct {
	ws      *websocket.Conn
	user    atomic.Pointer[auth.User] // nil => anonymous; read through principal()
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
	closeStatus  websocket.StatusCode // non-zero: the writer sends it in a close frame
	closeReason  string               // the close frame's reason, with closeStatus

	topicsMu sync.RWMutex
	topics   map[string]*catchUp // nil value: live; non-nil: still catching up

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
		ws: c, baseCtx: ctx, log: log, topics: make(map[string]*catchUp),
		outbound: make(chan outboundFrame, sendQueueSize), done: make(chan struct{}),
		writerDone: make(chan struct{}), cancel: cancel,
	}
	conn.user.Store(user)
	safego.Go(conn.writeLoop)
	return conn
}

// principal is the connection's current principal (nil: anonymous). Only its
// superuser bit ever changes — TopicRevoker swaps in a re-judged copy — so its
// nil-ness and ID are fixed for the connection's life.
func (c *Conn) principal() *auth.User { return c.user.Load() }

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
	if frame.topic != "" {
		c.topicsMu.RLock()
		pending, subscribed := c.topics[frame.topic]
		c.topicsMu.RUnlock()
		if !subscribed {
			return nil
		}
		if pending != nil {
			// Held for sendSubscription, inside the same byte budget as the
			// queue: a subscription that falls this far behind is a slow client.
			if frame.bytes > sendQueueBytes-c.pendingBytes-pending.bytes {
				return errSendBacklog
			}
			pending.frames = append(pending.frames, frame.payload)
			pending.bytes += frame.bytes
			return nil
		}
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

// sendSubscription ends a subscription's catch-up atomically with respect to
// live enqueue: it queues the replay, the acknowledgement and then the live
// frames held since subscribe, and makes the subscription live. A replay is one
// queue item so a valid replay larger than 64 events doesn't overflow the
// live-event slot budget or interleave live frames before its acknowledgement.
// Held frames the replay already covers (event id <= cursor) are dropped;
// ephemeral ones (no id) pass. A subscription revoked while it was catching up
// queues nothing and reports errRevoked.
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
	if c.closed {
		c.sendMu.Unlock()
		return net.ErrClosed
	}
	held := c.goLive(topic)
	if held == nil {
		c.sendMu.Unlock()
		return errRevoked
	}
	for _, payload := range held.frames {
		if id := frameEventID(payload); id == 0 || id > cursor {
			frame.replay = append(frame.replay, payload)
			frame.bytes += len(payload)
		}
	}
	err := c.enqueueLocked(frame)
	c.sendMu.Unlock()
	if err != nil {
		c.close()
	}
	return err
}

// frameEventID returns a serialized event frame's event id: 0 for an ephemeral
// event or a frame that carries none.
func frameEventID(raw []byte) int64 {
	var probe struct {
		Event struct {
			EventID int64 `json:"event_id"`
		} `json:"event"`
	}
	if json.Unmarshal(raw, &probe) != nil {
		return 0
	}
	return probe.Event.EventID
}

func (c *Conn) writeLoop() {
	defer close(c.writerDone)
	// Release any queued payload references on exit, even if a revoker still
	// holds this Conn in its subscriber snapshot.
	defer func() {
		c.close()
		// Never perform even socket-close I/O on the Redis fan-in goroutine.
		// CloseNow interrupts the reader without waiting for a peer handshake;
		// the read handler still owns presence/IP cleanup. A deliberate close
		// (closeWith) instead runs the handshake here, on this socket's own
		// goroutine, so the client learns why and reconnects.
		c.sendMu.Lock()
		status, reason := c.closeStatus, c.closeReason
		c.sendMu.Unlock()
		if status != 0 {
			_ = c.ws.Close(status, reason)
		} else {
			_ = c.ws.CloseNow()
		}
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

// subscribe registers topic in catch-up mode: from here on its live frames are
// held, not sent, until sendSubscription releases them behind the replay. The
// handler registers before it reads the replay cursor, so an event published in
// between reaches the socket exactly once (replayed or held), and before it
// authorizes, so a revocation pass (SubscribersOf, subscribedTopics) already
// finds the subscription. false: c is closed.
func (c *Conn) subscribe(topic string) bool {
	c.sendMu.Lock()
	defer c.sendMu.Unlock()
	if c.closed {
		return false
	}
	c.topicsMu.Lock()
	c.topics[topic] = &catchUp{}
	if c.hub != nil {
		c.hub.index(c, topic, false)
	}
	c.topicsMu.Unlock()
	return true
}

// goLive makes a catching-up subscription live and returns what it held; nil
// when the subscription is gone (revoked while catching up). Caller holds
// sendMu, so no live frame can slip between the two states.
func (c *Conn) goLive(topic string) *catchUp {
	c.topicsMu.Lock()
	defer c.topicsMu.Unlock()
	held := c.topics[topic]
	if held == nil {
		return nil
	}
	c.topics[topic] = nil
	if c.hub != nil {
		c.hub.index(c, topic, true)
	}
	return held
}

func (c *Conn) unsubscribe(topic string) {
	c.sendMu.Lock()
	hub := c.hub
	c.sendMu.Unlock()
	c.topicsMu.Lock()
	delete(c.topics, topic)
	if hub != nil {
		hub.unindex(c, topic)
	}
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

// closeWith is close, but the writer then sends status and reason in a close
// frame instead of dropping the socket, so the client knows the server ended
// it on purpose. Queued frames are discarded either way.
func (c *Conn) closeWith(status websocket.StatusCode, reason string) {
	c.sendMu.Lock()
	if !c.closed {
		c.closeStatus, c.closeReason = status, reason
	}
	c.sendMu.Unlock()
	c.close()
}

// Hub is the in-process registry of live connections.
//
// Lock order: Conn.sendMu, then Conn.topicsMu, then Hub.mu. Nothing holds
// Hub.mu while taking a connection lock.
type Hub struct {
	mu    sync.RWMutex
	conns map[*Conn]struct{}
	// topics indexes subscribers by topic, so fan-out and presence touch only
	// that topic's sockets. The value is false while the subscription is still
	// catching up (its frames are held, it is not yet in presence). It changes
	// together with Conn.topics, under that connection's topicsMu.
	topics map[string]map[*Conn]bool
	// closing is set by CloseAll: add refuses connections from then on.
	closing bool
}

// NewHub returns an empty connection registry.
func NewHub() *Hub {
	return &Hub{conns: make(map[*Conn]struct{}), topics: make(map[string]map[*Conn]bool)}
}

// add registers c. false: c is already closed, or CloseAll has run — a socket
// registered after its snapshot would never be closed by it.
func (h *Hub) add(c *Conn) bool {
	c.sendMu.Lock()
	defer c.sendMu.Unlock()
	if c.closed {
		return false
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.closing {
		return false
	}
	c.hub = h
	h.conns[c] = struct{}{}
	return true
}

// remove unregisters c and its topics. c is closed (or its read loop is over),
// so it cannot subscribe again behind the snapshot.
func (h *Hub) remove(c *Conn) {
	topics := c.subscribedTopics()
	h.mu.Lock()
	delete(h.conns, c)
	for _, topic := range topics {
		h.unindexLocked(c, topic)
	}
	h.mu.Unlock()
}

func (h *Hub) index(c *Conn, topic string, live bool) {
	h.mu.Lock()
	subs := h.topics[topic]
	if subs == nil {
		subs = make(map[*Conn]bool)
		h.topics[topic] = subs
	}
	subs[c] = live
	h.mu.Unlock()
}

func (h *Hub) unindex(c *Conn, topic string) {
	h.mu.Lock()
	h.unindexLocked(c, topic)
	h.mu.Unlock()
}

func (h *Hub) unindexLocked(c *Conn, topic string) {
	subs := h.topics[topic]
	delete(subs, c)
	if len(subs) == 0 {
		delete(h.topics, topic)
	}
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

// AuthenticatedCount returns the number of live connections that carry a
// principal (session or API key). Anonymous connections are ignored.
func (h *Hub) AuthenticatedCount() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	n := 0
	for c := range h.conns {
		if c.principal() != nil {
			n++
		}
	}
	return n
}

// CloseAll disconnects every live connection on shutdown and makes add refuse
// any that arrive later, so a socket accepted concurrently cannot outlive it.
// HTTP Shutdown does not wait for hijacked sockets; cancellation also
// terminates their writers.
func (h *Hub) CloseAll() {
	h.mu.Lock()
	h.closing = true
	conns := make([]*Conn, 0, len(h.conns))
	for c := range h.conns {
		conns = append(conns, c)
	}
	h.mu.Unlock()

	for _, c := range conns {
		c.close()
	}
}

// Reset implements events.Resetter. After the Redis subscription was lost every
// live socket may have missed frames, so each is closed with 1012 (service
// restart): clients reconnect and replay from their cursor. New connections
// stay accepted. It runs on the Redis fan-in goroutine, so it only marks the
// sockets; each writer performs its own close handshake.
func (h *Hub) Reset() {
	h.mu.RLock()
	conns := make([]*Conn, 0, len(h.conns))
	for c := range h.conns {
		conns = append(conns, c)
	}
	h.mu.RUnlock()

	for _, c := range conns {
		c.closeWith(websocket.StatusServiceRestart, "")
	}
}

// SubscribersOf returns a snapshot of the connections currently subscribed to
// topic, including ones still catching up. The snapshot is taken under the
// same lock Route uses and is stale the moment it is returned — callers
// (TopicRevoker) must tolerate a connection that unsubscribed or closed in
// between, which unsubscribe/send already do.
func (h *Hub) SubscribersOf(topic string) []*Conn {
	return h.subscribers(topic, nil)
}

func (h *Hub) subscribers(topic string, exclude *Conn) []*Conn {
	h.mu.RLock()
	defer h.mu.RUnlock()
	subs := make([]*Conn, 0, len(h.topics[topic]))
	for c := range h.topics[topic] {
		if c != exclude {
			subs = append(subs, c)
		}
	}
	return subs
}

// connsOf snapshots the live connections authenticated as userID, with the
// same staleness caveat as SubscribersOf.
func (h *Hub) connsOf(userID int64) []*Conn {
	h.mu.RLock()
	defer h.mu.RUnlock()
	var conns []*Conn
	for c := range h.conns {
		if u := c.principal(); u != nil && u.ID == userID {
			conns = append(conns, c)
		}
	}
	return conns
}

// Route queues a pre-serialized frame for every subscriber except exclude.
// Enqueue never waits for socket I/O; a bounded-backlog overflow disconnects
// that client, without delaying subsequent Redis events or other rooms.
func (h *Hub) Route(topic string, payload []byte, exclude *Conn) {
	for _, c := range h.subscribers(topic, exclude) {
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
// anonymous connections subscribed to a topic. A subscription still catching
// up is not counted: it may not even be authorized yet.
func (h *Hub) presenceStats(topic string) ([]int64, int) {
	h.mu.RLock()
	seen := make(map[int64]struct{})
	anonymous := 0
	for c, live := range h.topics[topic] {
		if !live {
			continue
		}
		u := c.principal()
		if u == nil {
			anonymous++
			continue
		}
		seen[u.ID] = struct{}{}
	}
	h.mu.RUnlock()

	ids := make([]int64, 0, len(seen))
	for id := range seen {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	return ids, anonymous
}
