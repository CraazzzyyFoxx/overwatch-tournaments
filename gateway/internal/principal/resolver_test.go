package principal

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
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
	if _, ok := r.Resolve(reqWithToken("")); ok {
		t.Fatal("expected no identity without a token")
	}
	if s.calls != 0 {
		t.Fatalf("rpc must not be called, calls=%d", s.calls)
	}
}

func TestResolver_ValidTokenCached(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":9,"is_superuser":true}}`)}
	r := New(s)
	id, ok := r.Resolve(reqWithToken("abc"))
	if !ok || id["user_id"].(float64) != 9 {
		t.Fatalf("resolve failed: ok=%v id=%v", ok, id)
	}
	// second call for the same token is served from cache (no extra RPC).
	if _, ok := r.Resolve(reqWithToken("abc")); !ok {
		t.Fatal("cached resolve failed")
	}
	if s.calls != 1 {
		t.Fatalf("expected 1 rpc call (cached), got %d", s.calls)
	}
}

func TestResolver_InvalidTokenNegativeCached(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":false,"error":{"code":"unauthorized","message":"x"}}`)}
	r := New(s)
	if _, ok := r.Resolve(reqWithToken("bad")); ok {
		t.Fatal("expected invalid token to resolve false")
	}
	_, _ = r.Resolve(reqWithToken("bad"))
	if s.calls != 1 {
		t.Fatalf("negative result should be cached, got %d calls", s.calls)
	}
}
