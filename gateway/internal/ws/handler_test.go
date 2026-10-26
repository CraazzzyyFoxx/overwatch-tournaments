package ws

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth/authtest"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/principal"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/protocol"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/replay"
)

// testPrincipals admits the way production does — the local EdDSA check, then
// identity-svc — over an identity-svc that accepts every token as a plain user.
var testPrincipals = Principals(auth.New(authtest.PublicKey), func(context.Context, string) (principal.Info, bool, error) {
	return principal.Info{}, true, nil
})

type allowAuthorizer struct {
	allow bool
	err   error
}

func (a allowAuthorizer) Allow(context.Context, *auth.User, string) (bool, error) {
	return a.allow, a.err
}

type fakeReplayer struct {
	cursor int64
	events []protocol.Envelope
	err    error
}

func (f fakeReplayer) CurrentCursor(context.Context, string) (int64, error) {
	return f.cursor, nil
}

func (f fakeReplayer) EventsSince(context.Context, string, *int64, int64) ([]protocol.Envelope, error) {
	return f.events, f.err
}

func newServer(t *testing.T, authz Authorizer, rep Replayer) string {
	return newServerLimits(t, authz, rep, Limits{})
}

func newServerLimits(t *testing.T, authz Authorizer, rep Replayer, limits Limits) string {
	t.Helper()
	h := NewHandler(NewHub(), testPrincipals, authz, rep, 30*time.Second,
		slog.New(slog.NewTextHandler(io.Discard, nil)), nil, nil, nil, nil, limits)
	mux := http.NewServeMux()
	mux.Handle("/ws", h)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv.URL
}

func mintToken(_ *testing.T, sub string) string {
	return authtest.Token(sub)
}

// dial connects with token in the Authorization header — the credential a
// script sends; browsers send the session cookie. "" is anonymous.
func dial(t *testing.T, ctx context.Context, serverURL, token string) *websocket.Conn {
	t.Helper()
	var opts *websocket.DialOptions
	if token != "" {
		opts = &websocket.DialOptions{HTTPHeader: http.Header{"Authorization": {"Bearer " + token}}}
	}
	return dialWith(t, ctx, "ws"+strings.TrimPrefix(serverURL, "http")+"/ws", opts)
}

func dialWith(t *testing.T, ctx context.Context, u string, opts *websocket.DialOptions) *websocket.Conn {
	t.Helper()
	c, _, err := websocket.Dial(ctx, u, opts)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	t.Cleanup(func() { c.CloseNow() })
	return c
}

func writeJSON(t *testing.T, ctx context.Context, c *websocket.Conn, v any) {
	t.Helper()
	b, _ := json.Marshal(v)
	if err := c.Write(ctx, websocket.MessageText, b); err != nil {
		t.Fatalf("write: %v", err)
	}
}

func readJSON(t *testing.T, ctx context.Context, c *websocket.Conn) map[string]any {
	t.Helper()
	rctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	_, data, err := c.Read(rctx)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	var m map[string]any
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("unmarshal %q: %v", data, err)
	}
	return m
}

func TestWS_SubscribePublic(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{cursor: 5})
	ctx := context.Background()
	c := dial(t, ctx, url, "")

	writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:bracket"})
	m := readJSON(t, ctx, c)
	if m["op"] != "subscribed" || m["topic"] != "tournament:1:bracket" || m["cursor"] != float64(5) {
		t.Fatalf("unexpected subscribed frame: %v", m)
	}
}

func TestWS_SubscribeForbidden(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: false}, fakeReplayer{})
	ctx := context.Background()
	c := dial(t, ctx, url, mintToken(t, "7")) // authenticated but not permitted

	writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:balancer"})
	m := readJSON(t, ctx, c)
	if m["op"] != "error" || m["code"] != "forbidden" {
		t.Fatalf("expected forbidden error for an authenticated non-member, got %v", m)
	}
}

