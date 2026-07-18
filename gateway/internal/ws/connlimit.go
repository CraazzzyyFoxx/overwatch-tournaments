package ws

import "sync"

// ipCounter tracks the number of concurrent connections per client IP so the
// handler can cap ANONYMOUS connections. /ws carries no auth and has no per-IP
// rate limiter in front of it (unlike /api/auth/*), so without a cap a single
// IP could open unbounded sockets. Authenticated connections are never counted
// here — they are bounded by the account, not the IP.
//
// A nil *ipCounter, or any call with max <= 0, is a no-op that always admits,
// so the cap can be disabled via config without a separate nil check.
type ipCounter struct {
	mu     sync.Mutex
	counts map[string]int
}

func newIPCounter() *ipCounter {
	return &ipCounter{counts: make(map[string]int)}
}

// acquire records one more connection for ip, returning false (WITHOUT
// recording) when that would exceed max. max <= 0 disables the cap.
func (c *ipCounter) acquire(ip string, max int) bool {
	if c == nil || max <= 0 {
		return true
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.counts[ip] >= max {
		return false
	}
	c.counts[ip]++
	return true
}

// release drops one connection for ip. max <= 0 is a no-op, mirroring acquire
// so callers pair the two under the same condition. The map entry is deleted at
// zero to bound memory under IP churn.
func (c *ipCounter) release(ip string, max int) {
	if c == nil || max <= 0 {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if n := c.counts[ip]; n <= 1 {
		delete(c.counts, ip)
	} else {
		c.counts[ip] = n - 1
	}
}
