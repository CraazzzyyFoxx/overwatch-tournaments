package rpc

import "testing"

func TestLimiter_CapsPerQueue(t *testing.T) {
	l := newLimiter(2)
	if !l.acquire("q1") || !l.acquire("q1") {
		t.Fatal("first two acquires must succeed")
	}
	if l.acquire("q1") {
		t.Fatal("third acquire must be rejected at cap 2")
	}
	if !l.acquire("q2") {
		t.Fatal("other queues must not be affected by q1 saturation")
	}
	l.release("q1")
	if !l.acquire("q1") {
		t.Fatal("acquire after release must succeed")
	}
}

func TestLimiter_ZeroMeansUnlimited(t *testing.T) {
	l := newLimiter(0)
	for i := 0; i < 1000; i++ {
		if !l.acquire("q") {
			t.Fatal("max=0 must never reject")
		}
	}
}

func TestLimiter_ReleaseCleansUpMap(t *testing.T) {
	l := newLimiter(3)
	l.acquire("q")
	l.release("q")
	l.mu.Lock()
	_, exists := l.n["q"]
	l.mu.Unlock()
	if exists {
		t.Fatal("fully released queue must be removed from the map (no unbounded growth)")
	}
}
