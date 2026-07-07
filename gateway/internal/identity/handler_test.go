package identity

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
)

type fakeCaller struct {
	resp     []byte
	err      error
	gotQueue string
	gotBody  []byte
	called   bool
}

func (f *fakeCaller) Call(_ context.Context, queue string, body []byte) ([]byte, error) {
	f.called = true
	f.gotQueue = queue
	f.gotBody = body
	return f.resp, f.err
}

func newHandler(c RPCCaller) *Handler {
	return NewHandler(c, slog.New(slog.NewTextHandler(io.Discard, nil)))
}

func doValidate(h *Handler, token string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(http.MethodPost, "/api/auth/validate", nil)
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	h.Validate(w, r)
	return w
}

func TestValidate_OK(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{"sub":42,"username":"x"}}`)}
	w := doValidate(newHandler(caller), "tok123")

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	var payload map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload["sub"] != float64(42) {
		t.Fatalf("body = %v, want sub=42", payload)
	}
	if caller.gotQueue != queueValidateToken {
		t.Fatalf("queue = %q", caller.gotQueue)
	}
	var req map[string]string
	_ = json.Unmarshal(caller.gotBody, &req)
	if req["token"] != "tok123" {
		t.Fatalf("rpc body token = %q", req["token"])
	}
}

func TestValidate_ErrorEnvelopeMapsStatus(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":false,"error":{"code":"unauthorized","message":"Could not validate credentials"}}`)}
	w := doValidate(newHandler(caller), "bad")

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", w.Code)
	}
	var body map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	if body["detail"] != "Could not validate credentials" {
		t.Fatalf("detail = %q", body["detail"])
	}
}

func TestValidate_NoAuthHeader(t *testing.T) {
	caller := &fakeCaller{}
	w := doValidate(newHandler(caller), "")

	if w.Code != http.StatusForbidden {
		t.Fatalf("status = %d, want 403", w.Code)
	}
	if caller.called {
		t.Fatal("RPC must not be called when no credentials are present")
	}
}

func TestValidate_RPCUnavailable(t *testing.T) {
	caller := &fakeCaller{err: rpc.ErrNotConnected}
	w := doValidate(newHandler(caller), "tok")

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", w.Code)
	}
}

func TestValidate_BadEnvelope(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`not json`)}
	w := doValidate(newHandler(caller), "tok")

	if w.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", w.Code)
	}
}

func TestLogin_ForwardsBodyAndMeta(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{"access_token":"a","refresh_token":"r","token_type":"bearer"}}`)}
	r := httptest.NewRequest(http.MethodPost, "/api/auth/login", strings.NewReader(`{"email":"e@x.com","password":"p"}`))
	r.Header.Set("X-Forwarded-For", "1.2.3.4")
	r.Header.Set("User-Agent", "UA/1")
	w := httptest.NewRecorder()
	newHandler(caller).Login(w, r)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if caller.gotQueue != queueLogin {
		t.Fatalf("queue = %q", caller.gotQueue)
	}
	var req map[string]any
	_ = json.Unmarshal(caller.gotBody, &req)
	if req["email"] != "e@x.com" || req["user_agent"] != "UA/1" || req["ip_address"] != "1.2.3.4" {
		t.Fatalf("rpc body did not carry creds+meta: %v", req)
	}
	var tok map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &tok)
	if tok["access_token"] != "a" {
		t.Fatalf("token not echoed: %v", tok)
	}
}

func TestLogout_NoBearer(t *testing.T) {
	caller := &fakeCaller{}
	r := httptest.NewRequest(http.MethodPost, "/api/auth/logout", strings.NewReader(`{"refresh_token":"r"}`))
	w := httptest.NewRecorder()
	newHandler(caller).Logout(w, r)

	if w.Code != http.StatusForbidden {
		t.Fatalf("status = %d, want 403", w.Code)
	}
	if caller.called {
		t.Fatal("RPC must not run without a bearer token")
	}
}

func TestLogout_ForwardsAccessToken(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":null}`)}
	r := httptest.NewRequest(http.MethodPost, "/api/auth/logout", strings.NewReader(`{"refresh_token":"rt"}`))
	r.Header.Set("Authorization", "Bearer acc")
	w := httptest.NewRecorder()
	newHandler(caller).Logout(w, r)

	if w.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204", w.Code)
	}
	var req map[string]any
	_ = json.Unmarshal(caller.gotBody, &req)
	if req["access_token"] != "acc" || req["refresh_token"] != "rt" {
		t.Fatalf("logout body = %v", req)
	}
}

