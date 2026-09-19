// Package apiver normalises every inbound API path onto the one canonical
// route table before routing, and marks v2 requests so JSON writers emit the
// RPC envelope instead of unwrapping data.
//
// The canonical shape is `/api/v{n}/<domain>/...` — one version axis, always the
// second segment. Two rewrites feed it:
//
//	/api/v2/...   -> /api/v1/...   plus the envelope flag. v1 stays the
//	                               unwrapped FastAPI-shaped contract; v2 is the
//	                               same handlers and HTTP status with
//	                               {ok, data, warnings?} / {ok:false, error}.
//	/api/auth/... -> /api/v1/auth/...   and the same for the other five
//	                               namespaces that used to sit beside the
//	                               version instead of inside it. Legacy only:
//	                               the response carries Deprecation/Sunset.
//
// Doing both here means the route tables, the OpenAPI specs and the response
// cache only ever see canonical paths, and an unmatched legacy path lands on
// the single `/api/v1/` 404 guard instead of needing a guard per namespace.
package apiver

import (
	"context"
	"net/http"
	"strings"
)

type ctxKey struct{}

// flagWriter marks a ResponseWriter as v2 so apierr can pick the envelope
// body without threading *http.Request through every writeDetail.
type flagWriter struct{ http.ResponseWriter }

func (w *flagWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }

// LegacyPrefixes are the namespaces that used to sit beside the version
// (`/api/auth/me`) and now live inside it (`/api/v1/auth/me`). Each entry is
// matched segment-wise, so `/api/authx` is not `/api/auth`.
//
// This table is the compatibility contract. It is exported because
// docs/frontend-zones-adjacent documentation and the guard tests assert against
// it rather than re-listing the prefixes.
var LegacyPrefixes = []struct{ From, To string }{
	{"/api/auth", "/api/v1/auth"},
	{"/api/analytics", "/api/v1/analytics"},
	{"/api/balancer", "/api/v1/balancer"},
	{"/api/streams", "/api/v1/streams"},
	{"/api/notifications", "/api/v1/notifications"},
	{"/api/announcements", "/api/v1/announcements"},
}

// SunsetDate is when the legacy prefixes stop being served, as an HTTP-date
// (RFC 8594 requires that format, not ISO-8601). Six months from the cutover:
// long enough for an integration that only polls monthly to see the header
// twice, short enough that the table does not become permanent.
const SunsetDate = "Thu, 01 Apr 2027 00:00:00 GMT"

// Want reports whether r is a v2 API request (path was /api/v2...).
func Want(r *http.Request) bool {
	if r == nil {
		return false
	}
	v, _ := r.Context().Value(ctxKey{}).(bool)
	return v
}

// WantWriter reports whether w (or something it unwraps to) is the v2 flag.
func WantWriter(w http.ResponseWriter) bool {
	for w != nil {
		if _, ok := w.(*flagWriter); ok {
			return true
		}
		u, ok := w.(interface{ Unwrap() http.ResponseWriter })
		if !ok {
			return false
		}
		w = u.Unwrap()
	}
	return false
}

// Middleware rewrites the request path onto the canonical table and stamps the
// writer + request context for v2. Unmatched paths hit the existing `/api/v1/`
// 404 guard, whichever spelling they arrived as.
func Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		orig := r
		if np, ok := rewriteVersion(r.URL.Path); ok {
			r = r.WithContext(context.WithValue(r.Context(), ctxKey{}, true))
			r.URL.Path = np
			w = &flagWriter{w}
		}
		if np, ok := rewriteLegacy(r.URL.Path); ok {
			// Headers are set before delegating: the handler populates the map
			// but never clears it, so these survive whatever status it writes.
			w.Header().Set("Deprecation", "true")
			w.Header().Set("Sunset", SunsetDate)
			w.Header().Set("Link", "<"+np+">; rel=\"successor-version\"")
			r = r.Clone(r.Context())
			r.URL.Path = np
		}
		next.ServeHTTP(w, r)
		orig.Pattern = r.Pattern
	})
}

func rewriteVersion(p string) (string, bool) {
	switch {
	case p == "/api/v2":
		return "/api/v1/", true
	case strings.HasPrefix(p, "/api/v2/"):
		return "/api/v1/" + strings.TrimPrefix(p, "/api/v2/"), true
	default:
		return p, false
	}
}

func rewriteLegacy(p string) (string, bool) {
	for _, l := range LegacyPrefixes {
		if p == l.From {
			return l.To, true
		}
		if strings.HasPrefix(p, l.From+"/") {
			return l.To + strings.TrimPrefix(p, l.From), true
		}
	}
	return p, false
}