// TestWS_SubscribeAuthRequired asserts an anonymous denial is surfaced as
// auth_required (login may grant access), distinct from forbidden.
func TestWS_SubscribeAuthRequired(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: false}, fakeReplayer{})
	ctx := context.Background()
	c := dial(t, ctx, url, "") // anonymous

	writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:balancer"})
	m := readJSON(t, ctx, c)
	if m["op"] != "error" || m["code"] != "auth_required" {
		t.Fatalf("expected auth_required error for an anonymous user, got %v", m)
	}
}

func TestWS_ReplayGap(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{err: replay.ErrGapTooLarge})
	ctx := context.Background()
	c := dial(t, ctx, url, "")

	writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:bracket", "after_event_id": 1})
	m := readJSON(t, ctx, c)
	if m["op"] != "error" || m["code"] != "replay_gap_too_large" {
		t.Fatalf("expected replay_gap_too_large, got %v", m)
	}
}

func TestWS_Ping(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{})
	ctx := context.Background()
	c := dial(t, ctx, url, "")

	writeJSON(t, ctx, c, map[string]any{"op": "ping"})
	if m := readJSON(t, ctx, c); m["op"] != "pong" {
		t.Fatalf("expected pong, got %v", m)
	}
}

func TestWS_PublishGuards(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{})
	ctx := context.Background()

	t.Run("anon cannot publish", func(t *testing.T) {
		c := dial(t, ctx, url, "")
		writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:bracket"})
		readJSON(t, ctx, c) // subscribed
		writeJSON(t, ctx, c, map[string]any{"op": "publish", "topic": "tournament:1:bracket", "event_type": "balancer.drag", "data": map[string]any{}})
		if m := readJSON(t, ctx, c); m["code"] != "forbidden" {
			t.Fatalf("expected forbidden, got %v", m)
		}
	})

	t.Run("not subscribed", func(t *testing.T) {
		c := dial(t, ctx, url, mintToken(t, "1"))
		writeJSON(t, ctx, c, map[string]any{"op": "publish", "topic": "tournament:1:balancer", "event_type": "balancer.drag", "data": map[string]any{}})
		if m := readJSON(t, ctx, c); m["code"] != "not_subscribed" {
			t.Fatalf("expected not_subscribed, got %v", m)
		}
	})

	t.Run("forbidden event type", func(t *testing.T) {
		c := dial(t, ctx, url, mintToken(t, "1"))
		writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:bracket"})
		readJSON(t, ctx, c) // subscribed
		writeJSON(t, ctx, c, map[string]any{"op": "publish", "topic": "tournament:1:bracket", "event_type": "tournament.updated", "data": map[string]any{}})
		if m := readJSON(t, ctx, c); m["code"] != "forbidden_event" {
			t.Fatalf("expected forbidden_event, got %v", m)
		}
	})
}

