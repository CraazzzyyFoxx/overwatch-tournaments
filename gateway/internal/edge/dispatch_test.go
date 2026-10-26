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
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apiver"
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

func TestDispatch_V2RelaysEnvelope(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":{"id":5},"warnings":[{"code":"truncated","message":"capped"}]}`)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/api/v1/tournaments/{id}", Queue: "rpc.tournament.get_tournament", IDParam: "id", Auth: AuthNone}
	mux := http.NewServeMux()
	d.Register(mux, []RouteSpec{spec})
	h := apiver.Middleware(mux)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/api/v2/tournaments/5", nil))
	if w.Code != 200 {
		t.Fatalf("code=%d body=%s", w.Code, w.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("json: %v", err)
	}
	if body["ok"] != true {
		t.Fatalf("body=%s", w.Body.String())
	}
	data, _ := body["data"].(map[string]any)
	if data["id"] != float64(5) {
		t.Fatalf("data=%v", body["data"])
	}
}

func TestDispatch_V2ErrorEnvelope(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":false,"error":{"code":"not_found","message":"missing"}}`)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/api/v1/tournaments/{id}", Queue: "rpc.tournament.get_tournament", IDParam: "id", Auth: AuthNone}
	mux := http.NewServeMux()
	d.Register(mux, []RouteSpec{spec})
	h := apiver.Middleware(mux)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/api/v2/tournaments/5", nil))
	if w.Code != 404 {
		t.Fatalf("code=%d body=%s", w.Code, w.Body.String())
	}
	var body map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	if body["ok"] != false {
		t.Fatalf("body=%s", w.Body.String())
	}
	errObj, _ := body["error"].(map[string]any)
	if errObj["code"] != "not_found" {
		t.Fatalf("error=%v", body["error"])
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

// NewRaw injects the identity bytes it is handed verbatim — the resolver's
// cached reply — with no decode/re-marshal: an id past 2^53 survives, and the
// sole workspace still fills the query.
func TestDispatch_RawIdentityInjectedVerbatim(t *testing.T) {
	const payload = `{"user_id":12345678901234567890,"workspaces":[{"workspace_id":7}]}`
	m := &mockCaller{reply: []byte(`{"ok":true,"data":{}}`)}
	d := NewRaw(m, slog.New(slog.NewTextHandler(io.Discard, nil)), func(*http.Request) (Identity, bool, error) {
		return Identity{Payload: json.RawMessage(payload), SoleWorkspaceID: 7}, true, nil
	})
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", Query: []string{"workspace_id"}, Auth: AuthRequired}
	if w := serve(d, spec, "GET", "/x", ""); w.Code != 200 {
		t.Fatalf("code=%d", w.Code)
	}
	var sent struct {
		Identity json.RawMessage     `json:"identity"`
		Query    map[string][]string `json:"query"`
	}
	if err := json.Unmarshal(m.lastBody, &sent); err != nil {
		t.Fatal(err)
	}
	if string(sent.Identity) != payload {
		t.Fatalf("identity = %s, want the cached bytes %s", sent.Identity, payload)
	}
	if got := sent.Query["workspace_id"]; len(got) != 1 || got[0] != "7" {
		t.Fatalf("workspace_id = %v, want [7]", got)
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
	if b["code"] != "forbidden" {
		t.Fatalf("code=%q", b["code"])
	}
}

// identityWith builds an IdentityResolver returning a payload whose workspaces
// carry the given ids — the shape identity-svc dumps (WorkspaceMembership).
func identityWith(workspaceIDs ...int) IdentityResolver {
	ws := make([]any, 0, len(workspaceIDs))
	for _, id := range workspaceIDs {
		ws = append(ws, map[string]any{"workspace_id": float64(id), "slug": "s"})
	}
	return func(*http.Request) (map[string]any, bool, error) {
		return map[string]any{"user_id": float64(1), "workspaces": ws}, true, nil
	}
}

// bodyQuery pulls data["query"] out of the captured RPC request.
func bodyQuery(t *testing.T, m *mockCaller) map[string]any {
	t.Helper()
	var sent map[string]any
	if err := json.Unmarshal(m.lastBody, &sent); err != nil {
		t.Fatalf("rpc body not JSON: %v", err)
	}
	q, _ := sent["query"].(map[string]any)
	return q
}

// A credential pinned to exactly one workspace already names its scope; making
// the caller repeat it in the query string is the first 400 every API-key
// integrator hits (shared/services/workspace_scope.py fails closed).
func TestDispatch_DerivesWorkspaceIDFromSoleWorkspace(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":{}}`)}
	d := newTestDispatcher(m, identityWith(7))
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", Query: []string{"workspace_id"}, Auth: AuthRequired}
	if w := serve(d, spec, "GET", "/x", ""); w.Code != 200 {
		t.Fatalf("code=%d", w.Code)
	}
	q := bodyQuery(t, m)
	got, _ := q["workspace_id"].([]any)
	if len(got) != 1 || got[0] != "7" {
		t.Fatalf("query.workspace_id=%#v, want [\"7\"]", q["workspace_id"])
	}
}

func TestDispatch_ExplicitWorkspaceIDWins(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":{}}`)}
	d := newTestDispatcher(m, identityWith(7))
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", AllQuery: true, Auth: AuthRequired}
	serve(d, spec, "GET", "/x?workspace_id=9", "")
	q := bodyQuery(t, m)
	got, _ := q["workspace_id"].([]any)
	if len(got) != 1 || got[0] != "9" {
		t.Fatalf("query.workspace_id=%#v, want [\"9\"]", q["workspace_id"])
	}
}

// Two workspaces are ambiguous: guessing one would silently scope a read to the
// wrong tenant, so the fail-closed 400 from the worker stays the right answer.
func TestDispatch_NoDeriveWhenWorkspaceAmbiguous(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":{}}`)}
	d := newTestDispatcher(m, identityWith(7, 8))
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", AllQuery: true, Auth: AuthRequired}
	serve(d, spec, "GET", "/x", "")
	if q := bodyQuery(t, m); q["workspace_id"] != nil {
		t.Fatalf("query.workspace_id=%#v, want absent", q["workspace_id"])
	}
}

// A route that never declared workspace_id must not grow a surprise param.
func TestDispatch_NoDeriveWhenRouteIgnoresWorkspace(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":{}}`)}
	d := newTestDispatcher(m, identityWith(7))
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", Auth: AuthRequired}
	serve(d, spec, "GET", "/x", "")
	if q := bodyQuery(t, m); q["workspace_id"] != nil {
		t.Fatalf("query=%#v, want no workspace_id", q)
	}
}

// A worker cannot set HTTP headers, so its 429 carries the budget in the
// envelope. Dropping it left API clients with no retry signal at all.
func TestDispatch_RateLimitedRelaysRetryAfter(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":false,"error":{"code":"rate_limited","message":"slow down","details":{"retry_after":30}}}`)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/x", Queue: "q", Auth: AuthNone}
	w := serve(d, spec, "GET", "/x", "")
	if w.Code != 429 {
		t.Fatalf("code=%d", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "30" {
		t.Fatalf("Retry-After=%q, want 30", got)
	}
}

func TestDispatch_ErrorRelaysStructuredFields(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":false,"error":{"code":"unprocessable","message":"bad input","details":{"fields":[{"field":"name","msg":"required","code":"missing"}]}}}`)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "POST", Pattern: "/x", Queue: "q", Auth: AuthNone}
	w := serve(d, spec, "POST", "/x", "")
	if w.Code != 422 {
		t.Fatalf("code=%d", w.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("body not JSON: %v", err)
	}
	if body["detail"] != "bad input" || body["code"] != "unprocessable" {
		t.Fatalf("body=%#v", body)
	}
	fields, _ := body["fields"].([]any)
	if len(fields) != 1 {
		t.Fatalf("fields=%#v, want 1 entry", body["fields"])
	}
	first, _ := fields[0].(map[string]any)
	if first["code"] != "missing" || first["field"] != "name" {
		t.Fatalf("fields[0]=%#v", first)
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

// deadlineCaller records the context deadline the dispatcher applied to the RPC.
type deadlineCaller struct {
	reply    []byte
	deadline time.Time
	hasDL    bool
}

func (m *deadlineCaller) Call(ctx context.Context, _ string, _ []byte) ([]byte, error) {
	m.deadline, m.hasDL = ctx.Deadline()
	return m.reply, nil
}

// TestDispatch_PerRouteTimeout asserts RouteSpec.Timeout overrides the blanket
// 120s default for the RPC context deadline (which also drives the AMQP TTL +
// x-deadline-ms propagation, see rpc/deadline.go), and that a zero Timeout
// keeps the default.
func TestDispatch_PerRouteTimeout(t *testing.T) {
	cases := []struct {
		name     string
		timeout  time.Duration
		min, max time.Duration
	}{
		{name: "override", timeout: 15 * time.Second, min: 10 * time.Second, max: 16 * time.Second},
		{name: "default", timeout: 0, min: 115 * time.Second, max: defaultRPCTimeout + time.Second},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			m := &deadlineCaller{reply: []byte(`{"ok":true,"data":{}}`)}
			d := New(m, slog.New(slog.NewTextHandler(io.Discard, nil)), nil)
			spec := RouteSpec{Method: "GET", Pattern: "/api/v1/things", Queue: "rpc.q", Timeout: tc.timeout}

			mux := http.NewServeMux()
			d.Register(mux, []RouteSpec{spec})
			start := time.Now()
			w := httptest.NewRecorder()
			mux.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/things", nil))

			if w.Code != http.StatusOK {
				t.Fatalf("status = %d", w.Code)
			}
			if !m.hasDL {
				t.Fatal("rpc context must carry a deadline")
			}
			got := m.deadline.Sub(start)
			if got < tc.min || got > tc.max {
				t.Fatalf("deadline %v outside [%v, %v]", got, tc.min, tc.max)
			}
		})
	}
}

// Every worker's record_audit reads data["ip_address"]/data["user_agent"]. Only
// the identity handlers used to stamp them, so audit rows from app-service and
// tournament-service -- the CRUD engine and every registration mutation --
// stored NULL for both and the journal could not say where a change came from.
// The key names are load-bearing: a synonym silently drops the forensics again.
func TestDispatch_ForwardsTrustedClientMeta(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":{}}`)}
	d := newTestDispatcher(m, nil)
	spec := RouteSpec{Method: "GET", Pattern: "/api/v1/things", Queue: "rpc.q", Auth: AuthNone}

	mux := http.NewServeMux()
	d.Register(mux, []RouteSpec{spec})
	r := httptest.NewRequest("GET", "/api/v1/things", nil)
	r.RemoteAddr = "127.0.0.1:1234" // a trusted proxy: forwarding headers from other peers are ignored
	r.Header.Set("X-Real-IP", "203.0.113.7")
	r.Header.Set("User-Agent", "UA/1")
	mux.ServeHTTP(httptest.NewRecorder(), r)

	var sent map[string]any
	if err := json.Unmarshal(m.lastBody, &sent); err != nil {
		t.Fatal(err)
	}
	if sent["ip_address"] != "203.0.113.7" {
		t.Fatalf("ip_address = %v", sent["ip_address"])
	}
	if sent["user_agent"] != "UA/1" {
		t.Fatalf("user_agent = %v", sent["user_agent"])
	}
}

// The recorded origin of a mutation must not be something its author can choose.
// The body lands under data["payload"], so body values can never reach the keys
// the workers read -- and the left-most X-Forwarded-For hop, which the client
// controls, must lose to the nginx-set X-Real-IP.
func TestDispatch_ClientCannotForgeClientMeta(t *testing.T) {
	m := &mockCaller{reply: []byte(`{"ok":true,"data":{}}`)}
	d := newTestDispatcher(m, func(*http.Request) (map[string]any, bool, error) {
		return map[string]any{"user_id": 1.0}, true, nil
	})
	spec := RouteSpec{Method: "POST", Pattern: "/api/v1/things", Queue: "rpc.q", Body: true, Auth: AuthRequired}

	mux := http.NewServeMux()
	d.Register(mux, []RouteSpec{spec})
	r := httptest.NewRequest("POST", "/api/v1/things",
		strings.NewReader(`{"ip_address":"6.6.6.6","user_agent":"forged"}`))
	r.RemoteAddr = "127.0.0.1:1234" // a trusted proxy: forwarding headers from other peers are ignored
	r.Header.Set("X-Real-IP", "203.0.113.7")
	r.Header.Set("X-Forwarded-For", "6.6.6.6, 203.0.113.7")
	r.Header.Set("User-Agent", "UA/1")
	mux.ServeHTTP(httptest.NewRecorder(), r)

	var sent map[string]any
	if err := json.Unmarshal(m.lastBody, &sent); err != nil {
		t.Fatal(err)
	}
	if sent["ip_address"] != "203.0.113.7" {
		t.Fatalf("ip_address = %v, want the nginx-trusted hop", sent["ip_address"])
	}
	if sent["user_agent"] != "UA/1" {
		t.Fatalf("user_agent = %v, want the real header", sent["user_agent"])
	}
	// The forged values are still visible where they belong -- inside the body
	// the worker validates -- and nowhere else.
	payload, _ := sent["payload"].(map[string]any)
	if payload["ip_address"] != "6.6.6.6" {
		t.Fatalf("payload lost the caller's own body: %v", sent["payload"])
	}
}

// The body rides under data["payload"] byte for byte. A lone Decode used to
// accept trailing data (`{"name":"X"} garbage` still ran the mutation), and the
// map[string]any round trip rounded integers past 2^53 through float64.
func TestDispatch_BodyRelayedVerbatim(t *testing.T) {
	spec := RouteSpec{Method: "POST", Pattern: "/x", Queue: "q", Body: true, Auth: AuthNone}
	for _, tc := range []struct {
		name, body string
		code       int
		payload    string // exact payload bytes on the RPC message; "" = no call
	}{
		{"object", ` {"name":"X"} `, 200, `{"name":"X"}`},
		{"big int byte-exact", `{"id":12345678901234567891}`, 200, `{"id":12345678901234567891}`},
		{"empty body", "", 200, `{}`},
		{"null", `null`, 200, `null`},
		{"trailing garbage", `{"name":"X"} garbage`, 400, ""},
		{"second value", `{"a":1}{"b":2}`, 400, ""},
		{"stray closer", `{"a":1}}`, 400, ""},
		{"array", `[1]`, 400, ""},
		{"malformed", `{"a":`, 400, ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			m := &mockCaller{reply: []byte(`{"ok":true,"data":{}}`)}
			w := serve(newTestDispatcher(m, nil), spec, "POST", "/x", tc.body)
			if w.Code != tc.code {
				t.Fatalf("code=%d want %d (%s)", w.Code, tc.code, w.Body.String())
			}
			if tc.payload == "" {
				if m.calls != 0 {
					t.Fatal("a rejected body still reached the RPC")
				}
				return
			}
			var sent struct {
				Payload json.RawMessage `json:"payload"`
			}
			if err := json.Unmarshal(m.lastBody, &sent); err != nil {
				t.Fatal(err)
			}
			if string(sent.Payload) != tc.payload {
				t.Fatalf("payload=%s want %s", sent.Payload, tc.payload)
			}
		})
	}
}

// Over the cap is a 413. The old LimitReader truncated silently, so an
// oversized object surfaced as a malformed-JSON 400.
func TestDispatch_OversizedBody413(t *testing.T) {
	m := &mockCaller{}
	spec := RouteSpec{Method: "POST", Pattern: "/x", Queue: "q", Body: true, Auth: AuthNone}
	body := `{"a":"` + strings.Repeat("x", maxBody) + `"}`
	w := serve(newTestDispatcher(m, nil), spec, "POST", "/x", body)
	if w.Code != http.StatusRequestEntityTooLarge || m.calls != 0 {
		t.Fatalf("code=%d calls=%d, want 413 and no RPC", w.Code, m.calls)
	}
}
