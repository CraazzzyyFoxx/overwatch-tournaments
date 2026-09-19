package apiver

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestRewriteVersion(t *testing.T) {
	cases := []struct {
		in   string
		want string
		ok   bool
	}{
		{"/api/v1/heroes", "/api/v1/heroes", false},
		{"/api/v2", "/api/v1/", true},
		{"/api/v2/", "/api/v1/", true},
		{"/api/v2/heroes", "/api/v1/heroes", true},
		{"/api/v2/admin/users/5", "/api/v1/admin/users/5", true},
		// v2 now reaches the folded-in domains too: the route table is one table.
		{"/api/v2/auth/me", "/api/v1/auth/me", true},
		{"/api/v1/auth/me", "/api/v1/auth/me", false},
	}
	for _, tc := range cases {
		got, ok := rewriteVersion(tc.in)
		if ok != tc.ok || got != tc.want {
			t.Errorf("rewriteVersion(%q)=(%q,%v) want (%q,%v)", tc.in, got, ok, tc.want, tc.ok)
		}
	}
}

func TestRewriteLegacy(t *testing.T) {
	cases := []struct {
		in   string
		want string
		ok   bool
	}{
		{"/api/auth/me", "/api/v1/auth/me", true},
		{"/api/auth", "/api/v1/auth", true},
		{"/api/analytics/streaks", "/api/v1/analytics/streaks", true},
		{"/api/balancer/tournaments/7/teams/import", "/api/v1/balancer/tournaments/7/teams/import", true},
		{"/api/streams/tournament/7", "/api/v1/streams/tournament/7", true},
		{"/api/notifications", "/api/v1/notifications", true},
		{"/api/notifications/read", "/api/v1/notifications/read", true},
		{"/api/announcements/active", "/api/v1/announcements/active", true},
		// Segment-aware: a longer segment that merely starts with a legacy name
		// is a different resource and must be left alone (it 404s on its own).
		{"/api/authx/me", "/api/authx/me", false},
		{"/api/balancerz", "/api/balancerz", false},
		// Already canonical, and the docs surface, are never touched.
		{"/api/v1/auth/me", "/api/v1/auth/me", false},
		{"/api/docs", "/api/docs", false},
		{"/api/openapi.json", "/api/openapi.json", false},
		{"/api/health", "/api/health", false},
	}
	for _, tc := range cases {
		got, ok := rewriteLegacy(tc.in)
		if ok != tc.ok || got != tc.want {
			t.Errorf("rewriteLegacy(%q)=(%q,%v) want (%q,%v)", tc.in, got, ok, tc.want, tc.ok)
		}
	}
}

// Every legacy prefix must land inside the version, at the same last segment.
// A typo in the table (`/api/v1/auths`) would otherwise 404 a live integration.
func TestLegacyPrefixesAreCanonical(t *testing.T) {
	for _, l := range LegacyPrefixes {
		want := "/api/v1" + l.From[len("/api"):]
		if l.To != want {
			t.Errorf("LegacyPrefixes: %q -> %q, want %q", l.From, l.To, want)
		}
	}
}

func TestMiddleware_RewritesAndFlags(t *testing.T) {
	var sawPath string
	var sawWant, sawWriter bool
	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sawPath = r.URL.Path
		sawWant = Want(r)
		sawWriter = WantWriter(w)
		w.WriteHeader(http.StatusNoContent)
	})
	h := Middleware(inner)

	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/v2/heroes/1", nil))
	if sawPath != "/api/v1/heroes/1" || !sawWant || !sawWriter {
		t.Fatalf("path=%q want=%v writer=%v", sawPath, sawWant, sawWriter)
	}

	sawPath, sawWant, sawWriter = "", false, false
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/v1/heroes/1", nil))
	if sawPath != "/api/v1/heroes/1" || sawWant || sawWriter {
		t.Fatalf("v1 leaked v2: path=%q want=%v writer=%v", sawPath, sawWant, sawWriter)
	}
}

// A legacy caller must reach the canonical handler AND be told the path is
// going away — a rewrite with no Sunset is a migration nobody ever performs.
func TestMiddleware_LegacyRewriteIsAnnounced(t *testing.T) {
	var sawPath string
	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sawPath = r.URL.Path
		w.WriteHeader(http.StatusOK)
	})
	h := Middleware(inner)

	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/api/auth/login", nil))

	if sawPath != "/api/v1/auth/login" {
		t.Fatalf("handler saw %q, want the canonical path", sawPath)
	}
	if got := w.Header().Get("Deprecation"); got != "true" {
		t.Errorf("Deprecation = %q, want \"true\"", got)
	}
	if got := w.Header().Get("Sunset"); got != SunsetDate {
		t.Errorf("Sunset = %q, want %q", got, SunsetDate)
	}
	if got := w.Header().Get("Link"); got != `</api/v1/auth/login>; rel="successor-version"` {
		t.Errorf("Link = %q", got)
	}
}

// The canonical path must NOT be marked deprecated. Stamping every request
// would make the header meaningless and, worse, tell correct clients to move.
func TestMiddleware_CanonicalIsNotDeprecated(t *testing.T) {
	h := Middleware(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	for _, p := range []string{"/api/v1/auth/login", "/api/v2/auth/login", "/api/v1/heroes"} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest(http.MethodPost, p, nil))
		if w.Header().Get("Deprecation") != "" || w.Header().Get("Sunset") != "" {
			t.Errorf("%s carries deprecation headers", p)
		}
	}
}

// A legacy v2 request is both rewrites at once: version first, then namespace.
func TestMiddleware_LegacyUnderV2(t *testing.T) {
	var sawPath string
	var sawWant bool
	h := Middleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sawPath = r.URL.Path
		sawWant = Want(r)
		w.WriteHeader(http.StatusOK)
	}))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/v2/auth/me", nil))
	if sawPath != "/api/v1/auth/me" || !sawWant {
		t.Fatalf("path=%q v2=%v", sawPath, sawWant)
	}
	if w.Header().Get("Deprecation") != "" {
		t.Error("/api/v2/auth/me is canonical under v2 and must not be deprecated")
	}
}
