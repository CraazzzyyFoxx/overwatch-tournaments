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
// caller gets the "/" catch-all 404 instead of the handler.
func TestPathNormalisation_ThreeSpellingsOneHandler(t *testing.T) {
	var seen []string
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/v1/auth/me", func(w http.ResponseWriter, r *http.Request) {
		seen = append(seen, r.URL.Path)
		w.WriteHeader(http.StatusOK)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotFound)
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
		if w.Code != http.StatusOK {
			t.Fatalf("%s: status=%d — must reach the typed handler", c.path, w.Code)
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

// Paths that are deliberately outside the version must not be rewritten or
// deprecated — the docs describe the versions.
func TestPathNormalisation_LeavesNonVersionedSurfacesAlone(t *testing.T) {
	var seen string
	h := apiver.Middleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.URL.Path
		w.WriteHeader(http.StatusOK)
	}))
	for _, p := range []string{"/api/docs", "/api/openapi.json"} {
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
