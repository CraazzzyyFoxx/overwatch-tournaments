package tracing_test

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/codes"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/tracing"
)

// setupRecorder installs a recording tracer provider as the global one; it
// must run before tracing.Middleware is constructed (the tracer is captured
// there).
func setupRecorder(t *testing.T) *tracetest.SpanRecorder {
	t.Helper()
	sr := tracetest.NewSpanRecorder()
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithSpanProcessor(sr),
		sdktrace.WithSampler(sdktrace.AlwaysSample()),
	)
	prev := otel.GetTracerProvider()
	otel.SetTracerProvider(tp)
	t.Cleanup(func() { otel.SetTracerProvider(prev) })
	return sr
}

// TestMiddlewareNamesSpanByRoute exercises the production chain
// (tracing -> httplog -> mux) and asserts the span is named by the matched
// route template — which only works if httplog copies r.Pattern back to the
// outer middleware's request pointer after ServeHTTP.
func TestMiddlewareNamesSpanByRoute(t *testing.T) {
	sr := setupRecorder(t)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/v1/heroes/{id}", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	h := tracing.Middleware(httplog.Middleware(mux, logger, nil))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/heroes/42", nil))

	spans := sr.Ended()
	if len(spans) != 1 {
		t.Fatalf("expected 1 span, got %d", len(spans))
	}
	if got, want := spans[0].Name(), "GET /api/v1/heroes/{id}"; got != want {
		t.Errorf("span name = %q, want %q", got, want)
	}
	if got := spans[0].Status().Code; got != codes.Unset {
		t.Errorf("status code = %v, want Unset for a 200", got)
	}
}

func TestMiddlewareMarksServerErrors(t *testing.T) {
	sr := setupRecorder(t)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /boom", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})
	h := tracing.Middleware(mux)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/boom", nil))

	spans := sr.Ended()
	if len(spans) != 1 {
		t.Fatalf("expected 1 span, got %d", len(spans))
	}
	if got := spans[0].Status().Code; got != codes.Error {
		t.Errorf("status code = %v, want Error for a 500", got)
	}
}

func TestMiddlewareUnmatchedRoute(t *testing.T) {
	sr := setupRecorder(t)

	// A bare handler never sets r.Pattern — the span must fall back to the
	// low-cardinality "unmatched" name instead of the raw URL.
	h := tracing.Middleware(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/no/such/route/12345", nil))

	spans := sr.Ended()
	if len(spans) != 1 {
		t.Fatalf("expected 1 span, got %d", len(spans))
	}
	if got, want := spans[0].Name(), "GET unmatched"; got != want {
		t.Errorf("span name = %q, want %q", got, want)
	}
}