// TestWS_FanoutAndPresence is the end-to-end check: two authenticated clients
// on a balancer topic, presence reflects both, a published drag reaches the
// other client but not the sender.
func TestWS_FanoutAndPresence(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{cursor: 0})
	ctx := context.Background()
	const topic = "tournament:1:balancer"

	// Client A subscribes; drain its subscribed + presence[1] frames.
	a := dial(t, ctx, url, mintToken(t, "1"))
	writeJSON(t, ctx, a, map[string]any{"op": "subscribe", "topic": topic})
	if m := readJSON(t, ctx, a); m["op"] != "subscribed" {
		t.Fatalf("A expected subscribed, got %v", m)
	}
	if ids := presenceIDs(t, readJSON(t, ctx, a)); !equalInts(ids, []int{1}) {
		t.Fatalf("A expected presence [1], got %v", ids)
	}

	// Client B subscribes; B reads subscribed + presence[1,2].
	b := dial(t, ctx, url, mintToken(t, "2"))
	writeJSON(t, ctx, b, map[string]any{"op": "subscribe", "topic": topic})
	if m := readJSON(t, ctx, b); m["op"] != "subscribed" {
		t.Fatalf("B expected subscribed, got %v", m)
	}
	if ids := presenceIDs(t, readJSON(t, ctx, b)); !equalInts(ids, []int{1, 2}) {
		t.Fatalf("B expected presence [1,2], got %v", ids)
	}
	// A also receives the updated presence[1,2].
	if ids := presenceIDs(t, readJSON(t, ctx, a)); !equalInts(ids, []int{1, 2}) {
		t.Fatalf("A expected presence [1,2], got %v", ids)
	}

	// A publishes a drag; B must receive it, A must not.
	writeJSON(t, ctx, a, map[string]any{
		"op": "publish", "topic": topic, "event_type": "balancer.drag",
		"data": map[string]any{"x": 1},
	})

	m := readJSON(t, ctx, b)
	if m["op"] != "event" {
		t.Fatalf("B expected event, got %v", m)
	}
	ev := m["event"].(map[string]any)
	if ev["event_type"] != "balancer.drag" || ev["actor_user_id"] != float64(1) || ev["event_id"] != float64(0) {
		t.Fatalf("B got unexpected drag envelope: %v", ev)
	}

	// A (the sender) must not receive its own drag.
	rctx, cancel := context.WithTimeout(ctx, 400*time.Millisecond)
	defer cancel()
	if _, _, err := a.Read(rctx); err == nil {
		t.Fatal("sender should not receive its own published frame")
	}
}

func TestWS_DraftPresenceIncludesAuthenticatedUsersAndAnonymousViewerCount(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{cursor: 0})
	ctx := context.Background()
	const topic = "draft:1:board"

	authenticated := dial(t, ctx, url, mintToken(t, "7"))
	writeJSON(t, ctx, authenticated, map[string]any{"op": "subscribe", "topic": topic})
	readJSON(t, ctx, authenticated) // subscribed
	first := readJSON(t, ctx, authenticated)
	if ids := presenceIDsFor(t, first, "draft.presence"); !equalInts(ids, []int{7}) {
		t.Fatalf("expected authenticated presence [7], got %v", ids)
	}
	if count := presenceAnonymousCount(t, first); count != 0 {
		t.Fatalf("expected zero anonymous viewers, got %d", count)
	}

	anonymous := dial(t, ctx, url, "")
	writeJSON(t, ctx, anonymous, map[string]any{"op": "subscribe", "topic": topic})
	readJSON(t, ctx, anonymous) // subscribed
	updated := readJSON(t, ctx, anonymous)
	if ids := presenceIDsFor(t, updated, "draft.presence"); !equalInts(ids, []int{7}) {
		t.Fatalf("expected authenticated presence [7], got %v", ids)
	}
	if count := presenceAnonymousCount(t, updated); count != 1 {
		t.Fatalf("expected one anonymous viewer, got %d", count)
	}
}

// newPresenceServer is newServer with the handler exposed and its presence
// window set before any connection can read it.
func newPresenceServer(t *testing.T, window time.Duration) (*Handler, string) {
	t.Helper()
	h := NewHandler(NewHub(), testPrincipals, allowAuthorizer{allow: true}, fakeReplayer{}, 30*time.Second,
		slog.New(slog.NewTextHandler(io.Discard, nil)), nil, nil, nil, nil, Limits{})
	h.presenceWindow = window
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	return h, srv.URL
}

