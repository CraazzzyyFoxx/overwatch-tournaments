package principal

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
)

type stubCaller struct {
	reply []byte
	err   error
	calls int
}

func (s *stubCaller) Call(_ context.Context, _ string, _ []byte) ([]byte, error) {
	s.calls++
	return s.reply, s.err
}

func reqWithToken(tok string) *http.Request {
	r := httptest.NewRequest("GET", "/", nil)
	if tok != "" {
		r.Header.Set("Authorization", "Bearer "+tok)
	}
	return r
}

func TestResolver_NoToken(t *testing.T) {
	s := &stubCaller{}
	r := New(s)
	_, ok, err := r.Resolve(reqWithToken(""))
	if ok {
		t.Fatal("expected no identity without a token")
	}
	if err != nil {
		t.Fatalf("expected nil error for an anonymous request, got %v", err)
	}
	if s.calls != 0 {
		t.Fatalf("rpc must not be called, calls=%d", s.calls)
	}
}

// TestResolver_NoAuthorizationHeader asserts a request that never set the
// Authorization header (as opposed to an empty bearer value) is anonymous,
// never an error.
func TestResolver_NoAuthorizationHeader(t *testing.T) {
	s := &stubCaller{}
	r := New(s)
	req := httptest.NewRequest("GET", "/", nil)
	id, ok, err := r.Resolve(req)
	if id != nil || ok || err != nil {
		t.Fatalf("expected (nil, false, nil), got id=%v ok=%v err=%v", id, ok, err)
	}
	if s.calls != 0 {
		t.Fatalf("rpc must not be called, calls=%d", s.calls)
	}
}

func TestResolver_ValidTokenCached(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":9,"is_superuser":true}}`)}
	r := New(s)
	id, ok, err := r.Resolve(reqWithToken("abc"))
	if err != nil || !ok || id["user_id"].(float64) != 9 {
		t.Fatalf("resolve failed: ok=%v err=%v id=%v", ok, err, id)
	}
	// second call for the same token is served from cache (no extra RPC).
	if _, ok, err := r.Resolve(reqWithToken("abc")); !ok || err != nil {
		t.Fatalf("cached resolve failed: ok=%v err=%v", ok, err)
	}
	if s.calls != 1 {
		t.Fatalf("expected 1 rpc call (cached), got %d", s.calls)
	}
}

func TestResolver_InvalidTokenNegativeCached(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":false,"error":{"code":"unauthorized","message":"x"}}`)}
	r := New(s)
	if _, ok, err := r.Resolve(reqWithToken("bad")); ok || err != nil {
		t.Fatalf("expected invalid token to resolve false with no error: ok=%v err=%v", ok, err)
	}
	if _, _, err := r.Resolve(reqWithToken("bad")); err != nil {
		t.Fatalf("cached negative resolve returned an error: %v", err)
	}
	if s.calls != 1 {
		t.Fatalf("negative result should be cached, got %d calls", s.calls)
	}
}

// TestResolver_TransportFailureNotCached is the regression for the finding:
// a shed/disconnected/timed-out RPC call must surface as an error (so the
// caller can respond 503) and must NEVER be cached as ok=false — otherwise a
// single hiccup would keep a valid session "logged out" for cacheTTL.
func TestResolver_TransportFailureNotCached(t *testing.T) {
	s := &stubCaller{err: fmt.Errorf("rpc to %q: %w", "rpc.identity.validate_token", rpc.ErrOverloaded)}
	r := New(s)

	id, ok, err := r.Resolve(reqWithToken("tok"))
	if ok {
		t.Fatal("expected ok=false on transport failure")
	}
	if id != nil {
		t.Fatalf("expected nil identity on transport failure, got %v", id)
	}
	if err == nil {
		t.Fatal("expected a non-nil error on transport failure")
	}
	if s.calls != 1 {
		t.Fatalf("expected 1 rpc call, got %d", s.calls)
	}

	// identity-svc recovers: the same token must be re-validated against the
	// backend, not served from a poisoned negative cache entry.
	s.err = nil
	s.reply = []byte(`{"ok":true,"data":{"user_id":3}}`)
	id, ok, err = r.Resolve(reqWithToken("tok"))
	if err != nil || !ok || id["user_id"].(float64) != 3 {
		t.Fatalf("expected successful resolve after recovery: ok=%v err=%v id=%v", ok, err, id)
	}
	if s.calls != 2 {
		t.Fatalf("expected a second (uncached) rpc call after recovery, got %d", s.calls)
	}
}

