package edge

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
)

type mockCaller struct {
	lastQueue string
	lastBody  []byte
	reply     []byte
	err       error
	calls     int
}

func (m *mockCaller) Call(_ context.Context, queue string, body []byte) ([]byte, error) {
	m.calls++
	m.lastQueue = queue
	m.lastBody = body
	return m.reply, m.err
}

func newTestDispatcher(m *mockCaller, identity IdentityResolver) *Dispatcher {
	return New(m, slog.New(slog.NewTextHandler(io.Discard, nil)), identity)
}

func serve(d *Dispatcher, spec RouteSpec, method, target, body string) *httptest.ResponseRecorder {
	mux := http.NewServeMux()
	d.Register(mux, []RouteSpec{spec})
	var r *http.Request
	if body != "" {
		r = httptest.NewRequest(method, target, strings.NewReader(body))
	} else {
		r = httptest.NewRequest(method, target, nil)
	}
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, r)
	return w
}

func TestDispatch_TypedSuccess(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":{"id":5}}`)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/api/v1/tournaments/{id}", Queue: "rpc.tournament.get_tournament", IDParam: "id", Auth: AuthNone}
	w := serve(d, spec, "GET", "/api/v1/tournaments/5", "")
	if w.Code != 200 {
		t.Fatalf("code=%d", w.Code)
	}
	if m.lastQueue != "rpc.tournament.get_tournament" {
		t.Fatalf("queue=%q", m.lastQueue)
	}
	if w.Body.String() != `{"id":5}` {
		t.Fatalf("body=%q", w.Body.String())
	}
	var sent map[string]any
	_ = json.Unmarshal(m.lastBody, &sent)
	if sent["id"] != "5" {
		t.Fatalf("sent id=%v", sent["id"])
	}
}

func TestDispatch_GenericCrudUpdate(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":{"id":5,"name":"X"}}`)}
	identity := map[string]any{"user_id": 1.0, "is_superuser": true}
	d := newTestDispatcher(m, func(*http.Request) (map[string]any, bool, error) { return identity, true, nil })
	spec := RouteSpec{
		Method: "PATCH", Pattern: "/api/v1/admin/teams/{id}", Queue: "rpc.tournament.admin.update",
		Entity: "team", Action: "update", IDParam: "id", Body: true, Auth: AuthRequired,
	}
	w := serve(d, spec, "PATCH", "/api/v1/admin/teams/5", `{"name":"X"}`)
	if w.Code != 200 {
		t.Fatalf("code=%d body=%s", w.Code, w.Body.String())
	}
	var sent map[string]any
	if err := json.Unmarshal(m.lastBody, &sent); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if sent["entity"] != "team" || sent["action"] != "update" || sent["id"] != "5" {
		t.Fatalf("sent=%v", sent)
	}
	if sent["identity"] == nil {
		t.Fatalf("identity not injected: %v", sent)
	}
	payload, ok := sent["payload"].(map[string]any)
	if !ok || payload["name"] != "X" {
		t.Fatalf("payload=%v", sent["payload"])
	}
}

func TestDispatch_AuthRequiredNoIdentity(t *testing.T) {
	m := &mockCaller{}
	d := newTestDispatcher(m, func(*http.Request) (map[string]any, bool, error) { return nil, false, nil })
	spec := RouteSpec{Method: "GET", Pattern: "/api/v1/admin/x", Queue: "q", Auth: AuthRequired}
	w := serve(d, spec, "GET", "/api/v1/admin/x", "")
	if w.Code != 401 {
		t.Fatalf("code=%d", w.Code)
	}
	if m.calls != 0 {
		t.Fatalf("rpc must not be called, calls=%d", m.calls)
	}
}

// TestDispatch_IdentityUnavailable_503WithRetryAfter is the regression for the
// finding: when the identity backend is unavailable (bulkhead shed,
// disconnected, or timed out), the dispatcher must surface a 503 with
// Retry-After, never a 401 — and must never call the route's own RPC.
func TestDispatch_IdentityUnavailable_503WithRetryAfter(t *testing.T) {
	m := &mockCaller{}
	resolverErr := fmt.Errorf("rpc to %q: %w", "rpc.identity.validate_token", rpc.ErrOverloaded)
	d := newTestDispatcher(m, func(*http.Request) (map[string]any, bool, error) { return nil, false, resolverErr })
	spec := RouteSpec{Method: "GET", Pattern: "/api/v1/admin/x", Queue: "q", Auth: AuthRequired}
	w := serve(d, spec, "GET", "/api/v1/admin/x", "")
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("code=%d, want 503", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "1" {
		t.Fatalf("Retry-After=%q, want \"1\"", got)
	}
	if m.calls != 0 {
		t.Fatalf("rpc must not be called, calls=%d", m.calls)
	}
}

// TestDispatch_IdentityUnavailable_AuthOptional_503 asserts the same 503
// behavior holds for AuthOptional routes — an unavailable identity backend is
// still a 503, not a silent fall-through to anonymous.
func TestDispatch_IdentityUnavailable_AuthOptional_503(t *testing.T) {
	m := &mockCaller{}
	resolverErr := fmt.Errorf("rpc to %q: %w", "rpc.identity.validate_token", rpc.ErrOverloaded)
	d := newTestDispatcher(m, func(*http.Request) (map[string]any, bool, error) { return nil, false, resolverErr })
	spec := RouteSpec{Method: "GET", Pattern: "/api/v1/x", Queue: "q", Auth: AuthOptional}
	w := serve(d, spec, "GET", "/api/v1/x", "")
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("code=%d, want 503", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "1" {
		t.Fatalf("Retry-After=%q, want \"1\"", got)
	}
	if m.calls != 0 {
		t.Fatalf("rpc must not be called, calls=%d", m.calls)
	}
}

func TestDispatch_ErrorEnvelope(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":false,"error":{"code":"forbidden","message":"nope"}}`)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", Auth: AuthNone}
	w := serve(d, spec, "GET", "/x", "")
	if w.Code != 403 {
		t.Fatalf("code=%d", w.Code)
	}
	var b map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &b)
	if b["detail"] != "nope" {
		t.Fatalf("detail=%q", b["detail"])
	}
}

