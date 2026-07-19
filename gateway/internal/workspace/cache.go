package workspace

import (
	"container/list"
	"sync"
	"time"
)

// ttlCache is a small concurrency-safe map cache with per-entry expiry and an
// optional bound on the number of live keys.
//
// Entries expire lazily on access. When maxEntries > 0 and the cache is at
// capacity, inserting a new key evicts the least-recently-set entry first
// (FIFO by set-order — see set/evictOldestLocked below), mirroring the
// bounded-map + eviction pattern already used by
// internal/ratelimit.Limiter (maxKeys/purge): a key space that can be driven
// by fully unauthenticated, attacker-chosen input must never be allowed to
// grow this map to an attacker-controlled size. Because every entry sharing
// one ttlCache instance has the same ttl, insertion order and expiry order
// coincide, so evicting the oldest-set entry never removes something
// "before its time" any more aggressively than the ttl itself would have.
//
// maxEntries == 0 (the zero value, via newTTLCache) means unbounded — today's
// behaviour for the tournament/membership caches, whose key space is
// operator-controlled (tournament IDs, user IDs), not attacker-controlled.
type ttlCache[K comparable, V any] struct {
	mu         sync.Mutex
	ttl        time.Duration
	maxEntries int
	now        func() time.Time
	m          map[K]*list.Element // value: *cacheEntry[K, V]
	ll         *list.List          // front = oldest-set, back = most-recently-set
}

type cacheEntry[K comparable, V any] struct {
	key K
	val V
	exp time.Time
}

// newTTLCache returns an unbounded cache, preserving the existing behaviour
// for callers that don't face an attacker-controlled key space.
func newTTLCache[K comparable, V any](ttl time.Duration) *ttlCache[K, V] {
	return newBoundedTTLCache[K, V](ttl, 0)
}

// newBoundedTTLCache returns a cache capped at maxEntries live keys. A
// maxEntries <= 0 means unbounded.
func newBoundedTTLCache[K comparable, V any](ttl time.Duration, maxEntries int) *ttlCache[K, V] {
	return &ttlCache[K, V]{
		ttl:        ttl,
		maxEntries: maxEntries,
		now:        time.Now,
		m:          make(map[K]*list.Element),
		ll:         list.New(),
	}
}

func (c *ttlCache[K, V]) get(k K) (V, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	el, ok := c.m[k]
	if !ok {
		var zero V
		return zero, false
	}
	ent := el.Value.(*cacheEntry[K, V])
	if c.now().After(ent.exp) {
		c.removeLocked(el)
		var zero V
		return zero, false
	}
	return ent.val, true
}

// set stores v for k, refreshing its expiry. This caches whatever v is,
// including a "negative" result (e.g. verified=false) — the caller decides
// what's cacheable by choosing whether to call set at all (see
// Store.IsVerifiedCustomDomain, which never calls set on a lookup error).
func (c *ttlCache[K, V]) set(k K, v V) {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := c.now()
	if el, ok := c.m[k]; ok {
		ent := el.Value.(*cacheEntry[K, V])
		ent.val = v
		ent.exp = now.Add(c.ttl)
		c.ll.MoveToBack(el) // refreshing a key protects it from being the next eviction target.
		return
	}
	if c.maxEntries > 0 && len(c.m) >= c.maxEntries {
		c.evictOldestLocked()
	}
	ent := &cacheEntry[K, V]{key: k, val: v, exp: now.Add(c.ttl)}
	el := c.ll.PushBack(ent)
	c.m[k] = el
}

// evictOldestLocked drops the least-recently-set entry. Caller holds c.mu.
func (c *ttlCache[K, V]) evictOldestLocked() {
	if front := c.ll.Front(); front != nil {
		c.removeLocked(front)
	}
}

// removeLocked drops el from both the map and the list. Caller holds c.mu.
func (c *ttlCache[K, V]) removeLocked(el *list.Element) {
	ent := el.Value.(*cacheEntry[K, V])
	delete(c.m, ent.key)
	c.ll.Remove(el)
}