// A room filling up must not cost N(N+1)/2 presence frames: a burst of joins
// inside one window reaches each subscriber as at most two presence frames
// (the leading one and the folded trailing one), the last carrying the final
// count. Once the topic goes quiet it keeps no throttle state, and the next
// isolated join is broadcast at once rather than a window later.
func TestWS_PresenceBurstIsThrottled(t *testing.T) {
	const window = 500 * time.Millisecond
	const n = 10
	const topic = "draft:1:board"
	h, url := newPresenceServer(t, window)
	ctx := context.Background()

	conns := make([]*websocket.Conn, n)
	for i := range conns {
		conns[i] = dial(t, ctx, url, "")
	}
	for _, c := range conns {
		writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": topic})
	}
	for i, c := range conns {
		frames := 0
		for {
			m := readJSON(t, ctx, c)
			if m["op"] == "subscribed" {
				continue
			}
			frames++
			if presenceAnonymousCount(t, m) == n {
				break
			}
		}
		if frames > 2 {
			t.Fatalf("subscriber %d got %d presence frames for one burst, want at most 2", i, frames)
		}
	}

	deadline := time.Now().Add(4 * window)
	for {
		h.presenceMu.Lock()
		_, open := h.presence[topic]
		h.presenceMu.Unlock()
		if !open {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("a quiet topic kept its presence window open")
		}
		time.Sleep(10 * time.Millisecond)
	}

	late := dial(t, ctx, url, "")
	start := time.Now()
	writeJSON(t, ctx, late, map[string]any{"op": "subscribe", "topic": topic})
	readJSON(t, ctx, late) // subscribed
	if got := presenceAnonymousCount(t, readJSON(t, ctx, late)); got != n+1 {
		t.Fatalf("isolated join presence count = %d, want %d", got, n+1)
	}
	if elapsed := time.Since(start); elapsed >= window {
		t.Fatalf("isolated join was broadcast after %v, want immediately", elapsed)
	}
}

func presenceIDs(t *testing.T, m map[string]any) []int {
	return presenceIDsFor(t, m, "balancer.presence")
}

func presenceIDsFor(t *testing.T, m map[string]any, eventType string) []int {
	t.Helper()
	if m["op"] != "event" {
		t.Fatalf("expected event frame for presence, got %v", m)
	}
	ev := m["event"].(map[string]any)
	if ev["event_type"] != eventType {
		t.Fatalf("expected %s, got %v", eventType, ev["event_type"])
	}
	raw := ev["data"].(map[string]any)["user_ids"].([]any)
	ids := make([]int, len(raw))
	for i, v := range raw {
		ids[i] = int(v.(float64))
	}
	return ids
}

func presenceAnonymousCount(t *testing.T, m map[string]any) int {
	t.Helper()
	ev := m["event"].(map[string]any)
	return int(ev["data"].(map[string]any)["anonymous_viewer_count"].(float64))
}

func equalInts(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func mintTokenWithExp(_ *testing.T, sub string, exp time.Time) string {
	claims := authtest.Claims(sub)
	claims["exp"] = exp.Unix()
	return authtest.Sign(claims)
}

// TestWS_ClosesAtTokenExpiry asserts an authenticated connection is torn down
// once its access token expires, rather than living until the idle timeout.
func TestWS_ClosesAtTokenExpiry(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: true}, fakeReplayer{cursor: 1})
	ctx := context.Background()
	token := mintTokenWithExp(t, "7", time.Now().Add(time.Second))
	c := dial(t, ctx, url, token)

	writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:bracket"})
	if m := readJSON(t, ctx, c); m["op"] != "subscribed" {
		t.Fatalf("expected subscribed while the token is valid, got %v", m)
	}

	readCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	if _, _, err := c.Read(readCtx); err == nil {
		t.Fatal("expected the connection to close at token expiry")
	}
}

// TestWS_TopicSubscriptionCap asserts a connection cannot exceed its topic
// budget (tighter for anonymous clients).
func TestWS_TopicSubscriptionCap(t *testing.T) {
	url := newServerLimits(t, allowAuthorizer{allow: true}, fakeReplayer{cursor: 1}, Limits{MaxTopicsAnon: 1})
	ctx := context.Background()
	c := dial(t, ctx, url, "")

	writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:bracket"})
	if m := readJSON(t, ctx, c); m["op"] != "subscribed" {
		t.Fatalf("first subscribe should succeed, got %v", m)
	}

	writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:2:bracket"})
	if m := readJSON(t, ctx, c); m["op"] != "error" || m["code"] != "too_many_topics" {
		t.Fatalf("second subscribe should hit the topic cap, got %v", m)
	}
}