func TestDispatch_RPCUnavailable(t *testing.T) {
	m := &mockCaller{err: rpc.ErrNotConnected}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", Auth: AuthNone}
	w := serve(d, spec, "GET", "/x", "")
	if w.Code != 503 {
		t.Fatalf("code=%d", w.Code)
	}
}

// TestDispatch_ClientCanceled_NoTimeout is the regression for OWT-TOURNAMENTS-20K:
// when the caller disconnects mid-RPC, rpc.Call returns context.Canceled. The
// dispatcher must not treat that as a service fault — no 504 (the client is
// gone) and no Error-level log (which would open a Sentry Issue). We can only
// assert the response side here: it must not emit a gateway timeout.
func TestDispatch_ClientCanceled_NoTimeout(t *testing.T) {
	m := &mockCaller{err: fmt.Errorf("rpc to %q: %w", "q", context.Canceled)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", Auth: AuthNone}
	w := serve(d, spec, "GET", "/x", "")
	if w.Code == http.StatusGatewayTimeout {
		t.Fatalf("client cancellation must not produce a 504")
	}
	if w.Body.Len() != 0 {
		t.Fatalf("client cancellation must not write a body, got %q", w.Body.String())
	}
}

func TestDispatch_QueryForwardedAsList(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":[]}`)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/api/v1/tournaments/{id}", Queue: "q", IDParam: "id", Query: []string{"entities", "workspace_id"}, Auth: AuthNone}
	w := serve(d, spec, "GET", "/api/v1/tournaments/5?entities=stages&entities=teams&workspace_id=7", "")
	if w.Code != 200 {
		t.Fatalf("code=%d", w.Code)
	}
	var sent map[string]any
	_ = json.Unmarshal(m.lastBody, &sent)
	q, _ := sent["query"].(map[string]any)
	ents, _ := q["entities"].([]any)
	if len(ents) != 2 || ents[0] != "stages" || ents[1] != "teams" {
		t.Fatalf("entities=%v", q["entities"])
	}
	ws, _ := q["workspace_id"].([]any)
	if len(ws) != 1 || ws[0] != "7" {
		t.Fatalf("workspace_id=%v", q["workspace_id"])
	}
}

func TestDispatch_NoContent(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":null}`)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "DELETE", Pattern: "/x/{id}", Queue: "q", IDParam: "id", Auth: AuthNone, Success: 204}
	w := serve(d, spec, "DELETE", "/x/5", "")
	if w.Code != 204 {
		t.Fatalf("code=%d", w.Code)
	}
	if w.Body.Len() != 0 {
		t.Fatalf("204 must have no body, got %q", w.Body.String())
	}
}

// A 200 with a null `X | None` payload must relay a literal JSON `null` body, not
// an empty one — otherwise callers' response.json() throws "Unexpected end of
// JSON input". Regression for the balancer Form / Google Sheets tabs.
func TestDispatch_NullData_WritesLiteralNull(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":null}`)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/x/{id}", Queue: "q", IDParam: "id", Auth: AuthNone}
	w := serve(d, spec, "GET", "/x/5", "")
	if w.Code != 200 {
		t.Fatalf("code=%d", w.Code)
	}
	if w.Body.String() != "null" {
		t.Fatalf("expected literal null body, got %q", w.Body.String())
	}
	if ct := w.Header().Get("Content-Type"); ct != "application/json" {
		t.Fatalf("content-type=%q", ct)
	}
}

func TestDispatch_Overloaded_503WithRetryAfter(t *testing.T) {
	m := &mockCaller{err: fmt.Errorf("rpc to %q: %w", "q", rpc.ErrOverloaded)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", Auth: AuthNone}
	w := serve(d, spec, "GET", "/x", "")
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("code=%d, want 503", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "1" {
		t.Fatalf("Retry-After=%q, want \"1\"", got)
	}
}

func TestDispatch_Unavailable_HasRetryAfter(t *testing.T) {
	m := &mockCaller{err: rpc.ErrNotConnected}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", Auth: AuthNone}
	w := serve(d, spec, "GET", "/x", "")
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("code=%d, want 503", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "1" {
		t.Fatalf("Retry-After=%q, want \"1\"", got)
	}
}
