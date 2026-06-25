package metrics

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHandlerExposesGatewayMetrics(t *testing.T) {
	m := New()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /ping", func(http.ResponseWriter, *http.Request) {})
	h := m.Middleware(mux, nil, nil)

	// One request so the request collectors have at least one child series.
	h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/ping", nil))

	rec := httptest.NewRecorder()
	m.Handler().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/metrics", nil))

	if rec.Code != http.StatusOK {
		t.Fatalf("/metrics status = %d, want 200", rec.Code)
	}
	body := rec.Body.String()
	for _, want := range []string{
		"gateway_http_requests_total",
		"gateway_http_request_duration_seconds",
	} {
		if !strings.Contains(body, want) {
			t.Errorf("/metrics output missing %q", want)
		}
	}
}
