package workspace

import (
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
