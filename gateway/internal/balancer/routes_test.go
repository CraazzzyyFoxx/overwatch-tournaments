package balancer

import (
	"net/http"
	"strings"
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

// TestDraftSessionHistoryRoutes pins the admin draft-history surface: listing a
// tournament's sessions and erasing one. The DELETE shares its pattern with the
// PATCH (session_patch), so a wrong Method here silently reroutes an erase.
func TestDraftSessionHistoryRoutes(t *testing.T) {
	var list, del *edge.RouteSpec
	for i, route := range DraftRoutes {
		switch route.Queue {
		case "rpc.balancer.draft.session_list":
			list = &DraftRoutes[i]
		case "rpc.balancer.draft.session_delete":
			del = &DraftRoutes[i]
		}
	}
	if list == nil || del == nil {
		t.Fatal("draft session list/delete routes are not registered")
	}
	if list.Method != "GET" || list.Pattern != "/api/balancer/draft/tournaments/{tournament_id}/sessions" || list.IDParam != "tournament_id" || list.Auth != edge.AuthRequired {
		t.Fatalf("unexpected session_list contract: %#v", *list)
	}
	if del.Method != "DELETE" || del.Pattern != "/api/balancer/draft/tournaments/{tournament_id}/sessions/{session_id}" || del.IDParam != "session_id" || del.Success != 204 || del.Auth != edge.AuthRequired {
		t.Fatalf("unexpected session_delete contract: %#v", *del)
	}
	if len(del.Path) != 1 || del.Path[0] != "tournament_id" {
		t.Fatalf("session_delete must forward tournament_id for the permission check: %#v", del.Path)
	}
}

func TestRosterRoutes(t *testing.T) {
	want := map[string]string{
		"GET /api/balancer/workspaces/{workspace_id}/players":                   "rpc.balancer.players.list",
		"GET /api/balancer/workspaces/{workspace_id}/players/summary":           "rpc.balancer.players.summary",
		"POST /api/balancer/workspaces/{workspace_id}/players":                  "rpc.balancer.players.upsert",
		"PUT /api/balancer/workspaces/{workspace_id}/players/{member_id}/ranks": "rpc.balancer.players.set_ranks",
	}
	for _, route := range RosterRoutes {
		key := route.Method + " " + route.Pattern
		queue, ok := want[key]
		if !ok {
			continue
		}
		if route.Queue != queue || route.Auth != edge.AuthRequired {
			t.Fatalf("unexpected %s: %#v", key, route)
		}
		delete(want, key)
	}
	if len(want) != 0 {
		t.Fatalf("missing roster routes: %#v", want)
	}
}

// TestMixReadsArePublic pins the five mix reads as AuthNone and every mix write
// as AuthRequired. A mix board is read out to a lobby whose players need no
// account here, so flipping a read back to AuthRequired 401s every signed-out
// visitor on /balancer/mix; flipping a write to AuthNone would hand the worker
// no actor to check host-or-co-host against.
func TestMixReadsArePublic(t *testing.T) {
	public := map[string]bool{
		"GET /api/balancer/workspaces/{workspace_id}/custom-games":                    true,
		"GET /api/balancer/workspaces/{workspace_id}/custom-games/stats":              true,
		"GET /api/balancer/workspaces/{workspace_id}/custom-games/{game_id}":          true,
		"GET /api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/matches":  true,
		"GET /api/balancer/workspaces/{workspace_id}/custom-games/{game_id}/rotation": true,
	}
	seen := 0
	for _, route := range RosterRoutes {
		if !strings.Contains(route.Pattern, "/custom-games") {
			continue
		}
		key := route.Method + " " + route.Pattern
		if public[key] {
			seen++
			if route.Auth != edge.AuthNone {
				t.Fatalf("mix read %s must be public: %#v", key, route)
			}
			continue
		}
		if route.Auth != edge.AuthRequired {
			t.Fatalf("mix write %s must stay authenticated: %#v", key, route)
		}
	}
	if seen != len(public) {
		t.Fatalf("expected %d public mix reads, found %d", len(public), seen)
	}
}

// TestRoutesRegisterWithoutConflict guards against ServeMux pattern conflicts,
// which panic at registration time (runtime), not at build time. It registers
// the entire balancer route surface — the typed route tables plus the two
// multipart handlers wired in cmd/gateway/main.go — onto a fresh mux.
func TestRoutesRegisterWithoutConflict(t *testing.T) {
	mux := http.NewServeMux()
	dummy := func(http.ResponseWriter, *http.Request) {}

	for _, set := range [][]edge.RouteSpec{PublicRoutes, AdminRoutes, RosterRoutes, DraftReadRoutes, DraftRoutes, JobRoutes} {

		for _, s := range set {
			mux.HandleFunc(s.Method+" "+s.Pattern, dummy)
		}
	}
	// Multipart handlers registered directly in main.go.
	mux.HandleFunc("POST /api/balancer/tournaments/{tournament_id}/teams/import", dummy)
	mux.HandleFunc("POST /api/balancer/jobs", dummy)
}
