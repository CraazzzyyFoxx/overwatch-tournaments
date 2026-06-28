package edge

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
	d := newTestDispatcher(m, func(*http.Request) (map[string]any, bool) { return identity, true })
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
	d := newTestDispatcher(m, func(*http.Request) (map[string]any, bool) { return nil, false })
	spec := RouteSpec{Method: "GET", Pattern: "/api/v1/admin/x", Queue: "q", Auth: AuthRequired}
	w := serve(d, spec, "GET", "/api/v1/admin/x", "")
	if w.Code != 401 {
		t.Fatalf("code=%d", w.Code)
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
