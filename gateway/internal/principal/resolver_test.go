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

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
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

// apiKeyReply is the shape identity-svc's validate_token returns for an
// owt_sk_ credential: the owner's user id, credential_type=api_key, the key's
// own limits, and exactly one workspace entry carrying the scope intersection.
const apiKeyReply = `{"ok":true,"data":{
	"sub":42,"credential_type":"api_key","is_superuser":false,
	"roles":[],"permissions":[],
	"api_key":{"id":7,"public_id":"pub7","workspace_id":11,
		"scopes":["team.create"],
		"limits":{"requests_per_minute":25,"jobs_per_day":100}},
	"workspaces":[{"workspace_id":11,"slug":"ws","rbac_roles":[],
		"rbac_permissions":[{"resource":"team","action":"create"}]}]
}}`

// TestResolver_PrincipalTypedView asserts the typed view is parsed from the
// payload the identity service actually sends (user id under "sub", limits
// nested under api_key) and that it rides the SAME cache entry as Resolve — one
// validate_token serves both views.
func TestResolver_PrincipalTypedView(t *testing.T) {
	s := &stubCaller{reply: []byte(apiKeyReply)}
	r := New(s)

	info, ok, err := r.Principal(reqWithToken("owt_sk_pub7_secret"))
	if err != nil || !ok {
		t.Fatalf("principal failed: ok=%v err=%v", ok, err)
	}
	if !info.IsAPIKey() {
		t.Errorf("credential_type=%q should read as an api key", info.CredentialType)
	}
	if info.UserID != 42 {
		t.Errorf("UserID: want the owner 42, got %d", info.UserID)
	}
	if info.APIKeyID != 7 || info.APIKeyPublicID != "pub7" {
		t.Errorf("key identity: want 7/pub7, got %d/%q", info.APIKeyID, info.APIKeyPublicID)
	}
	if info.RequestsPerMinute != 25 {
		t.Errorf("RequestsPerMinute: want the key's own 25, got %d", info.RequestsPerMinute)
	}
	if info.WorkspaceGrants != 1 {
		t.Errorf("WorkspaceGrants: want 1, got %d", info.WorkspaceGrants)
	}

	// Resolve for the same token is served from the entry Principal populated.
	payload, ok, err := r.Resolve(reqWithToken("owt_sk_pub7_secret"))
	if err != nil || !ok || payload["credential_type"] != "api_key" {
		t.Fatalf("resolve after principal: ok=%v err=%v payload=%v", ok, err, payload)
	}
	if s.calls != 1 {
		t.Fatalf("both views must share one validate_token, got %d calls", s.calls)
	}
}