// TestOAuthURL_ForwardsGuardHash (Task 10R fix 1): the optional
// guard_hash query param -- set only by the frontend's custom-domain apex
// bounce (oauth-login.ts) -- must reach identity-svc's rpc.identity.oauth_url
// alongside origin/redirect/action/csrf so it gets signed into the state.
func TestOAuthURL_ForwardsGuardHash(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{"provider":"discord","url":"https://discord.example/authorize","state":"s"}}`)}
	r := httptest.NewRequest(http.MethodGet,
		"/api/auth/oauth/discord/url?origin=https://anakq.gg&redirect=/account&action=login&csrf=raw-csrf&guard_hash=abc123",
		nil)
	w := httptest.NewRecorder()
	newHandler(caller).OAuthURL(w, r)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	var req map[string]any
	_ = json.Unmarshal(caller.gotBody, &req)
	if req["guard_hash"] != "abc123" {
		t.Fatalf("guard_hash = %v, want \"abc123\"", req["guard_hash"])
	}
}

// TestOAuthURL_OmittedGuardHashForwardsEmptyString documents that a
// platform-host flow (no guard_hash query param at all) forwards an empty
// string, not a missing key -- identity-svc treats an empty string the same
// as absent (never signs an empty "lg" into the state).
func TestOAuthURL_OmittedGuardHashForwardsEmptyString(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{"provider":"discord","url":"https://discord.example/authorize","state":"s"}}`)}
	r := httptest.NewRequest(http.MethodGet,
		"/api/auth/oauth/discord/url?origin=https://owt.craazzzyyfoxx.me&redirect=/&action=login&csrf=raw-csrf",
		nil)
	w := httptest.NewRecorder()
	newHandler(caller).OAuthURL(w, r)

	var req map[string]any
	_ = json.Unmarshal(caller.gotBody, &req)
	if req["guard_hash"] != "" {
		t.Fatalf("guard_hash = %v, want \"\"", req["guard_hash"])
	}
}

// TestOAuthLink_NoBearer_StillCallsIdentity documents the Task 10R behavior
// change: unlike every other authenticated identity route, OAuthLink no
// longer rejects a missing bearer at the gateway -- identity-svc decides
// (branching on the signed OAuth state's origin) whether one is required.
func TestOAuthLink_NoBearer_StillCallsIdentity(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{"mode":"link_ticket","ticket":"tic-1","origin":"https://anakq.gg","redirect":"/account"}}`)}
	r := httptest.NewRequest(http.MethodPost, "/api/auth/oauth/discord/link", strings.NewReader(`{"code":"c","state":"s","csrf":"x"}`))
	w := httptest.NewRecorder()
	newHandler(caller).OAuthLink(w, r)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if !caller.called {
		t.Fatal("RPC must run even without a bearer token -- identity-svc decides (Task 10R)")
	}
}

// TestOAuthLink_NoBearer_BodyAccessTokenNeverReachesIdentity is the
// "hardening" test from the Task 10R brief: a client-supplied access_token
// in the body must never survive mergeBody's overwrite, whether or not a
// real bearer is present. With no bearer, the forwarded access_token must be
// the empty string, never the attacker-supplied value.
func TestOAuthLink_NoBearer_BodyAccessTokenNeverReachesIdentity(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{"mode":"link_ticket","ticket":"tic-1","origin":"https://anakq.gg","redirect":"/account"}}`)}
	r := httptest.NewRequest(http.MethodPost, "/api/auth/oauth/discord/link",
		strings.NewReader(`{"code":"c","state":"s","csrf":"x","access_token":"attacker-supplied"}`))
	w := httptest.NewRecorder()
	newHandler(caller).OAuthLink(w, r)

	var req map[string]any
	_ = json.Unmarshal(caller.gotBody, &req)
	if req["access_token"] != "" {
		t.Fatalf("access_token = %v, want \"\" (body-supplied value must never survive)", req["access_token"])
	}
}

