package metrics

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
)

// ActiveRecorder records that a user was active. Implementations must be
// non-blocking and safe for concurrent use (active-user counts are best-effort).
type ActiveRecorder interface {
	Record(userID int64)
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

// Middleware instruments the REST mux: it records request count, latency, and
// the authenticated user (resolved from the local JWT, no RPC) for each request.
// It must wrap the ServeMux directly so that, after ServeHTTP, r.Pattern holds
// the matched route template used as a low-cardinality label.
func (m *Metrics) Middleware(next http.Handler, authn *auth.Authenticator, rec ActiveRecorder) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: http.StatusOK}

		next.ServeHTTP(sw, r)

		route := routeLabel(r.Pattern)
		m.requests.WithLabelValues(route, r.Method, strconv.Itoa(sw.status)).Inc()
		m.duration.WithLabelValues(route, r.Method).Observe(time.Since(start).Seconds())

		if rec != nil && authn != nil {
			if u := authn.UserFromRequest(r); u != nil {
				rec.Record(u.ID)
			}
		}
	})
}

// routeLabel turns a ServeMux pattern ("GET /api/v1/heroes/{id}" or "/path")
// into a low-cardinality route label by stripping the leading method.
func routeLabel(pattern string) string {
	if pattern == "" {
		return "unmatched"
	}
	if _, path, found := strings.Cut(pattern, " "); found {
		return path
	}
	return pattern
}