// TestResolver_PrincipalSessionHasNoKeyFields guards the session path: an
// access-token payload must yield no api-key identity (so nothing downstream
// mistakes a session for a key) while still exposing its user id and grants.
func TestResolver_PrincipalSessionHasNoKeyFields(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":9,"is_superuser":true,
		"credential_type":"access_token",
		"workspaces":[{"workspace_id":1,"rbac_permissions":[{"resource":"team","action":"create"},
			{"resource":"team","action":"update"}]}]}}`)}
	r := New(s)

	info, ok, err := r.Principal(reqWithToken("session.jwt.token"))
	if err != nil || !ok {
		t.Fatalf("principal failed: ok=%v err=%v", ok, err)
	}
	if info.IsAPIKey() || info.APIKeyID != 0 || info.RequestsPerMinute != 0 {
		t.Errorf("session must carry no key identity, got %+v", info)
	}
	if info.UserID != 9 || info.WorkspaceGrants != 2 {
		t.Errorf("want user 9 with 2 grants, got %+v", info)
	}
}

// TestResolver_APIKeyCachedShorterThanSession is the whole point of
// apiKeyCacheTTL: a key is long-lived and revocation is the only way to stop
// it, so its verdict must go stale much sooner than a self-expiring session's.
func TestResolver_APIKeyCachedShorterThanSession(t *testing.T) {
	s := &stubCaller{reply: []byte(apiKeyReply)}
	r := New(s)
	now := time.Now()
	r.now = func() time.Time { return now }

	if _, ok, _ := r.Principal(reqWithToken("owt_sk_pub7_secret")); !ok {
		t.Fatal("first api-key resolve failed")
	}
	if _, ok, _ := r.Resolve(reqWithToken("session.jwt.token")); !ok {
		t.Fatal("first session resolve failed")
	}
	if s.calls != 2 {
		t.Fatalf("want 2 rpc calls, got %d", s.calls)
	}

	// Past the api-key TTL but well inside the session TTL: the key is
	// re-validated, the session is not.
	now = now.Add(apiKeyCacheTTL + time.Second)
	if _, ok, _ := r.Principal(reqWithToken("owt_sk_pub7_secret")); !ok {
		t.Fatal("api-key re-resolve failed")
	}
	if s.calls != 3 {
		t.Fatalf("api key must be re-validated after apiKeyCacheTTL, calls=%d", s.calls)
	}
	if _, ok, _ := r.Resolve(reqWithToken("session.jwt.token")); !ok {
		t.Fatal("session resolve failed")
	}
	if s.calls != 3 {
		t.Fatalf("session must still be cached at %v, calls=%d", apiKeyCacheTTL, s.calls)
	}

	// And the session does expire at its own, longer TTL.
	now = now.Add(cacheTTL)
	if _, ok, _ := r.Resolve(reqWithToken("session.jwt.token")); !ok {
		t.Fatal("session re-resolve failed")
	}
	if s.calls != 4 {
		t.Fatalf("session must be re-validated after cacheTTL, calls=%d", s.calls)
	}
}

// TestResolver_APIKeyQuota_SkipsNonKeyTraffic is the cost guarantee behind
// wrapping the whole API mux with the per-key limiter: anything that is not an
// API-key credential is answered from the local prefix test alone, with no
// validate_token call added to session or anonymous traffic.
func TestResolver_APIKeyQuota_SkipsNonKeyTraffic(t *testing.T) {
	s := &stubCaller{reply: []byte(apiKeyReply)}
	r := New(s)

	for _, tok := range []string{"", "session.jwt.token"} {
		if key, rpm, ok := r.APIKeyQuota(reqWithToken(tok)); ok {
			t.Errorf("token %q must not be metered as a key, got %q/%d", tok, key, rpm)
		}
	}
	if s.calls != 0 {
		t.Fatalf("non-key traffic must cost no rpc, got %d calls", s.calls)
	}

	key, rpm, ok := r.APIKeyQuota(reqWithToken("owt_sk_pub7_secret"))
	if !ok || key != "7" || rpm != 25 {
		t.Fatalf("want bucket 7 with the key's own 25/min, got %q/%d ok=%v", key, rpm, ok)
	}
	// Keys minted before the rebrand are metered the same way.
	if key, _, ok := r.APIKeyQuota(reqWithToken("aqt_sk_pub7_secret")); !ok || key != "7" {
		t.Fatalf("a legacy aqt_sk_ key must be metered too, got %q ok=%v", key, ok)
	}
}

// TestResolver_APIKeyQuota_BackendDownDoesNotThrottle: an unavailable identity
// service must not turn into a 429. The route behind the limiter resolves the
// same token and answers 503, which is the honest failure.
func TestResolver_APIKeyQuota_BackendDownDoesNotThrottle(t *testing.T) {
	s := &stubCaller{err: rpc.ErrOverloaded}
	r := New(s)
	if _, _, ok := r.APIKeyQuota(reqWithToken("owt_sk_pub7_secret")); ok {
		t.Fatal("a resolver error must report ok=false, not a throttling verdict")
	}
}

// The match-log download is an `<a download>` link the browser navigates to, so
// no script can attach an Authorization header. Without the cookie fallback the
// route would 401 every signed-in user.
func TestResolver_ResolveWithSessionCookie_FallsBackToTheCookie(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":9}}`)}
	r := New(s)

	req := httptest.NewRequest("GET", "/api/v1/matches/7/log", nil)
	req.AddCookie(&http.Cookie{Name: auth.CookieName, Value: "cookie-token"})

	id, ok, err := r.ResolveWithSessionCookie(req)
	if err != nil || !ok || id["user_id"] != float64(9) {
		t.Fatalf("want the cookie identity, got id=%v ok=%v err=%v", id, ok, err)
	}
}

// The header stays authoritative: an API-key client hitting the same download
// must be judged on its key, never on a cookie the browser happened to send.
func TestResolver_ResolveWithSessionCookie_PrefersTheHeader(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":9}}`)}
	r := New(s)

	req := reqWithToken("header-token")
	req.AddCookie(&http.Cookie{Name: auth.CookieName, Value: "cookie-token"})
	if _, ok, _ := r.ResolveWithSessionCookie(req); !ok {
		t.Fatal("expected the header credential to resolve")
	}

	// Same entry, so a second call on the header token alone is a cache hit:
	// proof the header — not the cookie — was the token that got validated.
	if _, ok, _ := r.Resolve(reqWithToken("header-token")); !ok {
		t.Fatal("expected the header token to be the cached one")
	}
	if s.calls != 1 {
		t.Fatalf("calls = %d, want 1 (the cookie must not be validated too)", s.calls)
	}
}

// Plain Resolve must stay header-only: widening it would put a cookie
// credential behind every mutating REST route, which is a CSRF surface.
func TestResolver_ResolveIgnoresTheSessionCookie(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":9}}`)}
	r := New(s)

	req := httptest.NewRequest("POST", "/api/v1/tournaments", nil)
	req.AddCookie(&http.Cookie{Name: auth.CookieName, Value: "cookie-token"})

	if _, ok, _ := r.Resolve(req); ok {
		t.Fatal("Resolve must not authenticate from a cookie")
	}
	if s.calls != 0 {
		t.Fatalf("rpc must not be called, calls=%d", s.calls)
	}
}
