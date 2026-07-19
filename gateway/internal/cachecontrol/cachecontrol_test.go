package cachecontrol

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func get(t *testing.T, h http.Handler, path string) *httptest.ResponseRecorder {
	t.Helper()
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	return rec
}

// An API response with no upstream Cache-Control must leave with an explicit
// `private, no-store` — the whole point of the middleware: no header means
// intermediaries may apply heuristic caching to viewer-dependent payloads.
func TestStampsBareAPIResponse(t *testing.T) {
	h := Middleware(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{}`))
	}))
	rec := get(t, h, "/api/v1/tournaments/1")
	if got := rec.Header().Get("Cache-Control"); got != directive {
		t.Fatalf("Cache-Control = %q, want %q", got, directive)
	}
}

// A handler that never calls WriteHeader explicitly (implicit 200 via Write)
// must still be stamped: Write goes through the wrapper's WriteHeader.
func TestStampsImplicitWriteHeader(t *testing.T) {
	h := Middleware(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{}`))
	}))
	rec := get(t, h, "/api/v1/tournaments/1")
	if got := rec.Header().Get("Cache-Control"); got != directive {
		t.Fatalf("Cache-Control = %q, want %q", got, directive)
	}
}

// An explicit upstream Cache-Control must win: a backend opting a public
// endpoint into shared caching (e.g. s-maxage) must not be overwritten, and
// the response must not carry two Cache-Control values.
func TestDefersToUpstreamHeader(t *testing.T) {
	const upstream = "public, s-maxage=30"
	h := Middleware(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Cache-Control", upstream)
		w.WriteHeader(http.StatusOK)
	}))
	rec := get(t, h, "/api/v1/tournaments/1")
	values := rec.Header().Values("Cache-Control")
	if len(values) != 1 || values[0] != upstream {
		t.Fatalf("Cache-Control = %v, want exactly [%q]", values, upstream)
	}
}

// Non-API paths (the "/" frontend catch-all: Next HTML, /_next/static) must
// pass through untouched — Next emits its own correct headers there.
func TestSkipsNonAPIPaths(t *testing.T) {
	h := Middleware(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	for _, path := range []string{"/tournaments/1", "/_next/static/chunk.js", "/"} {
		rec := get(t, h, path)
		if got := rec.Header().Get("Cache-Control"); got != "" {
			t.Fatalf("path %s: Cache-Control = %q, want none", path, got)
		}
	}
}

// Error responses (404 guards, 429 from the anon limiter, 5xx) are API
// responses too and must be stamped — a cached error body is as wrong as a
// cached success.
func TestStampsErrorStatuses(t *testing.T) {
	for _, code := range []int{http.StatusNotFound, http.StatusTooManyRequests, http.StatusInternalServerError} {
		h := Middleware(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(code)
		}))
		rec := get(t, h, "/api/v1/tournaments/1")
		if got := rec.Header().Get("Cache-Control"); got != directive {
			t.Fatalf("status %d: Cache-Control = %q, want %q", code, got, directive)
		}
	}
}

// Unwrap must expose the real ResponseWriter so http.ResponseController
// (reverse-proxy flushing) keeps working through the wrapper.
func TestUnwrapExposesUnderlyingWriter(t *testing.T) {
	rec := httptest.NewRecorder()
	s := &stamper{ResponseWriter: rec}
	if s.Unwrap() != rec {
		t.Fatal("Unwrap must return the wrapped ResponseWriter")
	}
}
