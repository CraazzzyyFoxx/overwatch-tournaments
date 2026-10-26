package workspace

import (
	"container/list"
	"context"
	"fmt"
	"sync"
	"time"

	"golang.org/x/sync/singleflight"
)

// lookupTimeout caps one shared lookup query (see fill). The query outlives
// the caller that started it, so it cannot borrow that caller's cancellation;
// this bounds it instead, unless the caller's own deadline is sooner.
const lookupTimeout = 5 * time.Second

// ttlCache is a small concurrency-safe map cache with per-entry expiry and a
// bound on the number of live keys.
//
// An expired entry is dropped when read, and every insertion first reclaims
// all the expired ones, so the ttl frees memory rather than only hiding stale
// answers. At capacity, inserting a new key evicts the least-recently-set
// entry first (FIFO by set-order — see setLocked/evictOldestLocked below),
// mirroring the bounded-map + eviction pattern already used by
// internal/ratelimit.Limiter (maxKeys/purge): a key space that can be driven
// by client-chosen input must never be allowed to grow this map to an
// attacker-controlled size. Because every entry sharing one ttlCache instance
// has the same ttl, insertion order and expiry order coincide, so the expired
// entries are always a prefix of the list, and evicting the oldest-set entry
// never removes something "before its time" any more aggressively than the ttl
// itself would have.
type ttlCache[K comparable, V any] struct {
	mu         sync.Mutex
	ttl        time.Duration
	maxEntries int
	now        func() time.Time
	m          map[K]*list.Element // value: *cacheEntry[K, V]
	ll         *list.List          // front = oldest-set, back = most-recently-set
	// gen counts evictWhere and reset calls. A miss snapshots it (generation)
	// before its query and stores through setIfCurrent, so an answer read
	// before an eviction is never cached after it.
	gen    uint64
	flight singleflight.Group
}

type cacheEntry[K comparable, V any] struct {
	key K
	val V
	exp time.Time
}

// loaded is one fill result shared by every caller in its flight.
type loaded[V any] struct {
	val   V
	found bool
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

// fill answers a miss on k — callers check get first, so a hit builds no
// fetch closure — with fetch, run once for every concurrent miss of k
// (singleflight): a cold key that a reconnect herd subscribes to at once costs
// one query, not one per socket. The flight re-checks the cache, since a miss
// can race a flight that has just stored k, and stores through setIfCurrent.
// Its key carries the generation, so a lookup that starts after an eviction
// never joins (nor is answered by) a flight that started before it.
//
// fetch's found=false is returned but not cached (no such row); an error is
// returned and nothing is cached. The query runs on a context detached from
// the leading caller's cancellation — one caller leaving must not fail the
// others — and bounded by lookupTimeout or that caller's deadline, whichever
// is sooner; every caller still stops waiting when its own ctx is done.
func (c *ttlCache[K, V]) fill(ctx context.Context, k K, fetch func(context.Context) (V, bool, error)) (V, bool, error) {
	gen := c.generation()
	ch := c.flight.DoChan(fmt.Sprintf("%d:%#v", gen, k), func() (any, error) {
		if v, ok := c.get(k); ok {
			return loaded[V]{val: v, found: true}, nil
		}
		deadline := time.Now().Add(lookupTimeout)
		if d, ok := ctx.Deadline(); ok && d.Before(deadline) {
			deadline = d
		}
		qctx, cancel := context.WithDeadline(context.WithoutCancel(ctx), deadline)
		defer cancel()
		v, found, err := fetch(qctx)
		if err != nil {
			return nil, err
		}
		if found {
			c.setIfCurrent(k, v, gen)
		}
		return loaded[V]{val: v, found: found}, nil
	})
	select {
	case res := <-ch:
		if res.Err != nil {
			var zero V
			return zero, false, res.Err
		}
		l := res.Val.(loaded[V])
		return l.val, l.found, nil
	case <-ctx.Done():
		var zero V
		return zero, false, ctx.Err()
	}
}

// generation is the eviction count a miss must hand to setIfCurrent; read it
// BEFORE the query whose answer will be stored.
func (c *ttlCache[K, V]) generation() uint64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.gen
}

// setIfCurrent stores v for k, refreshing its expiry, unless evictWhere or
// reset ran since gen was read: that answer may predate the change the
// eviction announced, and the next lookup simply queries again. It caches
// whatever v is, including a "negative" result (e.g. verified=false).
func (c *ttlCache[K, V]) setIfCurrent(k K, v V, gen uint64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.gen == gen {
		c.setLocked(k, v)
	}
}

func (c *ttlCache[K, V]) setLocked(k K, v V) {
	now := c.now()
	// Reclaim the expired prefix (see ttlCache) before it can count against
	// maxEntries or linger until its own key is read again.
	for el := c.ll.Front(); el != nil && now.After(el.Value.(*cacheEntry[K, V]).exp); el = c.ll.Front() {
		c.removeLocked(el)
	}
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

// evictWhere drops every key match accepts and fences the misses already in
// flight (see gen). Used when the realtime bus announces that a whole family
// of answers changed (see Store.EvictUser, Store.InvalidateRoomAccess).
//
// ponytail: linear scan under the lock; key the cache by user if RBAC changes
// ever become frequent enough for it to show.
func (c *ttlCache[K, V]) evictWhere(match func(K) bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.gen++
	for el := c.ll.Front(); el != nil; {
		next := el.Next()
		if match(el.Value.(*cacheEntry[K, V]).key) {
			c.removeLocked(el)
		}
		el = next
	}
}

// reset drops every entry and fences every miss in flight, like an evictWhere
// matching everything (see Store.Reset).
func (c *ttlCache[K, V]) reset() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.gen++
	clear(c.m)
	c.ll.Init()
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