// TestOAuthLink_WithBearer_OverridesBodyAccessToken proves the same
// overwrite holds when a real bearer IS present: the server-computed
// access_token (from the Authorization header) always wins over whatever a
// client put in the JSON body.
func TestOAuthLink_WithBearer_OverridesBodyAccessToken(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{"mode":"linked","message":"ok","provider":"discord","username":"u","origin":"https://owt.craazzzyyfoxx.me","redirect":"/account"}}`)}
	r := httptest.NewRequest(http.MethodPost, "/api/auth/oauth/discord/link",
		strings.NewReader(`{"code":"c","state":"s","csrf":"x","access_token":"attacker-supplied"}`))
	r.Header.Set("Authorization", "Bearer real-token")
	w := httptest.NewRecorder()
	newHandler(caller).OAuthLink(w, r)

	var req map[string]any
	_ = json.Unmarshal(caller.gotBody, &req)
	if req["access_token"] != "real-token" {
		t.Fatalf("access_token = %v, want \"real-token\"", req["access_token"])
	}
}

func TestLinkComplete_NoBearer(t *testing.T) {
	caller := &fakeCaller{}
	r := httptest.NewRequest(http.MethodPost, "/api/auth/link/complete", strings.NewReader(`{"ticket":"tic-1"}`))
	w := httptest.NewRecorder()
	newHandler(caller).LinkComplete(w, r)

	if w.Code != http.StatusForbidden {
		t.Fatalf("status = %d, want 403", w.Code)
	}
	if caller.called {
		t.Fatal("RPC must not run without a bearer token -- this route is NOT public (unlike SsoExchange)")
	}
}

func TestLinkComplete_ForwardsAccessTokenAndTicket(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{"message":"Discord account linked successfully","provider":"discord","username":"u"}}`)}
	r := httptest.NewRequest(http.MethodPost, "/api/auth/link/complete", strings.NewReader(`{"ticket":"tic-1"}`))
	r.Header.Set("Authorization", "Bearer acc")
	w := httptest.NewRecorder()
	newHandler(caller).LinkComplete(w, r)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if caller.gotQueue != queueLinkComplete {
		t.Fatalf("queue = %q", caller.gotQueue)
	}
	var req map[string]any
	_ = json.Unmarshal(caller.gotBody, &req)
	if req["access_token"] != "acc" || req["ticket"] != "tic-1" {
		t.Fatalf("link_complete body = %v", req)
	}
}

// TestLinkComplete_BodyAccessTokenNeverOverridesBearer guards the same
// footgun as OAuthLink above, for the new route.
func TestLinkComplete_BodyAccessTokenNeverOverridesBearer(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{}}`)}
	r := httptest.NewRequest(http.MethodPost, "/api/auth/link/complete",
		strings.NewReader(`{"ticket":"tic-1","access_token":"attacker-supplied"}`))
	r.Header.Set("Authorization", "Bearer real-token")
	w := httptest.NewRecorder()
	newHandler(caller).LinkComplete(w, r)

	var req map[string]any
	_ = json.Unmarshal(caller.gotBody, &req)
	if req["access_token"] != "real-token" {
		t.Fatalf("access_token = %v, want \"real-token\"", req["access_token"])
	}
}

// TestLinkComplete_ForwardsGuard (Task 10R fix 1): "guard" -- the raw
// owt_xdomain_guard cookie value the frontend route read -- must reach
// identity-svc's rpc.identity.link_complete alongside "ticket"/access_token.
// mergeBody only overwrites "access_token"; every other client field
// (including "guard") passes through unfiltered, so no gateway code needs
// to name "guard" explicitly for it to be forwarded.
func TestLinkComplete_ForwardsGuard(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{"message":"Discord account linked successfully","provider":"discord","username":"u"}}`)}
	r := httptest.NewRequest(http.MethodPost, "/api/auth/link/complete",
		strings.NewReader(`{"ticket":"tic-1","guard":"raw-guard-value"}`))
	r.Header.Set("Authorization", "Bearer acc")
	w := httptest.NewRecorder()
	newHandler(caller).LinkComplete(w, r)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	var req map[string]any
	_ = json.Unmarshal(caller.gotBody, &req)
	if req["ticket"] != "tic-1" || req["guard"] != "raw-guard-value" || req["access_token"] != "acc" {
		t.Fatalf("link_complete body = %v", req)
	}
}

