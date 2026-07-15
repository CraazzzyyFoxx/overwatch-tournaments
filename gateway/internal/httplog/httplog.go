// Package httplog adds request-scoped structured logging to the gateway: a
// correlation id per request (taken from X-Request-ID / X-Correlation-ID or
// generated), a request-scoped logger stored in the context, and one access-log
// line per request.
package httplog

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/getsentry/sentry-go"
	"go.opentelemetry.io/otel/trace"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
)

const (
	// RequestIDHeader and CorrelationIDHeader carry the correlation id in and out.
	// Both are set so downstream Python services (which read either) and the
	// frontend see the same id.
	RequestIDHeader     = "X-Request-ID"
	CorrelationIDHeader = "X-Correlation-ID"

	// AccessLogAttr marks the single per-request access-log record ("request
	// completed"). It separates that operational line from application logs in
	// Loki, and the observability Sentry bridge keys off it to keep access logs
	// out of Sentry: as Issues they are pure noise (every edge 5xx, including
	// internet vuln-scanner probes against the public IP, would open one), and
	// as Logs they flood ingest at edge throughput. Genuine faults are captured
	// elsewhere (panics via sentryhttp, explicit .Error() calls) and carry no
	// such attr, so they still reach Sentry.
	AccessLogAttr = "access_log"
)

type ctxKey struct{}

type cidKey struct{}

// With returns a context carrying the request-scoped logger.
func With(ctx context.Context, logger *slog.Logger) context.Context {
	return context.WithValue(ctx, ctxKey{}, logger)
}

// From returns the request-scoped logger bound by Middleware, or slog.Default()
// when none is present (e.g. background goroutines).
func From(ctx context.Context) *slog.Logger {
	if l, ok := ctx.Value(ctxKey{}).(*slog.Logger); ok && l != nil {
		return l
	}
	return slog.Default()
}

// WithCorrelationID returns a context carrying the request's correlation id.
func WithCorrelationID(ctx context.Context, cid string) context.Context {
	return context.WithValue(ctx, cidKey{}, cid)
}

// CorrelationIDFromContext returns the correlation id bound by Middleware, or
// "" when none is present. Used by the RPC client to forward the id in
// RabbitMQ message headers.
func CorrelationIDFromContext(ctx context.Context) string {
	if cid, ok := ctx.Value(cidKey{}).(string); ok {
		return cid
	}
	return ""
}

// Middleware assigns/propagates a correlation id, binds a request-scoped logger
// into the context, and emits one access-log line per request. It must wrap the
// REST ServeMux directly (inside the Sentry handler) so that, after ServeHTTP,
// r.Pattern holds the matched route template.
func Middleware(next http.Handler, base *slog.Logger, authn *auth.Authenticator) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()

		cid := CorrelationID(r)
		// Propagate downstream (proxied requests forward these) and echo to the client.
		r.Header.Set(RequestIDHeader, cid)
		r.Header.Set(CorrelationIDHeader, cid)
		w.Header().Set(RequestIDHeader, cid)
		w.Header().Set(CorrelationIDHeader, cid)

		reqLog := base.With(slog.String("correlation_id", cid))
		// trace_id: prefer the OTel span (opened by the tracing middleware, which
		// wraps this one) so Loki's derived TraceID field links to Tempo; fall
		// back to the Sentry span when tracing is disabled. At partial sampling
		// most logged trace_ids have no stored trace — the field is still useful
		// for grepping a request's log lines together.
		if sc := trace.SpanContextFromContext(r.Context()); sc.IsValid() {
			reqLog = reqLog.With(slog.String("trace_id", sc.TraceID().String()))
		} else if span := sentry.SpanFromContext(r.Context()); span != nil {
			reqLog = reqLog.With(slog.String("trace_id", span.TraceID.String()))
		}
		orig := r
		r = r.WithContext(WithCorrelationID(With(r.Context(), reqLog), cid))

		rec := &responseRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r)
		// WithContext made a shallow copy, so the mux set Pattern on OUR copy.
		// Copy it back to the caller's request pointer so outer middleware
		// (tracing) can name its span by the matched route.
		orig.Pattern = r.Pattern

		attrs := []slog.Attr{
			// Marks this as the access log so the Sentry bridge skips it; see
			// AccessLogAttr. Kept first so it is present on every emitted record.
			slog.Bool(AccessLogAttr, true),
			slog.String("method", r.Method),
			slog.String("route", routeLabel(r.Pattern)),
			slog.Int("status", rec.status),
			slog.Int64("duration_ms", time.Since(start).Milliseconds()),
			slog.Int("bytes", rec.bytes),
		}
		// user_id (from the local JWT, no RPC). The token itself is never logged.
		if authn != nil {
			if u := authn.UserFromRequest(r); u != nil {
				attrs = append(attrs, slog.Int64("user_id", u.ID))
			}
		}
		reqLog.LogAttrs(r.Context(), levelForStatus(rec.status), "request completed", attrs...)
	})
}

// CorrelationID returns the request's correlation id: X-Request-ID, else
// X-Correlation-ID, else a freshly generated id. Exported so the WebSocket path
// (which bypasses Middleware) can bind the same id to its connection logger.
func CorrelationID(r *http.Request) string {
	if v := r.Header.Get(RequestIDHeader); v != "" {
		return v
	}
	if v := r.Header.Get(CorrelationIDHeader); v != "" {
		return v
	}
	return newID()
}

func newID() string {
	var b [16]byte
	// crypto/rand.Read never returns an error on supported platforms; the guard
	// exists only for completeness.
	if _, err := rand.Read(b[:]); err != nil {
		return "unknown"
	}
	return hex.EncodeToString(b[:])
}

func levelForStatus(status int) slog.Level {
	switch {
	case status >= 500:
		return slog.LevelError
	case status >= 400:
		return slog.LevelWarn
	default:
		return slog.LevelInfo
	}
}

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

// responseRecorder captures the status code and bytes written. It exposes
// Unwrap so http.ResponseController (used by the reverse proxy to flush) reaches
// the real ResponseWriter.
type responseRecorder struct {
	http.ResponseWriter
	status int
	bytes  int
	wrote  bool
}

func (w *responseRecorder) WriteHeader(code int) {
	if !w.wrote {
		w.status = code
		w.wrote = true
	}
	w.ResponseWriter.WriteHeader(code)
}

func (w *responseRecorder) Write(b []byte) (int, error) {
	if !w.wrote {
		w.status = http.StatusOK
		w.wrote = true
	}
	n, err := w.ResponseWriter.Write(b)
	w.bytes += n
	return n, err
}

func (w *responseRecorder) Unwrap() http.ResponseWriter { return w.ResponseWriter }
