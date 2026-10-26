package tournament

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"slices"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

// TestTeamImageRouteContracts pins the team-logo surface: the DELETE is a typed
// method on the dispatcher (no Entity/Action, so it never reaches the generic CRUD
// engine and can't be mistaken for the team delete), and the POST is documented
// for the multipart binary handler.
func TestTeamImageRouteContracts(t *testing.T) {
	const pattern = "/api/v1/admin/teams/{team_id}/image"

	var del *edge.RouteSpec
	for i, r := range AdminCrudRoutes {
		if r.Pattern == pattern {
			del = &AdminCrudRoutes[i]
		}
	}
	if del == nil {
		t.Fatalf("%s DELETE is not registered", pattern)
	}
	if del.Method != "DELETE" || del.Queue != "rpc.tournament.teams.image_delete" || del.IDParam != "team_id" || del.Auth != edge.AuthRequired {
		t.Fatalf("unexpected image_delete contract: %#v", *del)
	}
	if del.Entity != "" || del.Action != "" {
		t.Fatalf("image_delete is a typed method, not generic CRUD: %#v", *del)
	}

	var up *edge.RouteSpec
	for i, r := range BinaryDocRoutes {
		if r.Pattern == pattern {
			up = &BinaryDocRoutes[i]
		}
	}
	if up == nil {
		t.Fatalf("%s POST is not documented in BinaryDocRoutes", pattern)
	}
	if up.Method != "POST" || up.Queue != "rpc.tournament.teams.image_upload" || up.Auth != edge.AuthRequired {
		t.Fatalf("unexpected image_upload contract: %#v", *up)
	}
}

// TestTournamentImageRouteContracts pins the cover/logo surface: the DELETE is a
// typed method carrying BOTH keys the worker reads ("id" from IDParam, "slot"
// verbatim from Path), and the POST is documented for the multipart handler.
func TestTournamentImageRouteContracts(t *testing.T) {
	const pattern = "/api/v1/admin/tournaments/{tournament_id}/images/{slot}"

	var del *edge.RouteSpec
	for i, r := range AdminCrudRoutes {
		if r.Pattern == pattern {
			del = &AdminCrudRoutes[i]
		}
	}
	if del == nil {
		t.Fatalf("%s DELETE is not registered", pattern)
	}
	if del.Method != "DELETE" || del.Queue != "rpc.tournament.tournaments.image_delete" || del.Auth != edge.AuthRequired {
		t.Fatalf("unexpected image_delete contract: %#v", *del)
	}
	if del.Entity != "" || del.Action != "" {
		t.Fatalf("image_delete is a typed method, not generic CRUD: %#v", *del)
	}
	// The worker reads the tournament as data["id"], so {tournament_id} must ride
	// IDParam; {slot} has no dedicated field and rides Path verbatim.
	if del.IDParam != "tournament_id" {
		t.Fatalf("image_delete must send the tournament as data[\"id\"]: %#v", *del)
	}
	if len(del.Path) != 1 || del.Path[0] != "slot" {
		t.Fatalf("image_delete must forward slot verbatim: %#v", *del)
	}

	var up *edge.RouteSpec
	for i, r := range BinaryDocRoutes {
		if r.Pattern == pattern {
			up = &BinaryDocRoutes[i]
		}
	}
	if up == nil {
		t.Fatalf("%s POST is not documented in BinaryDocRoutes", pattern)
	}
	if up.Method != "POST" || up.Queue != "rpc.tournament.tournaments.image_upload" || up.Auth != edge.AuthRequired {
		t.Fatalf("unexpected image_upload contract: %#v", *up)
	}
}

// TestTournamentFacetsRouteContract pins the facet counters read: AuthOptional,
// because the counts must match the visibility-filtered listing the same viewer
// gets (hidden tournaments are counted only for eligible viewers).
func TestTournamentFacetsRouteContract(t *testing.T) {
	const pattern = "/api/v1/tournaments/facets"

	var facets *edge.RouteSpec
	for i, r := range PublicReadRoutes {
		if r.Pattern == pattern {
			facets = &PublicReadRoutes[i]
		}
	}
	if facets == nil {
		t.Fatalf("%s is not registered", pattern)
	}
	if facets.Method != "GET" || facets.Queue != "rpc.tournament.tournaments_facets" || facets.Auth != edge.AuthOptional {
		t.Fatalf("unexpected facets contract: %#v", *facets)
	}
	if !slices.Contains(facets.Query, "discipline") {
		t.Fatalf("facets must forward the discipline filter the list honours: %#v", facets.Query)
	}
}

