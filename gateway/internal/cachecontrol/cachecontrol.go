// Package cachecontrol stamps an explicit Cache-Control directive on API
// responses that would otherwise carry none.
//
// Today every /api/* response leaves the gateway without any Cache-Control
// header (verified against the backend services: none of them set one). An
// absent header is not "no caching" — it is *undefined* caching: RFC 9111
// allows intermediaries to apply heuristic freshness, and corporate/transparent
// proxies do. API payloads here are viewer-dependent (workspace scoping,
// hidden-tournament gates, preview allowlists), so an intermediary serving one
// viewer's cached body to another would be a correctness and privacy bug.
// `private, no-store` closes that gray zone explicitly.
//
// The header is set only when the upstream response does NOT already carry a
// Cache-Control of its own. This keeps the door open for a backend to opt a
// deliberately-public endpoint into shared caching later (e.g.
// `public, s-maxage=30` on a public tournament read) without touching the
// gateway — the middleware defers to any explicit upstream decision.
//
// Scope: paths under /api/ only. The "/" frontend catch-all (Next.js HTML,
// /_next/static assets) is untouched — Next already emits correct headers
// there (`no-store` for dynamic HTML, `immutable` for hashed static assets),
// and stamping those would either duplicate or fight them.
package cachecontrol

import (
	"net/http"
	"strings"
)

// directive is what an API response with no explicit upstream Cache-Control
// gets: never stored by any cache, shared or private. `private` is technically
// redundant next to `no-store` but is kept as belt-and-braces for
// non-conforming intermediaries that treat unknown/partial directives loosely.
const directive = "private, no-store"

// Middleware wraps next, stamping `Cache-Control: private, no-store` on every
// /api/* response whose handler (or proxied upstream) did not set its own
// Cache-Control. Non-API paths pass through with the original ResponseWriter —
// zero overhead for the frontend proxy and static assets.
func Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasPrefix(r.URL.Path, "/api/") {
			next.ServeHTTP(w, r)
			return
		}
		next.ServeHTTP(&stamper{ResponseWriter: w}, r)
	})
}

// stamper defers the decision to WriteHeader time: by then the handler (or the
// reverse proxy copying upstream headers) has populated the header map, so
// "only if absent" can be judged correctly. It exposes Unwrap so
// http.ResponseController (used by the reverse proxy to flush) reaches the
// real ResponseWriter, mirroring httplog.responseRecorder.
type stamper struct {
	http.ResponseWriter
	wroteHeader bool
}

func (s *stamper) WriteHeader(code int) {
	if !s.wroteHeader {
		s.wroteHeader = true
		if s.Header().Get("Cache-Control") == "" {
			s.Header().Set("Cache-Control", directive)
		}
	}
	s.ResponseWriter.WriteHeader(code)
}

func (s *stamper) Write(b []byte) (int, error) {
	if !s.wroteHeader {
		s.WriteHeader(http.StatusOK)
	}
	return s.ResponseWriter.Write(b)
}

func (s *stamper) Unwrap() http.ResponseWriter { return s.ResponseWriter }
