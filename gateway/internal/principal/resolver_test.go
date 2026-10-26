package principal

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth/authtest"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/ratelimit"
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

func newResolver(c RPCCaller) *Resolver {
	return New(c, auth.New(authtest.PublicKey))
}

// creds maps the short names the tests use to real credentials that pass the
// resolver's local precheck: a name with an API-key prefix becomes a
// well-formed key, any other a valid access token. Distinct names stay
// distinct credentials (cache entries); a name always maps to the same one.
var creds sync.Map

func cred(name string) string {
	if c, ok := creds.Load(name); ok {
		return c.(string)
	}
	c := authtest.Token("1")
	if auth.IsAPIKey(name) {
		sum := sha256.Sum256([]byte(name))
		secret := hex.EncodeToString(sum[:])
		c = name[:len(auth.APIKeyPrefix)] + secret[:16] + "_" + secret
	}
	stored, _ := creds.LoadOrStore(name, c)
	return stored.(string)
}

// reqWithToken is a request bearing the credential cred(name); "" is none.
func reqWithToken(name string) *http.Request {
	if name == "" {
		return rawReq("")
	}
	return rawReq(cred(name))
}

// rawReq is a request bearing token verbatim.
func rawReq(token string) *http.Request {
	r := httptest.NewRequest("GET", "/", nil)
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	return r
}

// A credential that cannot possibly validate is refused locally: no
// validate_token and no cache entry, so junk neither reaches identity-svc nor
// evicts live sessions from the LRU.
func TestResolver_PrecheckRefusesWithoutRPC(t *testing.T) {
	_, otherKey, _ := ed25519.GenerateKey(nil)
	forged, _ := jwt.NewWithClaims(jwt.SigningMethodEdDSA, authtest.Claims("9")).SignedString(otherKey)
	expired := authtest.Claims("9")
	expired["exp"] = time.Now().Add(-time.Minute).Unix()
	wrongAud := authtest.Claims("9")
	wrongAud["aud"] = "other"

	for name, token := range map[string]string{
		"forged":        forged,
		"expired":       authtest.Sign(expired),
		"wrong aud":     authtest.Sign(wrongAud),
		"malformed":     "not.a.jwt",
		"malformed key": "owt_sk_pub_secret",
		"short key":     "aqt_sk_0123456789abcdef_0123",
	} {
		s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":9}}`)}
		r := newResolver(s)
		if _, ok, err := r.Resolve(rawReq(token)); ok || err != nil {
			t.Errorf("%s: want (false, nil), got ok=%v err=%v", name, ok, err)
		}
		if _, ok, err := r.PrincipalToken(context.Background(), token); ok || err != nil {
			t.Errorf("%s: PrincipalToken want (false, nil), got ok=%v err=%v", name, ok, err)
		}
		if s.calls != 0 || len(r.cache) != 0 {
			t.Errorf("%s: want no rpc and no cache entry, got calls=%d entries=%d", name, s.calls, len(r.cache))
		}
	}
}