// TestPublicReadsHaveTimeout asserts every public tournament read opted into
// publicReadTimeout: at the 120s edge default an abandoned read's deadline sat
// two minutes out, so the worker could neither drop nor cancel it.
func TestPublicReadsHaveTimeout(t *testing.T) {
	for _, r := range PublicReadRoutes {
		if r.Method != "GET" || r.Timeout != publicReadTimeout {
			t.Errorf("%s %s (%s): public reads must be GETs with publicReadTimeout, got %v", r.Method, r.Pattern, r.Queue, r.Timeout)
		}
	}
}

// TestTournamentFacetsRouting pins that the literal "facets" segment is not
// swallowed by the /{id} read next to it — a facets request reaching
// get_tournament would 404 on a non-numeric id instead of returning counters.
func TestTournamentFacetsRouting(t *testing.T) {
	mux := http.NewServeMux()
	hit := ""
	mark := func(name string) http.HandlerFunc {
		return func(http.ResponseWriter, *http.Request) { hit = name }
	}
	for _, s := range PublicReadRoutes {
		mux.HandleFunc(s.Method+" "+s.Pattern, mark(s.Queue))
	}

	for _, tc := range []struct{ path, want string }{
		{"/api/v1/tournaments/facets", "rpc.tournament.tournaments_facets"},
		{"/api/v1/tournaments/72", "rpc.tournament.get_tournament"},
	} {
		hit = ""
		req, err := http.NewRequest("GET", tc.path, nil)
		if err != nil {
			t.Fatal(err)
		}
		mux.ServeHTTP(nil, req)
		if hit != tc.want {
			t.Errorf("GET %s routed to %q, want %q", tc.path, hit, tc.want)
		}
	}
}

// capturingCaller records the RPC body the dispatcher built.
type capturingCaller struct{ body []byte }

func (c *capturingCaller) Call(_ context.Context, _ string, body []byte) ([]byte, error) {
	c.body = body
	return []byte(`{"ok":true,"data":{}}`), nil
}

// TestTournamentImageDeletePayload proves the route table's IDParam+Path pair
// actually produces BOTH keys the worker reads — the field names alone don't say
// whether the two are additive in edge.Dispatcher.serve.
func TestTournamentImageDeletePayload(t *testing.T) {
	const pattern = "/api/v1/admin/tournaments/{tournament_id}/images/{slot}"

	var spec edge.RouteSpec
	for _, r := range AdminCrudRoutes {
		if r.Pattern == pattern && r.Method == "DELETE" {
			spec = r
		}
	}
	caller := &capturingCaller{}
	identity := func(*http.Request) (map[string]any, bool, error) {
		return map[string]any{"user_id": 1}, true, nil
	}
	mux := http.NewServeMux()
	edge.New(caller, slog.New(slog.DiscardHandler), identity).Register(mux, []edge.RouteSpec{spec})

	req := httptest.NewRequest("DELETE", "/api/v1/admin/tournaments/72/images/cover", nil)
	mux.ServeHTTP(httptest.NewRecorder(), req)

	var sent map[string]any
	if err := json.Unmarshal(caller.body, &sent); err != nil {
		t.Fatalf("no RPC body captured: %v (%q)", err, caller.body)
	}
	if sent["id"] != "72" {
		t.Errorf(`payload["id"] = %#v, want "72"`, sent["id"])
	}
	if sent["slot"] != "cover" {
		t.Errorf(`payload["slot"] = %#v, want "cover"`, sent["slot"])
	}
}

