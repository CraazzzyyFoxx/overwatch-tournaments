package workspace

import (
	"sync"
	"time"
)

// ttlCache is a small concurrency-safe map cache with per-entry expiry.
//
// Entries expire lazily on access; an entry that is never read again lingers
// until process restart. The cardinality here (tournaments, workspace
// memberships) is small, so this is acceptable for Phase 0.
// TODO: add a periodic sweep or a size bound if the key space grows.
type ttlCache[K comparable, V any] struct {
	mu  sync.Mutex
	ttl time.Duration
	now func() time.Time
	m   map[K]entry[V]
}

type entry[V any] struct {
	val V
	exp time.Time
}

func newTTLCache[K comparable, V any](ttl time.Duration) *ttlCache[K, V] {
	return &ttlCache[K, V]{ttl: ttl, now: time.Now, m: make(map[K]entry[V])}
}

func (c *ttlCache[K, V]) get(k K) (V, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.m[k]
	if !ok || c.now().After(e.exp) {
		if ok {
			delete(c.m, k)
		}
		var zero V
		return zero, false
	}
	return e.val, true
}

func (c *ttlCache[K, V]) set(k K, v V) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.m[k] = entry[V]{val: v, exp: c.now().Add(c.ttl)}
}