func TestResolver_NoToken(t *testing.T) {
	s := &stubCaller{}
	r := newResolver(s)
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
	r := newResolver(s)
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
	r := newResolver(s)
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

// Only identity-svc's verdicts on the credential itself are cached as
// ok=false (see TestResolver_OperationalErrorIsNotAVerdict for the rest).
func TestResolver_InvalidTokenNegativeCached(t *testing.T) {
	for _, code := range []string{"unauthorized", "forbidden", "bad_request"} {
		s := &stubCaller{reply: []byte(`{"ok":false,"error":{"code":"` + code + `","message":"x"}}`)}
		r := newResolver(s)
		if _, ok, err := r.Resolve(reqWithToken("bad")); ok || err != nil {
			t.Fatalf("%s: expected invalid token to resolve false with no error: ok=%v err=%v", code, ok, err)
		}
		if _, _, err := r.Resolve(reqWithToken("bad")); err != nil {
			t.Fatalf("%s: cached negative resolve returned an error: %v", code, err)
		}
		if s.calls != 1 {
			t.Fatalf("%s: negative result should be cached, got %d calls", code, s.calls)
		}
	}
}

// The dispatcher injects the payload exactly as identity-svc sent it, from the
// cache: no decode/re-marshal round trip (which also rounded ids past 2^53).
func TestResolver_IdentityKeepsRawPayload(t *testing.T) {
	data := `{"user_id":9,"big":12345678901234567890,"workspaces":[{"workspace_id":11}]}`
	s := &stubCaller{reply: []byte(`{"ok":true,"data":` + data + `}`)}
	r := newResolver(s)
	for range 2 {
		id, ok, err := r.Identity(reqWithToken("session"))
		if err != nil || !ok || !bytes.Equal(id.Payload, []byte(data)) || id.SoleWorkspaceID != 11 {
			t.Fatalf("want the verbatim payload pinned to workspace 11, got %s/%d ok=%v err=%v", id.Payload, id.SoleWorkspaceID, ok, err)
		}
	}
	if s.calls != 1 {
		t.Fatalf("the second Identity must be a cache hit, calls=%d", s.calls)
	}
	if id, ok, err := newResolver(s).Identity(rawReq("not.a.jwt")); ok || err != nil || id.Payload != nil {
		t.Fatalf("a refused token carries no identity, got %s ok=%v err=%v", id.Payload, ok, err)
	}
}

// TestResolver_OperationalErrorIsNotAVerdict: identity-svc answers a bad token
// with "unauthorized" and nothing else. Any other failure — a DB hiccup's
// "internal", "unavailable", a reply that does not parse — says nothing about
// the token, so it must surface as an error (503) and stay uncached. It used to
// be stored as ok=false, logging valid sessions out for the whole TTL.
func TestResolver_OperationalErrorIsNotAVerdict(t *testing.T) {
	for _, reply := range []string{
		`{"ok":false,"error":{"code":"internal","message":"internal error"}}`,
		`{"ok":false,"error":{"code":"unavailable","message":"x"}}`,
		`{"ok":false}`,
		`{"ok":true,"data":null}`,
		`not json`,
	} {
		s := &stubCaller{reply: []byte(reply)}
		r := newResolver(s)
		if _, ok, err := r.Resolve(reqWithToken("tok")); ok || err == nil {
			t.Errorf("%s: want an error, got ok=%v err=%v", reply, ok, err)
		}
		s.reply = []byte(`{"ok":true,"data":{"user_id":3}}`)
		if _, ok, err := r.Resolve(reqWithToken("tok")); !ok || err != nil || s.calls != 2 {
			t.Errorf("%s: the failure must not be cached: ok=%v err=%v calls=%d", reply, ok, err, s.calls)
		}
	}
}

// TestResolver_SessionCacheEndsAtTokenExpiry: a verdict must not outlive the
// token. A hit is never re-checked and the workers do not look at exp, so a
// token validated just before it expired used to stay authorized for most of
// cacheTTL.
func TestResolver_SessionCacheEndsAtTokenExpiry(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":9}}`)}
	r := newResolver(s)
	// The token must pass the precheck by the wall clock, so the resolver's
	// own clock starts 10s before an exp an hour away.
	exp := time.Now().Add(time.Hour).Truncate(time.Second)
	now := exp.Add(-10 * time.Second)
	r.now = func() time.Time { return now }
	claims := authtest.Claims("9")
	claims["exp"] = exp.Unix()
	tok := authtest.Sign(claims)
	resolve := func() {
		t.Helper()
		if _, ok, err := r.Resolve(rawReq(tok)); !ok || err != nil {
			t.Fatalf("resolve: ok=%v err=%v", ok, err)
		}
	}

	resolve()
	now = now.Add(9 * time.Second)
	resolve()
	if s.calls != 1 {
		t.Fatalf("before exp the verdict is a cache hit, calls=%d", s.calls)
	}
	now = now.Add(time.Second) // exactly exp, still well inside cacheTTL
	resolve()
	if s.calls != 2 {
		t.Fatalf("at the token's exp the cached verdict must not be served, calls=%d", s.calls)
	}
}

// TestResolver_TransportFailureNotCached is the regression for the finding:
// a shed/disconnected/timed-out RPC call must surface as an error (so the
// caller can respond 503) and must NEVER be cached as ok=false — otherwise a
// single hiccup would keep a valid session "logged out" for cacheTTL.
func TestResolver_TransportFailureNotCached(t *testing.T) {
	s := &stubCaller{err: fmt.Errorf("rpc to %q: %w", "rpc.identity.validate_token", rpc.ErrOverloaded)}
	r := newResolver(s)

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
	r := newResolver(s)

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
	r := newResolver(g)

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
	r := newResolver(s)

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

// TestResolver_PrincipalAttributionFields covers the three fields edge quota
// metering attributes a request with: the workspace a key is pinned to, every
// workspace a session belongs to (stringly-typed ids included — the payload has
// historically carried both shapes), and the superuser flag that lets an
// operator be metered against a tenant it is not a member of.
func TestResolver_PrincipalAttributionFields(t *testing.T) {
	key := newResolver(&stubCaller{reply: []byte(apiKeyReply)})
	info, ok, err := key.Principal(reqWithToken("owt_sk_pub7_secret"))
	if err != nil || !ok {
		t.Fatalf("principal failed: ok=%v err=%v", ok, err)
	}
	if info.APIKeyWorkspaceID != 11 {
		t.Errorf("APIKeyWorkspaceID: want the key's workspace 11, got %d", info.APIKeyWorkspaceID)
	}
	if len(info.WorkspaceIDs) != 1 || info.WorkspaceIDs[0] != 11 {
		t.Errorf("WorkspaceIDs: want [11], got %v", info.WorkspaceIDs)
	}
	if info.IsSuperuser {
		t.Errorf("is_superuser=false must not read as a superuser")
	}

	su := newResolver(&stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":9,"is_superuser":true,
		"credential_type":"access_token",
		"workspaces":[{"workspace_id":3},{"workspace_id":"4"},{"slug":"no-id"}]}}`)})
	info, ok, err = su.Principal(reqWithToken("session"))
	if err != nil || !ok {
		t.Fatalf("principal failed: ok=%v err=%v", ok, err)
	}
	if !info.IsSuperuser {
		t.Errorf("is_superuser=true must be parsed")
	}
	if len(info.WorkspaceIDs) != 2 || info.WorkspaceIDs[0] != 3 || info.WorkspaceIDs[1] != 4 {
		t.Errorf("WorkspaceIDs: want [3 4] (a string id parsed, an id-less entry skipped), got %v", info.WorkspaceIDs)
	}
	if info.APIKeyWorkspaceID != 0 {
		t.Errorf("a session carries no key workspace, got %d", info.APIKeyWorkspaceID)
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
	r := newResolver(s)

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
	r := newResolver(s)
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
	r := newResolver(s)

	for _, tok := range []string{"", "session.jwt.token"} {
		if key, rpm, err := r.APIKeyQuota(reqWithToken(tok)); key != "" || err != nil {
			t.Errorf("token %q must not be metered as a key, got %q/%d err=%v", tok, key, rpm, err)
		}
	}
	if s.calls != 0 {
		t.Fatalf("non-key traffic must cost no rpc, got %d calls", s.calls)
	}

	key, rpm, err := r.APIKeyQuota(reqWithToken("owt_sk_pub7_secret"))
	if err != nil || key != "7" || rpm != 25 {
		t.Fatalf("want bucket 7 with the key's own 25/min, got %q/%d err=%v", key, rpm, err)
	}
	// Keys minted before the rebrand are metered the same way.
	if key, _, err := r.APIKeyQuota(reqWithToken("aqt_sk_pub7_secret")); err != nil || key != "7" {
		t.Fatalf("a legacy aqt_sk_ key must be metered too, got %q err=%v", key, err)
	}
}

// TestResolver_APIKeyQuota_IdentityFailuresStopAtTheLimiter wires APIKeyQuota
// into the per-key limiter in front of a route that resolves the same token,
// as main does. A rejected key is a 401 that never reaches the route; an
// identity outage is a 503 after ONE validate_token — it used to pass through
// as "not a key", and the route then waited out a second validation.
func TestResolver_APIKeyQuota_IdentityFailuresStopAtTheLimiter(t *testing.T) {
	for _, tc := range []struct {
		name   string
		stub   *stubCaller
		status int
	}{
		{"rejected", &stubCaller{reply: []byte(`{"ok":false,"error":{"code":"unauthorized","message":"x"}}`)}, http.StatusUnauthorized},
		{"unavailable", &stubCaller{err: rpc.ErrOverloaded}, http.StatusServiceUnavailable},
	} {
		r := newResolver(tc.stub)
		routed := false
		route := http.HandlerFunc(func(_ http.ResponseWriter, req *http.Request) {
			routed = true
			r.Resolve(req)
		})
		rec := httptest.NewRecorder()
		ratelimit.New(1000, time.Minute).WrapAPIKey(route, r.APIKeyQuota).ServeHTTP(rec, reqWithToken("owt_sk_pub7_secret"))
		if rec.Code != tc.status || routed {
			t.Errorf("%s: want %d before the route, got %d (routed=%v)", tc.name, tc.status, rec.Code, routed)
		}
		if tc.stub.calls != 1 {
			t.Errorf("%s: want exactly one validate_token, got %d", tc.name, tc.stub.calls)
		}
	}
}

// TestResolver_MeterCaller_RejectionsByCredential: edge metering refuses a
// rejected key exactly like APIKeyQuota, but a rejected session token is just
// no identity — public routes still serve it as anonymous.
func TestResolver_MeterCaller_RejectionsByCredential(t *testing.T) {
	r := newResolver(&stubCaller{reply: []byte(`{"ok":false,"error":{"code":"unauthorized","message":"x"}}`)})
	if _, _, err := r.MeterCaller(reqWithToken("owt_sk_pub7_secret")); !errors.Is(err, ratelimit.ErrKeyRejected) {
		t.Errorf("rejected key: want ErrKeyRejected, got %v", err)
	}
	if _, ok, err := r.MeterCaller(reqWithToken("session.jwt.token")); ok || err != nil {
		t.Errorf("rejected session: want (false, nil), got (%v, %v)", ok, err)
	}
}

// The match-log download is an `<a download>` link the browser navigates to, so
// no script can attach an Authorization header. Without the cookie fallback the
// route would 401 every signed-in user.
func TestResolver_ResolveWithSessionCookie_FallsBackToTheCookie(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":9}}`)}
	r := newResolver(s)

	req := httptest.NewRequest("GET", "/api/v1/matches/7/log", nil)
	req.AddCookie(&http.Cookie{Name: auth.CookieName, Value: cred("cookie-token")})

	id, ok, err := r.ResolveWithSessionCookie(req)
	if err != nil || !ok || id["user_id"] != float64(9) {
		t.Fatalf("want the cookie identity, got id=%v ok=%v err=%v", id, ok, err)
	}
}