// TestWS_AnonConnectionCapPerIP asserts a second anonymous connection from the
// same IP is rejected at the handshake with a 429 while one is already open.
func TestWS_AnonConnectionCapPerIP(t *testing.T) {
	url := newServerLimits(t, allowAuthorizer{allow: true}, fakeReplayer{}, Limits{MaxAnonConnsPerIP: 1})
	ctx := context.Background()

	dial(t, ctx, url, "") // first anonymous connection holds the only slot

	u := "ws" + strings.TrimPrefix(url, "http") + "/ws"
	conn, resp, err := websocket.Dial(ctx, u, nil)
	if err == nil {
		conn.CloseNow()
		t.Fatal("expected the second anonymous connection to be rejected")
	}
	if resp == nil || resp.StatusCode != http.StatusTooManyRequests {
		t.Fatalf("expected 429, got resp=%v err=%v", resp, err)
	}
}

func newHubServer(t *testing.T, hub *Hub) string {
	t.Helper()
	h := NewHandler(hub, testPrincipals, allowAuthorizer{allow: true}, fakeReplayer{cursor: 1}, 30*time.Second,
		slog.New(slog.NewTextHandler(io.Discard, nil)), nil, nil, nil, nil, Limits{})
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	return srv.URL
}

// An unsubscribe for a topic the socket never joined must cost nothing: it
// used to open a presence throttle window (and timer) per unique topic.
func TestWS_UnsubscribeOfUnjoinedTopicIsANoop(t *testing.T) {
	h, url := newPresenceServer(t, time.Minute)
	ctx := context.Background()
	c := dial(t, ctx, url, "")
	writeJSON(t, ctx, c, map[string]any{"op": "unsubscribe", "topic": "draft:9:board"})
	writeJSON(t, ctx, c, map[string]any{"op": "ping"})
	if m := readJSON(t, ctx, c); m["op"] != "pong" {
		t.Fatalf("expected pong, got %v", m)
	}
	h.presenceMu.Lock()
	open := len(h.presence)
	h.presenceMu.Unlock()
	if open != 0 {
		t.Fatalf("unsubscribing a never-joined topic opened %d presence windows", open)
	}
}

// A socket accepted after CloseAll's snapshot used to register anyway and
// outlive shutdown. It is turned away with 1001 instead.
func TestWS_RefusedAfterCloseAll(t *testing.T) {
	hub := NewHub()
	url := newHubServer(t, hub)
	hub.CloseAll()
	c := dial(t, context.Background(), url, "")
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if _, _, err := c.Read(ctx); websocket.CloseStatus(err) != websocket.StatusGoingAway {
		t.Fatalf("expected close 1001 after CloseAll, got %v", err)
	}
	if n := hub.Count(); n != 0 {
		t.Fatalf("CloseAll'd hub registered %d connections", n)
	}
}

// Reset (after a lost Redis subscription) closes live sockets with 1012 so
// clients reconnect and replay, and keeps accepting new ones.
func TestWS_HubResetClosesWithServiceRestart(t *testing.T) {
	hub := NewHub()
	url := newHubServer(t, hub)
	ctx := context.Background()
	subscribe := func(c *websocket.Conn) {
		t.Helper()
		writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:bracket"})
		if m := readJSON(t, ctx, c); m["op"] != "subscribed" {
			t.Fatalf("expected subscribed, got %v", m)
		}
	}
	c := dial(t, ctx, url, "")
	subscribe(c)
	hub.Reset()
	rctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	if _, _, err := c.Read(rctx); websocket.CloseStatus(err) != websocket.StatusServiceRestart {
		t.Fatalf("expected close 1012 on Reset, got %v", err)
	}
	subscribe(dial(t, ctx, url, ""))
}

