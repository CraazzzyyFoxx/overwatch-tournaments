package principal

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

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
