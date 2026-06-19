package edge_test

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/app"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/tournament"
)

// errCaller stands in for the RPC client; routing assertions never need a real
// reply (the cases we check resolve before any RPC call).
type errCaller struct{}

func (errCaller) Call(_ context.Context, _ string, _ []byte) ([]byte, error) {
	return nil, context.Canceled
}

func marker(name string) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("X-Route", name)
		w.WriteHeader(http.StatusOK)
	}
}

// buildGuardedMux mirrors gateway/cmd/gateway/main.go's /api/v1 wiring. Building
// it must NOT panic — a ServeMux pattern conflict would crash the gateway at
// startup. /api/v1/core/* proxies to app-service; any OTHER unmatched /api/v1/*
// must hit the /api/v1/ guard (404), never the "/" frontend catch-all (which
// rewrites /api/v1/* back to the gateway -> infinite proxy loop).
func buildGuardedMux(t *testing.T) *http.ServeMux {
	t.Helper()
	d := edge.New(errCaller{}, slog.New(slog.NewTextHandler(io.Discard, nil)), nil)
	mux := http.NewServeMux()
	d.Register(mux, tournament.PublicReadRoutes)
	d.Register(mux, tournament.AdminCrudRoutes)
	d.Register(mux, tournament.AdminMiscRoutes)
	d.Register(mux, tournament.RegistrationAdminRoutes)
	d.Register(mux, tournament.IntegrationsRoutes)
	d.Register(mux, tournament.PublicWriteRoutes)
	mux.Handle("/api/v1/division-grids/", d.Subtree(tournament.DivisionGridRoutes))
	mux.Handle("/api/v1/admin/stages/", d.Subtree(tournament.StageSubtreeRoutes))
	// app-service public reads (typed RPC) + achievements get subtree. Registering
	// these must NOT panic — /users/{name} vs /users/{id}/... and the achievements
	// /{id}/users vs /user/{user_id} ambiguity are the cases that would conflict.
	d.Register(mux, app.ReadRoutes)
	d.Register(mux, app.WorkspaceWriteRoutes)
	mux.Handle("/api/v1/core/achievements/", d.Subtree(app.AchievementsSubtreeRoutes))
	mux.Handle("/api/v1/core/", marker("core"))
	mux.HandleFunc("/api/v1/", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("X-Route", "guard")
		w.WriteHeader(http.StatusNotFound)
	})
	mux.Handle("/", marker("frontend"))
	return mux
}

func TestApiV1Guard_NoConflictAndNoLoop(t *testing.T) {
	mux := buildGuardedMux(t) // panics here on any ServeMux pattern conflict
	srv := httptest.NewServer(mux)
	defer srv.Close()

	cases := []struct {
		name      string
		method    string
		path      string
		wantRoute string // "" => expect the /api/v1/ guard 404
	}{
		{"unknown top-level api path", "GET", "/api/v1/does-not-exist", ""},
		{"deep unmatched tournament path", "GET", "/api/v1/tournaments/123/nope", ""},
		{"unmigrated app path still proxies", "GET", "/api/v1/core/matches/1/log", "core"},
		{"unmigrated app write still proxies", "POST", "/api/v1/core/assets/achievements/x", "core"},
		{"non-api path hits frontend", "GET", "/users/someone", "frontend"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			req, _ := http.NewRequest(c.method, srv.URL+c.path, nil)
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatalf("%s %s: %v", c.method, c.path, err)
			}
			defer resp.Body.Close()
			route := resp.Header.Get("X-Route")
			if c.wantRoute == "" {
				if resp.StatusCode != http.StatusNotFound || route != "guard" {
					t.Fatalf("%s %s: got route=%q status=%d, want the /api/v1/ guard (404). "+
						"Falling through to the frontend would re-create the proxy loop.",
						c.method, c.path, route, resp.StatusCode)
				}
				return
			}
			if route != c.wantRoute {
				t.Fatalf("%s %s: routed to %q, want %q", c.method, c.path, route, c.wantRoute)
			}
		})
	}
}

// TestApiV1Core_MigratedReadsHitDispatcher asserts the migrated app-service read
// patterns win over the /api/v1/core proxy (ServeMux specificity) and reach the
// typed dispatcher rather than the "core" proxy / frontend / guard. With the stub
// RPC caller the dispatcher returns 504, so a migrated path yields an empty
// X-Route (typed handler) — never "core"/"frontend"/"guard".
func TestApiV1Core_MigratedReadsHitDispatcher(t *testing.T) {
	mux := buildGuardedMux(t)
	srv := httptest.NewServer(mux)
	defer srv.Close()

	paths := []string{
		"/api/v1/core/heroes",
		"/api/v1/core/heroes/5",
		"/api/v1/core/heroes/lookup",
		"/api/v1/core/heroes/5/leaderboard",
		"/api/v1/core/heroes/statistics/playtime",
		"/api/v1/core/maps",
		"/api/v1/core/maps/5",
		"/api/v1/core/maps/lookup",
		"/api/v1/core/gamemodes/5",
		"/api/v1/core/achievements",
		"/api/v1/core/achievements/5",
		"/api/v1/core/achievements/5/users",
		"/api/v1/core/achievements/user/7",
		"/api/v1/core/users",
		"/api/v1/core/users/search",
		"/api/v1/core/users/overview",
		"/api/v1/core/users/overview/stats",
		"/api/v1/core/users/5/profile",
		"/api/v1/core/users/5/tournaments/9",
		"/api/v1/core/users/5/maps/summary",
		"/api/v1/core/users/someblizzname",
		"/api/v1/core/statistics/dashboard",
		"/api/v1/core/statistics/won-maps",
		"/api/v1/core/workspaces",
		"/api/v1/core/workspaces/5",
	}
	for _, p := range paths {
		t.Run(p, func(t *testing.T) {
			resp, err := http.Get(srv.URL + p)
			if err != nil {
				t.Fatalf("GET %s: %v", p, err)
			}
			defer resp.Body.Close()
			switch resp.Header.Get("X-Route") {
			case "core", "frontend", "guard":
				t.Fatalf("GET %s: routed to %q, want the typed app dispatcher (not proxied)",
					p, resp.Header.Get("X-Route"))
			}
		})
	}
}
