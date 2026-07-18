package ws

import (
	"context"
	"log/slog"
	"sort"
	"sync"
	"time"

	"github.com/coder/websocket"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/safego"
)

const sendTimeout = 2 * time.Second

// Conn is a single live WebSocket connection and its subscription state.
type Conn struct {
	ws      *websocket.Conn
	user    *auth.User // nil => anonymous
	baseCtx context.Context
	log     *slog.Logger // request-scoped: carries correlation_id

	writeMu   sync.Mutex // serializes writes to the socket
	closeOnce sync.Once

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
	return &Conn{ws: c, user: user, baseCtx: ctx, log: log, topics: make(map[string]struct{})}
}

func (c *Conn) send(payload []byte) error {
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	ctx, cancel := context.WithTimeout(c.baseCtx, sendTimeout)
	defer cancel()
	return c.ws.Write(ctx, websocket.MessageText, payload)
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
	// Both the fan-out path (on send failure) and cleanup may close a
	// connection; sync.Once keeps it to a single underlying Close.
	c.closeOnce.Do(func() {
		_ = c.ws.Close(websocket.StatusNormalClosure, "")
	})
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

// CloseAll closes every live connection. Used on shutdown so clients receive a
// clean close and reconnect, rather than being left dangling (http.Server's
// Shutdown does not wait for hijacked WebSocket connections).
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

// Route delivers a pre-serialized frame to every connection subscribed to
// topic, except exclude. Failed sends drop the offending connection. Sends run
// concurrently so one slow client cannot stall fan-out to the others.
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

	if len(targets) == 0 {
		return
	}

	var wg sync.WaitGroup
	for _, c := range targets {
		wg.Add(1)
		// safego.Go recovers a panic in this per-target send (this runs for every
		// realtime message to every subscriber) so one bad connection cannot crash
		// the whole process. wg.Done is deferred inside so it fires even on panic.
		safego.Go(func() {
			defer wg.Done()
			if err := c.send(payload); err != nil {
				h.remove(c)
				c.close()
			}
		})
	}
	wg.Wait()
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
