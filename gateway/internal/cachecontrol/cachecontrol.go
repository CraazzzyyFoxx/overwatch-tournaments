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
// Scope: the whole REST mux. The gateway serves only the API (pages and the
// frontend's /bff/* go nginx -> Next directly; nginx applies the same policy
// to /bff/*), so every response it wraps is viewer-dependent API output.
package cachecontrol

import "net/http"

// directive is what an API response with no explicit upstream Cache-Control
// gets: never stored by any cache, shared or private. `private` is technically
// redundant next to `no-store` but is kept as belt-and-braces for
// non-conforming intermediaries that treat unknown/partial directives loosely.
const directive = "private, no-store"

// Middleware wraps next, stamping `Cache-Control: private, no-store` on every
// response whose handler did not set its own Cache-Control.
func Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		next.ServeHTTP(&stamper{ResponseWriter: w}, r)
	})
}

// stamper defers the decision to WriteHeader time: by then the handler has
// populated the header map, so "only if absent" can be judged correctly. It
// exposes Unwrap so http.ResponseController reaches the real ResponseWriter,
// mirroring httplog.responseRecorder.
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
