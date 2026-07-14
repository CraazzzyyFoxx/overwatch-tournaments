package rpc

import "sync"

// limiter is a per-queue in-flight cap (bulkhead). One saturated queue rejects
// further calls to itself without affecting other queues. max <= 0 disables
// the cap entirely.
type limiter struct {
	max int
	mu  sync.Mutex
	n   map[string]int
}

func newLimiter(max int) *limiter {
	return &limiter{max: max, n: make(map[string]int)}
}

// acquire reserves an in-flight slot for queue. It reports false when the
// queue is at capacity — the caller should shed the request immediately
// instead of adding it to the broker backlog.
func (l *limiter) acquire(queue string) bool {
	if l.max <= 0 {
		return true
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.n[queue] >= l.max {
		return false
	}
	l.n[queue]++
	return true
}

// release frees a slot previously acquired for queue.
func (l *limiter) release(queue string) {
	if l.max <= 0 {
		return
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.n[queue] <= 1 {
		delete(l.n, queue)
	} else {
		l.n[queue]--
	}
}
