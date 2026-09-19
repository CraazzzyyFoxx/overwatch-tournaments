package main

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apiver"
)

// The whole point of the unification, end to end through the real middleware
// chain order (apiver outermost, then the mux): three spellings, one handler.
//
// This lives in package main because the wiring order is main's, not any one
// package's — apiver has to see the path before the mux does, or a legacy
// caller gets the "/" frontend catch-all and the gateway<->frontend proxy loop
// that every guard in here exists to prevent.
func TestPathNormalisation_ThreeSpellingsOneHandler(t *testing.T) {
	var seen []string
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/v1/auth/me", func(w http.ResponseWriter, r *http.Request) {
		seen = append(seen, r.URL.Path)
		w.WriteHeader(http.StatusOK)
	})
	mux.HandleFunc("/api/v1/", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		// Standing in for the frontend catch-all: reaching it is the bug.
		w.Header().Set("X-Route", "frontend")
		w.WriteHeader(http.StatusOK)
	})
	h := apiver.Middleware(mux)

	for _, c := range []struct {
		path           string
		wantDeprecated bool
	}{
		{"/api/v1/auth/me", false},
		{"/api/v2/auth/me", false},
		{"/api/auth/me", true},
	} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, c.path, nil))
		if w.Code != http.StatusOK || w.Header().Get("X-Route") == "frontend" {
			t.Fatalf("%s: status=%d route=%q — must reach the typed handler", c.path, w.Code, w.Header().Get("X-Route"))
		}
		if got := w.Header().Get("Deprecation") == "true"; got != c.wantDeprecated {
			t.Errorf("%s: Deprecation=%v, want %v", c.path, got, c.wantDeprecated)
		}
	}
	if len(seen) != 3 {
		t.Fatalf("handler saw %d requests, want 3", len(seen))
	}
	for _, p := range seen {
		if p != "/api/v1/auth/me" {
			t.Errorf("handler saw %q; every spelling must arrive canonical", p)
		}
	}
}

// An unmatched path in a folded-in namespace must land on the single /api/v1/
// guard, whichever spelling it arrived as — never on the frontend catch-all.
func TestPathNormalisation_UnmatchedLegacyHitsTheGuard(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("X-Route", "guard")
		w.WriteHeader(http.StatusNotFound)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("X-Route", "frontend")
		w.WriteHeader(http.StatusOK)
	})
	h := apiver.Middleware(mux)

	for _, p := range []string{
		"/api/auth/nope", "/api/analytics/nope", "/api/balancer/nope",
		"/api/streams/nope", "/api/notifications/nope", "/api/announcements/nope",
		"/api/v1/nope", "/api/v2/nope",
	} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, p, nil))
		if w.Header().Get("X-Route") != "guard" || w.Code != http.StatusNotFound {
			t.Errorf("%s: route=%q status=%d, want the /api/v1/ guard 404",
				p, w.Header().Get("X-Route"), w.Code)
		}
	}
}

// Paths that are deliberately outside the version must not be rewritten or
// deprecated — the docs describe the versions, and /api/health is a probe.
func TestPathNormalisation_LeavesNonVersionedSurfacesAlone(t *testing.T) {
	var seen string
	h := apiver.Middleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.URL.Path
		w.WriteHeader(http.StatusOK)
	}))
	for _, p := range []string{"/api/docs", "/api/openapi.json", "/api/health", "/bff/account/sessions"} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, p, nil))
		if seen != p {
			t.Errorf("%s was rewritten to %q", p, seen)
		}
		if w.Header().Get("Deprecation") != "" {
			t.Errorf("%s marked deprecated", p)
		}
	}
}
