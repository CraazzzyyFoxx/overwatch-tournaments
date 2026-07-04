package tracing

import (
	"net/http"
	"strings"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/codes"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace"
)

// Middleware opens one SERVER span per REST request. It deliberately does NOT
// use otelhttp: the low-cardinality span name is the matched ServeMux route
// template (r.Pattern), which only exists after the inner mux has run — the
// same post-ServeHTTP trick the metrics middleware uses. It relies on httplog
// copying r.Pattern back to this middleware's request pointer.
//
// Incoming traceparent headers are intentionally ignored: the gateway is the
// public edge, and honoring client-supplied context would let clients force
// sampling decisions or stitch into arbitrary traces. Gateway spans are roots.
func Middleware(next http.Handler) http.Handler {
	tracer := otel.Tracer("gateway/http")
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx, span := tracer.Start(r.Context(), r.Method,
			trace.WithSpanKind(trace.SpanKindServer),
			trace.WithAttributes(
				semconv.HTTPRequestMethodKey.String(r.Method),
				semconv.URLPath(r.URL.Path),
			),
		)
		defer span.End()

		r = r.WithContext(ctx)
		sw := &statusWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(sw, r)

		route := routeLabel(r.Pattern)
		span.SetName(r.Method + " " + route)
		span.SetAttributes(
			semconv.HTTPRoute(route),
			semconv.HTTPResponseStatusCode(sw.status),
		)
		// Semconv for SERVER spans: only 5xx marks the span as errored (4xx is a
		// client problem, not a service failure).
		if sw.status >= 500 {
			span.SetStatus(codes.Error, http.StatusText(sw.status))
		}
	})
}

// statusWriter captures the response status code. It exposes Unwrap so
// http.ResponseController (used by the reverse proxy for flushing) reaches the
// real ResponseWriter.
type statusWriter struct {
	http.ResponseWriter
	status int
	wrote  bool
}

func (w *statusWriter) WriteHeader(code int) {
	if !w.wrote {
		w.status = code
		w.wrote = true
	}
	w.ResponseWriter.WriteHeader(code)
}

func (w *statusWriter) Write(b []byte) (int, error) {
	if !w.wrote {
		w.status = http.StatusOK
		w.wrote = true
	}
	return w.ResponseWriter.Write(b)
}

func (w *statusWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }

// routeLabel strips the leading method from a ServeMux pattern
// ("GET /api/v1/x/{id}" -> "/api/v1/x/{id}").
func routeLabel(pattern string) string {
	if pattern == "" {
		return "unmatched"
	}
	if _, path, found := strings.Cut(pattern, " "); found {
		return path
	}
	return pattern
}
