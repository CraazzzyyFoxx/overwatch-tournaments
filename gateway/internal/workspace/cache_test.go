package workspace

import (
	"fmt"
	"testing"
	"time"
)

func TestTTLCache(t *testing.T) {
	c := newTTLCache[int64, int64](time.Minute)
	clock := time.Unix(1000, 0)
	c.now = func() time.Time { return clock }

	if _, ok := c.get(1); ok {
		t.Fatal("empty cache should miss")
	}

	c.set(1, 42)
	if v, ok := c.get(1); !ok || v != 42 {
		t.Fatalf("expected hit 42, got %d ok=%v", v, ok)
	}

	// Still fresh just before expiry.
	clock = clock.Add(59 * time.Second)
	if _, ok := c.get(1); !ok {
		t.Fatal("entry should still be fresh")
	}

	// Expired after TTL.
	clock = clock.Add(2 * time.Second)
	if _, ok := c.get(1); ok {
		t.Fatal("entry should have expired")
	}
}

// TestTTLCache_UnboundedByDefault pins today's behaviour for the existing
// (operator-controlled key space) callers: newTTLCache never evicts on its
// own, however many distinct keys are inserted.
func TestTTLCache_UnboundedByDefault(t *testing.T) {
	c := newTTLCache[int, bool](time.Minute)
	for i := 0; i < 10_000; i++ {
		c.set(i, i%2 == 0)
	}
	for i := 0; i < 10_000; i++ {
		v, ok := c.get(i)
		if !ok {
			t.Fatalf("key %d: expected a hit in an unbounded cache, got a miss", i)
		}
		if v != (i%2 == 0) {
			t.Fatalf("key %d: got %v, want %v", i, v, i%2 == 0)
		}
	}
}

// TestBoundedTTLCache_EvictsOldestOnOverflow proves the cardinality guard
// that closes the availability hole in ws.Handler's custom-domain Origin
// lookup: once a bounded cache is at capacity, inserting a new key evicts
// the least-recently-set entry (FIFO), never growing past maxEntries live
// keys — a flood of distinct attacker-chosen keys cannot inflate the map
// without bound.
func TestBoundedTTLCache_EvictsOldestOnOverflow(t *testing.T) {
	const maxEntries = 3
	c := newBoundedTTLCache[string, bool](time.Minute, maxEntries)

	c.set("a", true)
	c.set("b", true)
	c.set("c", true)
	if got := len(c.m); got != maxEntries {
		t.Fatalf("after filling to capacity: len(m) = %d, want %d", got, maxEntries)
	}

	// "d" overflows the cache: "a" (oldest-set) must be evicted, and the
	// live-key count must never exceed maxEntries.
	c.set("d", true)
	if got := len(c.m); got != maxEntries {
		t.Fatalf("after overflow: len(m) = %d, want %d (still bounded)", got, maxEntries)
	}
	if _, ok := c.get("a"); ok {
		t.Fatal(`"a" should have been evicted as the oldest entry`)
	}
	for _, k := range []string{"b", "c", "d"} {
		if _, ok := c.get(k); !ok {
			t.Fatalf("%q should still be cached", k)
		}
	}

	// Flooding with many more distinct keys must never grow the cache past
	// maxEntries — this is the direct regression test for the
	// distinct-Origin-host flood described in the CSWSH/DoS review.
	for i := 0; i < 1000; i++ {
		c.set(fmt.Sprintf("flood-%d", i), true)
	}
	if got := len(c.m); got != maxEntries {
		t.Fatalf("after a 1000-key flood: len(m) = %d, want %d (bound violated)", got, maxEntries)
	}
}

// TestBoundedTTLCache_RefreshProtectsFromEviction proves that a key which
// keeps getting legitimately refreshed (a real, actively-used custom domain)
// is moved to the back of the eviction order on each set, so it is NOT the
// eviction target while a colder entry is — a flood of new distinct keys
// evicts itself before it evicts something still in active use.
func TestBoundedTTLCache_RefreshProtectsFromEviction(t *testing.T) {
	const maxEntries = 3
	c := newBoundedTTLCache[string, bool](time.Minute, maxEntries)

	c.set("hot", true)
	c.set("b", true)
	c.set("c", true) // cache at capacity: order is hot, b, c (oldest -> newest)

	c.set("hot", true) // refresh: moves "hot" to the back -> order is b, c, hot

	c.set("d", true) // overflow: evicts "b" (now the oldest), not "hot"

	if _, ok := c.get("hot"); !ok {
		t.Fatal(`"hot" was refreshed and should have survived the overflow eviction`)
	}
	if _, ok := c.get("b"); ok {
		t.Fatal(`"b" should have been evicted (it was the oldest after "hot" was refreshed)`)
	}
}

// TestBoundedTTLCache_CachesNegativeResultsLikePositiveOnes proves the cache
// itself treats a cached "false" (e.g. host-not-verified) exactly like a
// cached "true": a single set is enough to make subsequent get calls hit,
// with no special-casing of the boolean value. This is the low-level
// building block behind Store.IsVerifiedCustomDomain's negative caching
// (verified=false is cached exactly like verified=true — see its doc
// comment) — a flood of lookups for the SAME unverified host costs at most
// one query per TTL, identically to a verified one.
func TestBoundedTTLCache_CachesNegativeResultsLikePositiveOnes(t *testing.T) {
	c := newBoundedTTLCache[string, bool](time.Minute, 8)

	c.set("verified.example.com", true)
	c.set("not-verified.example.com", false)

	v, ok := c.get("verified.example.com")
	if !ok || !v {
		t.Fatalf("verified.example.com: got (%v, %v), want (true, true)", v, ok)
	}

	v, ok = c.get("not-verified.example.com")
	if !ok || v {
		t.Fatalf("not-verified.example.com: got (%v, %v), want (false, true) — a cached negative result", v, ok)
	}
}