// TestSsoExchange_ForwardsGuard (Task 10R fix 1): same as LinkComplete
// above, but for the public /auth/sso/exchange route, which uses
// decodeRawBody (re-marshals the entire client body verbatim) rather than
// mergeBody.
func TestSsoExchange_ForwardsGuard(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{"access_token":"a","refresh_token":"r"}}`)}
	r := httptest.NewRequest(http.MethodPost, "/api/auth/sso/exchange",
		strings.NewReader(`{"ticket":"tic-1","guard":"raw-guard-value"}`))
	w := httptest.NewRecorder()
	newHandler(caller).SsoExchange(w, r)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if caller.gotQueue != queueSsoExchange {
		t.Fatalf("queue = %q", caller.gotQueue)
	}
	var req map[string]any
	_ = json.Unmarshal(caller.gotBody, &req)
	if req["ticket"] != "tic-1" || req["guard"] != "raw-guard-value" {
		t.Fatalf("sso_exchange body = %v", req)
	}
}

func TestRbacListSessions_ForwardsAllQuery(t *testing.T) {
	caller := &fakeCaller{resp: []byte(`{"ok":true,"data":{"results":[],"total":0,"page":2,"per_page":25}}`)}
	r := httptest.NewRequest(http.MethodGet,
		"/api/auth/rbac/sessions?page=2&per_page=25&sort=last_seen_at&order=desc&status=active", nil)
	r.Header.Set("Authorization", "Bearer acc")
	w := httptest.NewRecorder()
	newHandler(caller).RbacListSessions(w, r)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if caller.gotQueue != queueRbacListSessions {
		t.Fatalf("queue = %q", caller.gotQueue)
	}

	var req struct {
		AccessToken string              `json:"access_token"`
		Query       map[string][]string `json:"query"`
	}
	if err := json.Unmarshal(caller.gotBody, &req); err != nil {
		t.Fatal(err)
	}
	if req.AccessToken != "acc" {
		t.Fatalf("access_token = %q, want acc", req.AccessToken)
	}
	for key, want := range map[string]string{
		"page": "2", "per_page": "25", "sort": "last_seen_at", "order": "desc", "status": "active",
	} {
		got := req.Query[key]
		if len(got) != 1 || got[0] != want {
			t.Fatalf("query[%q] = %v, want [%q]", key, got, want)
		}
	}
}

func TestRbacListSessions_NoBearer(t *testing.T) {
	caller := &fakeCaller{}
	r := httptest.NewRequest(http.MethodGet, "/api/auth/rbac/sessions?page=1", nil)
	w := httptest.NewRecorder()
	newHandler(caller).RbacListSessions(w, r)

	if w.Code != http.StatusForbidden {
		t.Fatalf("status = %d, want 403", w.Code)
	}
	if caller.called {
		t.Fatal("RPC must not run without a bearer token")
	}
}

func TestClientMeta(t *testing.T) {
	// The trusted hop is the RIGHT-most X-Forwarded-For entry (nginx appends the
	// real peer via $proxy_add_x_forwarded_for); the left-most "9.9.9.9" is
	// client-supplied and must NOT be trusted.
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set("X-Forwarded-For", "9.9.9.9, 10.0.0.1")
	r.Header.Set("User-Agent", "Mozilla")
	ua, ip := clientMeta(r)
	if ua != "Mozilla" || ip != "10.0.0.1" {
		t.Fatalf("clientMeta = %q, %q, want \"Mozilla\", \"10.0.0.1\"", ua, ip)
	}

	// X-Real-IP (set by nginx to $remote_addr) wins over X-Forwarded-For.
	r = httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set("X-Real-IP", "203.0.113.7")
	r.Header.Set("X-Forwarded-For", "9.9.9.9, 10.0.0.1")
	if _, ip = clientMeta(r); ip != "203.0.113.7" {
		t.Fatalf("clientMeta ip = %q, want \"203.0.113.7\"", ip)
	}

	// Spoofable vendor CDN headers are ignored (Cloudflare is not used).
	r = httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set("CF-Connecting-IP", "6.6.6.6")
	r.RemoteAddr = "192.0.2.5:5555"
	if _, ip = clientMeta(r); ip != "192.0.2.5" {
		t.Fatalf("clientMeta ip = %q, want \"192.0.2.5\"", ip)
	}
}