// The handshake reads the Authorization header or the session cookie; a
// ?token= is never read (a credential in a URL lands in every proxy log), so
// that socket is anonymous: auth_required, not forbidden.
func TestWS_CredentialSources(t *testing.T) {
	url := newServer(t, allowAuthorizer{allow: false}, fakeReplayer{})
	ctx := context.Background()
	base := "ws" + strings.TrimPrefix(url, "http") + "/ws"
	token := mintToken(t, "7")
	for name, tc := range map[string]struct {
		url  string
		opts *websocket.DialOptions
		want string
	}{
		"query":  {base + "?token=" + token, nil, "auth_required"},
		"cookie": {base, &websocket.DialOptions{HTTPHeader: http.Header{"Cookie": {auth.CookieName + "=" + token}}}, "forbidden"},
		"header": {base, &websocket.DialOptions{HTTPHeader: http.Header{"Authorization": {"Bearer " + token}}}, "forbidden"},
	} {
		c := dialWith(t, ctx, tc.url, tc.opts)
		writeJSON(t, ctx, c, map[string]any{"op": "subscribe", "topic": "tournament:1:balancer"})
		if m := readJSON(t, ctx, c); m["code"] != tc.want {
			t.Errorf("%s: want %s, got %v", name, tc.want, m)
		}
	}
}

func TestPrincipals(t *testing.T) {
	ctx := context.Background()
	session := mintToken(t, "7")
	key := "owt_sk_" + strings.Repeat("ab", 8) + "_" + strings.Repeat("cd", 32)
	down := errors.New("identity unavailable")
	cases := []struct {
		name  string
		token string
		info  principal.Info
		ok    bool
		err   error
		want  *auth.User
	}{
		{"session: superuser from identity", session, principal.Info{UserID: 7, IsSuperuser: true}, true, nil, &auth.User{ID: 7, IsSuperuser: true}},
		{"session: revoked", session, principal.Info{}, false, nil, nil},
		{"session: identity down degrades to the claims", session, principal.Info{}, false, down, &auth.User{ID: 7}},
		{"session: forged never reaches identity", "not.a.jwt", principal.Info{UserID: 7}, true, nil, nil},
		{"key: pinned, never superuser", key, principal.Info{UserID: 7, WorkspaceGrants: 1, APIKeyWorkspaceID: 3, IsSuperuser: true}, true, nil, &auth.User{ID: 7, APIKeyWorkspaceID: 3}},
		{"key: no workspace", key, principal.Info{UserID: 7, WorkspaceGrants: 1}, true, nil, nil},
		{"key: no grant", key, principal.Info{UserID: 7, APIKeyWorkspaceID: 3}, true, nil, nil},
		{"key: identity down", key, principal.Info{}, false, down, nil},
	}
	for _, tc := range cases {
		called := false
		got, err := Principals(auth.New(authtest.PublicKey), func(context.Context, string) (principal.Info, bool, error) {
			called = true
			return tc.info, tc.ok, tc.err
		})(ctx, tc.token)
		if !errors.Is(err, tc.err) {
			t.Errorf("%s: err = %v, want %v", tc.name, err, tc.err)
		}
		switch {
		case tc.want == nil && got != nil:
			t.Errorf("%s: want anonymous, got %+v", tc.name, got)
		case tc.want != nil && (got == nil || got.ID != tc.want.ID || got.IsSuperuser != tc.want.IsSuperuser ||
			got.APIKeyWorkspaceID != tc.want.APIKeyWorkspaceID || got.Token != tc.token):
			t.Errorf("%s: want %+v carrying its token, got %+v", tc.name, tc.want, got)
		case tc.token == session && tc.want != nil && got.ExpiresAt.IsZero():
			t.Errorf("%s: a session principal must carry its exp", tc.name)
		}
		if tc.token == "not.a.jwt" && called {
			t.Errorf("%s: an invalid token must not cost an identity call", tc.name)
		}
	}
}