// TestResolver_LRUEviction asserts the full cache evicts the least-recently-used
// token instead of dropping the whole map: recently-touched entries survive an
// overflow (a flood of one-off tokens no longer logs every active session out
// of the cache at once).
func TestResolver_LRUEviction(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":1}}`)}
	r := New(s)

	for i := range maxCacheEntries {
		if _, ok, err := r.Resolve(reqWithToken(fmt.Sprintf("t%d", i))); !ok || err != nil {
			t.Fatalf("resolve t%d failed: ok=%v err=%v", i, ok, err)
		}
	}
	if s.calls != maxCacheEntries {
		t.Fatalf("expected %d rpc calls, got %d", maxCacheEntries, s.calls)
	}

	// Touch t0 so it becomes the most recently used; t1 is now the LRU tail.
	if _, ok, err := r.Resolve(reqWithToken("t0")); !ok || err != nil {
		t.Fatalf("cached resolve t0 failed: ok=%v err=%v", ok, err)
	}
	if s.calls != maxCacheEntries {
		t.Fatalf("t0 must be served from cache, calls=%d", s.calls)
	}

	// Overflow by one: exactly the LRU entry (t1) is evicted.
	if _, ok, err := r.Resolve(reqWithToken("overflow")); !ok || err != nil {
		t.Fatalf("resolve overflow failed: ok=%v err=%v", ok, err)
	}
	if s.calls != maxCacheEntries+1 {
		t.Fatalf("expected %d rpc calls after overflow, got %d", maxCacheEntries+1, s.calls)
	}
	if _, ok, err := r.Resolve(reqWithToken("t0")); !ok || err != nil {
		t.Fatalf("t0 must survive the eviction: ok=%v err=%v", ok, err)
	}
	if s.calls != maxCacheEntries+1 {
		t.Fatalf("t0 must still be cached, calls=%d", s.calls)
	}
	if _, _, err := r.Resolve(reqWithToken("t1")); err != nil {
		t.Fatalf("resolve t1 failed: %v", err)
	}
	if s.calls != maxCacheEntries+2 {
		t.Fatalf("t1 must have been evicted (re-validated), calls=%d", s.calls)
	}
}

// gatedCaller blocks every Call until release is closed, counting calls
// atomically — used to hold several resolves in flight at once.
type gatedCaller struct {
	reply   []byte
	release chan struct{}
	calls   atomic.Int64
}

func (g *gatedCaller) Call(ctx context.Context, _ string, _ []byte) ([]byte, error) {
	g.calls.Add(1)
	select {
	case <-g.release:
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	return g.reply, nil
}

// TestResolver_ConcurrentMissesSingleflight asserts concurrent cache misses for
// the same token collapse into a single validate_token RPC instead of firing
// one per request (a page load fans out N API calls with the same bearer).
func TestResolver_ConcurrentMissesSingleflight(t *testing.T) {
	g := &gatedCaller{
		reply:   []byte(`{"ok":true,"data":{"user_id":7}}`),
		release: make(chan struct{}),
	}
	r := New(g)

	const workers = 8
	var wg sync.WaitGroup
	errs := make(chan error, workers)
	for range workers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			id, ok, err := r.Resolve(reqWithToken("shared"))
			if err != nil || !ok || id["user_id"].(float64) != 7 {
				errs <- fmt.Errorf("resolve: ok=%v err=%v id=%v", ok, err, id)
			}
		}()
	}

	// Wait until the flight leader is inside the RPC, give the followers time
	// to join the flight (the key stays active while the gate is held, so any
	// DoChan in this window merges), then let the leader finish.
	for g.calls.Load() == 0 {
		time.Sleep(time.Millisecond)
	}
	time.Sleep(100 * time.Millisecond)
	close(g.release)
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Fatal(err)
	}

	if n := g.calls.Load(); n != 1 {
		t.Fatalf("expected 1 rpc call for %d concurrent misses, got %d", workers, n)
	}
	// The result must be cached for followers too.
	if _, ok, err := r.Resolve(reqWithToken("shared")); !ok || err != nil {
		t.Fatalf("cached resolve failed: ok=%v err=%v", ok, err)
	}
	if n := g.calls.Load(); n != 1 {
		t.Fatalf("expected cached hit after flight, got %d calls", n)
	}
}
