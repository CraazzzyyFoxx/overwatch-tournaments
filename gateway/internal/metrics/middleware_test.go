package metrics

import (
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/prometheus/client_golang/prometheus/testutil"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
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
	const secret = "test-secret"
	m := New()
	rec := &fakeRecorder{}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /me", func(http.ResponseWriter, *http.Request) {})
	h := m.Middleware(mux, auth.New(secret), rec)

	authed := httptest.NewRequest(http.MethodGet, "/me", nil)
	authed.Header.Set("Authorization", "Bearer "+signAccessToken(t, secret, 42))
	h.ServeHTTP(httptest.NewRecorder(), authed)

	// Anonymous request must not be recorded.
	h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/me", nil))

	if len(rec.ids) != 1 || rec.ids[0] != 42 {
		t.Fatalf("recorded ids = %v, want [42]", rec.ids)
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

func signAccessToken(t *testing.T, secret string, sub int64) string {
	t.Helper()
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub":  strconv.FormatInt(sub, 10),
		"type": "access",
		"exp":  time.Now().Add(time.Hour).Unix(),
	})
	signed, err := tok.SignedString([]byte(secret))
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	return signed
}
