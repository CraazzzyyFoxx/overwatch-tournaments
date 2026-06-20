package balancer

import (
	"net/http"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

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
