package metrics

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/prometheus/client_golang/prometheus/testutil"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth/authtest"
)

type fakeRecorder struct{ ids []int64 }

func (f *fakeRecorder) Record(id int64) { f.ids = append(f.ids, id) }

func TestMiddlewareRecordsRequestWithRouteTemplate(t *testing.T) {
	m := New()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/v1/heroes/{id}", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	})
	h := m.Middleware(mux, nil, nil)

	// Two different concrete IDs must collapse to one templated route label.
	for _, id := range []string{"5", "9"} {
		h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/api/v1/heroes/"+id, nil))
	}

	got := testutil.ToFloat64(m.requests.WithLabelValues("/api/v1/heroes/{id}", "GET", "204"))
	if got != 2 {
		t.Fatalf("requests{route=/api/v1/heroes/{id},code=204} = %v, want 2", got)
	}
}

func TestMiddlewareDefaultsStatus200(t *testing.T) {
	m := New()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /ok", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("hi")) // no explicit WriteHeader -> 200
	})
	h := m.Middleware(mux, nil, nil)

	h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/ok", nil))

	if got := testutil.ToFloat64(m.requests.WithLabelValues("/ok", "GET", "200")); got != 1 {
		t.Fatalf("requests{code=200} = %v, want 1", got)
	}
}

func TestMiddlewareRecordsActiveUserFromJWT(t *testing.T) {
	m := New()
	rec := &fakeRecorder{}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /me", func(http.ResponseWriter, *http.Request) {})
	h := m.Middleware(mux, auth.New(authtest.PublicKey), rec)

	authed := httptest.NewRequest(http.MethodGet, "/me", nil)
	authed.Header.Set("Authorization", "Bearer "+authtest.Token("42"))
	h.ServeHTTP(httptest.NewRecorder(), authed)

	// Anonymous request must not be recorded.
	h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/me", nil))

	if len(rec.ids) != 1 || rec.ids[0] != 42 {
		t.Fatalf("recorded ids = %v, want [42]", rec.ids)
	}
}

// Every token net/http accepts as a method used to become its own label value,
// minting series that are never deleted. Non-standard methods collapse to OTHER.
func TestMiddlewareBoundsTheMethodLabel(t *testing.T) {
	m := New()
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNotFound) })
	h := m.Middleware(mux, nil, nil)

	for _, method := range []string{"XREQ123", "XREQ456", http.MethodGet} {
		h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(method, "/nope", nil))
	}

	if got := testutil.ToFloat64(m.requests.WithLabelValues("/", "OTHER", "404")); got != 2 {
		t.Fatalf("requests{method=OTHER} = %v, want 2", got)
	}
	if got := testutil.ToFloat64(m.requests.WithLabelValues("/", "GET", "404")); got != 1 {
		t.Fatalf("requests{method=GET} = %v, want 1", got)
	}
	if n := testutil.CollectAndCount(m.requests); n != 2 {
		t.Fatalf("request series = %d, want 2 (GET + OTHER)", n)
	}
}

// httplog (outside) already parsed the caller; metrics must take that answer,
// anonymous included, rather than verify the same JWT a second time.
func TestMiddlewareReusesTheUserResolvedOutside(t *testing.T) {
	m := New()
	rec := &fakeRecorder{}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /me", func(http.ResponseWriter, *http.Request) {})
	h := m.Middleware(mux, auth.New(authtest.PublicKey), rec)

	bearer := "Bearer " + authtest.Token("42")
	resolved := httptest.NewRequest(http.MethodGet, "/me", nil)
	resolved.Header.Set("Authorization", bearer)
	h.ServeHTTP(httptest.NewRecorder(), resolved.WithContext(auth.WithUser(resolved.Context(), &auth.User{ID: 7})))

	anonymous := httptest.NewRequest(http.MethodGet, "/me", nil)
	anonymous.Header.Set("Authorization", bearer)
	h.ServeHTTP(httptest.NewRecorder(), anonymous.WithContext(auth.WithUser(anonymous.Context(), nil)))

	if len(rec.ids) != 1 || rec.ids[0] != 7 {
		t.Fatalf("recorded ids = %v, want [7] (the context user, no re-parse)", rec.ids)
	}
}

func TestRouteLabel(t *testing.T) {
	cases := map[string]string{
		"GET /api/v1/heroes/{id}": "/api/v1/heroes/{id}",
		"/api/v1/division-grids/": "/api/v1/division-grids/",
		"":                        "unmatched",
	}
	for in, want := range cases {
		if got := routeLabel(in); got != want {
			t.Errorf("routeLabel(%q) = %q, want %q", in, got, want)
		}
	}
}