// The header stays authoritative: an API-key client hitting the same download
// must be judged on its key, never on a cookie the browser happened to send.
func TestResolver_ResolveWithSessionCookie_PrefersTheHeader(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":9}}`)}
	r := newResolver(s)

	req := reqWithToken("header-token")
	req.AddCookie(&http.Cookie{Name: auth.CookieName, Value: cred("cookie-token")})
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
	r := newResolver(s)

	req := httptest.NewRequest("POST", "/api/v1/tournaments", nil)
	req.AddCookie(&http.Cookie{Name: auth.CookieName, Value: cred("cookie-token")})

	if _, ok, _ := r.Resolve(req); ok {
		t.Fatal("Resolve must not authenticate from a cookie")
	}
	if s.calls != 0 {
		t.Fatalf("rpc must not be called, calls=%d", s.calls)
	}
}

// identity-svc publishes realtime:user:{id}:rbac whenever it drops a user's
// cached RBAC. Every token of that user must be judged again on its next
// request — a creator must see the workspace they just made, a removed member
// must lose it — while other users' entries and other topics stay put.
func TestResolver_RBACChangeEvictsOnlyThatUsersTokens(t *testing.T) {
	before := []byte(`{"ok":true,"data":{"user_id":9,"workspaces":[]}}`)
	s := &stubCaller{reply: before}
	r := newResolver(s)
	resolveAll := func() {
		t.Helper()
		for _, tok := range []string{"a", "b", "c"} {
			if _, ok, err := r.Resolve(reqWithToken(tok)); !ok || err != nil {
				t.Fatalf("resolve %s: ok=%v err=%v", tok, ok, err)
			}
		}
	}
	r.Resolve(reqWithToken("a"))
	r.Resolve(reqWithToken("b"))
	s.reply = []byte(`{"ok":true,"data":{"user_id":5}}`)
	r.Resolve(reqWithToken("c"))
	if s.calls != 3 {
		t.Fatalf("setup: calls=%d", s.calls)
	}

	for _, topic := range []string{"user:9:invalidation", "tournament:9:rbac", "user:x:rbac", "user:9:rbac:extra"} {
		r.Broadcast(topic, nil)
	}
	resolveAll()
	if s.calls != 3 {
		t.Fatalf("unrelated topics must not evict: calls=%d", s.calls)
	}

	s.reply = []byte(`{"ok":true,"data":{"user_id":9,"workspaces":[{"workspace_id":3,"rbac_permissions":[{"resource":"workspace","action":"update"}]}]}}`)
	r.Broadcast("user:9:rbac", nil)
	resolveAll()
	if s.calls != 5 {
		t.Fatalf("user 9's two tokens must revalidate, user 5's must not: calls=%d", s.calls)
	}
	if info, _, _ := r.Principal(reqWithToken("a")); info.WorkspaceGrants != 1 {
		t.Fatalf("the re-judged payload must carry the new grant, got %+v", info)
	}
}

