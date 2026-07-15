package balancer

import (
	"net/http"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

func TestDraftSafetyRoutes(t *testing.T) {
	want := map[string]struct {
		method string
		queue  string
	}{
		"/api/balancer/draft/sessions/{session_id}/feasibility": {
			method: "GET",
			queue:  "rpc.balancer.draft.feasibility",
		},
		"/api/balancer/draft/picks/{pick_id}/options": {
			method: "GET",
			queue:  "rpc.balancer.draft.pick_options",
		},
		"/api/balancer/draft/sessions/{session_id}/players/{player_id}/roles": {
			method: "POST",
			queue:  "rpc.balancer.draft.player_role_edit",
		},
	}

	for _, route := range DraftRoutes {
		expected, ok := want[route.Pattern]
		if !ok {
			continue
		}
		if route.Method != expected.method || route.Queue != expected.queue || route.Auth != edge.AuthRequired {
			t.Fatalf("unexpected route contract for %s: %#v", route.Pattern, route)
		}
		delete(want, route.Pattern)
	}
	if len(want) != 0 {
		t.Fatalf("missing draft safety routes: %#v", want)
	}
}

// TestRoutesRegisterWithoutConflict guards against ServeMux pattern conflicts,
// which panic at registration time (runtime), not at build time. It registers
// the entire balancer route surface — the typed route tables plus the two
// multipart handlers wired in cmd/gateway/main.go — onto a fresh mux.
func TestRoutesRegisterWithoutConflict(t *testing.T) {
	mux := http.NewServeMux()
	dummy := func(http.ResponseWriter, *http.Request) {}

	for _, set := range [][]edge.RouteSpec{PublicRoutes, AdminRoutes, DraftReadRoutes, DraftRoutes, JobRoutes} {
		for _, s := range set {
			mux.HandleFunc(s.Method+" "+s.Pattern, dummy)
		}
	}
	// Multipart handlers registered directly in main.go.
	mux.HandleFunc("POST /api/balancer/tournaments/{tournament_id}/teams/import", dummy)
	mux.HandleFunc("POST /api/balancer/jobs", dummy)
}