// TestRoutesRegisterWithoutConflict guards against ServeMux pattern conflicts,
// which panic at registration time (runtime), not at build time. It registers the
// tournament route tables that are mounted as patterns — the subtree tables
// (DivisionGridRoutes, StageSubtreeRoutes, RegistrationTeamSubtreeRoutes) are
// deliberately ambiguous and mounted via edge.Subtree — plus the subtree prefixes
// and multipart handlers wired in cmd/gateway/main.go.
func TestRoutesRegisterWithoutConflict(t *testing.T) {
	mux := http.NewServeMux()
	dummy := func(http.ResponseWriter, *http.Request) {}

	for _, set := range [][]edge.RouteSpec{
		PublicReadRoutes, PublicWriteRoutes, AdminCrudRoutes, AdminMiscRoutes, DashboardRoutes,
		RegistrationAdminRoutes, IntegrationsRoutes, ScrimRoutes,
	} {
		for _, s := range set {
			mux.HandleFunc(s.Method+" "+s.Pattern, dummy)
		}
	}
	// Subtree prefixes registered in main.go: less specific than every precise
	// pattern above, so they must coexist with them.
	mux.Handle("/api/v1/registration-teams/", http.NotFoundHandler())
	// Multipart handlers registered directly in main.go.
	mux.HandleFunc("POST /api/v1/admin/teams/{team_id}/image", dummy)
	mux.HandleFunc("POST /api/v1/registration-teams/{team_id}/image", dummy)
	mux.HandleFunc("POST /api/v1/admin/tournaments/{tournament_id}/images/{slot}", dummy)
}

// TestRegistrationTeamCrestRouting pins the precedence the crest DELETE depends
// on. Its pattern cannot be registered on the ServeMux at all (it is ambiguous
// with the invite-revoke wildcard), so it is served by the subtree mounted at
// /api/v1/registration-teams/ — which must NOT shadow the precise sibling
// patterns registered alongside it.
func TestRegistrationTeamCrestRouting(t *testing.T) {
	mux := http.NewServeMux()
	hit := ""
	mark := func(name string) http.HandlerFunc {
		return func(http.ResponseWriter, *http.Request) { hit = name }
	}
	for _, s := range PublicWriteRoutes {
		mux.HandleFunc(s.Method+" "+s.Pattern, mark(s.Queue))
	}
	mux.Handle("/api/v1/registration-teams/", mark("subtree"))
	mux.HandleFunc("POST /api/v1/registration-teams/{team_id}/image", mark("rpc.tournament.regteam_image_upload"))

	for _, tc := range []struct{ method, path, want string }{
		{"DELETE", "/api/v1/registration-teams/5/image", "subtree"},
		{"POST", "/api/v1/registration-teams/5/image", "rpc.tournament.regteam_image_upload"},
		// The siblings the subtree must not swallow.
		{"DELETE", "/api/v1/registration-teams/invites/9", "rpc.tournament.regteam_invite_revoke"},
		{"DELETE", "/api/v1/registration-teams/5", "rpc.tournament.regteam_disband"},
		{"DELETE", "/api/v1/registration-teams/5/members/me", "rpc.tournament.regteam_leave"},
		{"POST", "/api/v1/registration-teams/invites/accept", "rpc.tournament.regteam_accept"},
	} {
		hit = ""
		req, err := http.NewRequest(tc.method, tc.path, nil)
		if err != nil {
			t.Fatal(err)
		}
		mux.ServeHTTP(nil, req)
		if hit != tc.want {
			t.Errorf("%s %s routed to %q, want %q", tc.method, tc.path, hit, tc.want)
		}
	}
}

func TestPlayerSubRoleListForwardsExplicitDiscipline(t *testing.T) {
	var spec edge.RouteSpec
	for _, route := range AdminCrudRoutes {
		if route.Method == "GET" && route.Pattern == "/api/v1/admin/player-sub-roles" {
			spec = route
		}
	}
	caller := &capturingCaller{}
	identity := func(*http.Request) (map[string]any, bool, error) {
		return map[string]any{"user_id": 1}, true, nil
	}
	mux := http.NewServeMux()
	edge.New(caller, slog.New(slog.DiscardHandler), identity).Register(mux, []edge.RouteSpec{spec})
	mux.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/api/v1/admin/player-sub-roles?workspace_id=7&discipline=lol&include_inactive=true", nil))
	var sent struct {
		Query map[string][]string `json:"query"`
	}
	if err := json.Unmarshal(caller.body, &sent); err != nil {
		t.Fatalf("no RPC body captured: %v (%q)", err, caller.body)
	}
	if !slices.Equal(sent.Query["discipline"], []string{"lol"}) || !slices.Equal(sent.Query["workspace_id"], []string{"7"}) {
		t.Fatalf("lost concrete sub-role scope: %#v", sent.Query)
	}
}