// A validation that was already in flight when the RBAC change landed carries
// a pre-change answer: it must not be cached, and a request arriving after the
// eviction must not join it.
func TestResolver_EvictionFencesTheValidationInFlight(t *testing.T) {
	g := &gatedCaller{reply: []byte(`{"ok":true,"data":{"user_id":7}}`), release: make(chan struct{})}
	r := newResolver(g)
	waitCalls := func(n int64) {
		t.Helper()
		deadline := time.Now().Add(2 * time.Second)
		for g.calls.Load() < n {
			if time.Now().After(deadline) {
				t.Fatalf("expected %d rpc calls, got %d", n, g.calls.Load())
			}
			time.Sleep(time.Millisecond)
		}
	}
	var wg sync.WaitGroup
	resolve := func() {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r.Resolve(reqWithToken("t"))
		}()
	}

	resolve()
	waitCalls(1)
	r.EvictUser(7)
	resolve() // must start its own flight, not join the pre-eviction one
	waitCalls(2)
	close(g.release)
	wg.Wait()

	if _, ok, err := r.Resolve(reqWithToken("t")); !ok || err != nil {
		t.Fatalf("resolve: ok=%v err=%v", ok, err)
	}
	if n := g.calls.Load(); n != 2 {
		t.Fatalf("the post-eviction answer should be cached, got %d calls", n)
	}

	// The store fence on its own: the only flight predates the eviction.
	g2 := &gatedCaller{reply: []byte(`{"ok":true,"data":{"user_id":7}}`), release: make(chan struct{})}
	r2 := newResolver(g2)
	done := make(chan struct{})
	go func() {
		defer close(done)
		r2.Resolve(reqWithToken("t"))
	}()
	for g2.calls.Load() == 0 {
		time.Sleep(time.Millisecond)
	}
	r2.EvictUser(7)
	close(g2.release)
	<-done
	r2.Resolve(reqWithToken("t"))
	if n := g2.calls.Load(); n != 2 {
		t.Fatalf("a pre-eviction answer must not be cached, got %d calls", n)
	}
}

// TestResolver_ResetDropsEverythingAndFencesFlights: after the realtime bus
// reconnects, RBAC evictions published while it was down are lost, so every
// cached verdict goes — and an answer already in flight must not be stored.
func TestResolver_ResetDropsEverythingAndFencesFlights(t *testing.T) {
	s := &stubCaller{reply: []byte(`{"ok":true,"data":{"user_id":7}}`)}
	r := newResolver(s)
	for range 2 {
		r.Resolve(reqWithToken("a"))
		r.Resolve(reqWithToken("b"))
		r.Reset()
	}
	if s.calls != 4 {
		t.Fatalf("every token must revalidate after Reset, calls=%d", s.calls)
	}

	g := &gatedCaller{reply: []byte(`{"ok":true,"data":{"user_id":7}}`), release: make(chan struct{})}
	r2 := newResolver(g)
	done := make(chan struct{})
	go func() {
		defer close(done)
		r2.Resolve(reqWithToken("t"))
	}()
	for g.calls.Load() == 0 {
		time.Sleep(time.Millisecond)
	}
	r2.Reset()
	close(g.release)
	<-done
	r2.Resolve(reqWithToken("t"))
	if n := g.calls.Load(); n != 2 {
		t.Fatalf("a pre-Reset answer must not be cached, got %d calls", n)
	}
}
