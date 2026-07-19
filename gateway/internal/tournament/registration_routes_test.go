package tournament

import (
	"testing"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

// TestRegistrationAdminRouteContracts pins the wire contract of the bulk
// mutations (queue + payload shape) and the per-route timeout split: reads
// fail fast (regReadTimeout), writes keep the 120s edge default (Timeout 0).
func TestRegistrationAdminRouteContracts(t *testing.T) {
	want := map[string]struct {
		method  string
		queue   string
		body    bool
		timeout time.Duration
	}{
		"/api/v1/admin/balancer/tournaments/{tournament_id}/registrations/bulk-exclusion": {
			method: "POST", queue: "rpc.tournament.reg_bulk_exclusion", body: true,
		},
		"/api/v1/admin/balancer/tournaments/{tournament_id}/registrations/bulk-add-to-balancer": {
			method: "POST", queue: "rpc.tournament.reg_bulk_add_balancer", body: true,
		},
		"/api/v1/admin/balancer/tournaments/{tournament_id}/registrations": {
			method: "GET", queue: "rpc.tournament.reg_list", timeout: regReadTimeout,
		},
	}

	for _, r := range RegistrationAdminRoutes {
		expected, ok := want[r.Pattern]
		if !ok || r.Method != expected.method {
			continue
		}
		if r.Queue != expected.queue || r.Body != expected.body || r.Auth != edge.AuthRequired ||
			r.IDParam != "tournament_id" || r.Timeout != expected.timeout {
			t.Errorf("unexpected route contract for %s %s: %#v", r.Method, r.Pattern, r)
		}
		delete(want, r.Pattern)
	}
	if len(want) != 0 {
		t.Fatalf("missing registration admin routes: %#v", want)
	}
}

// TestRegistrationAdminReadsHaveTimeout asserts every GET in the table opted
// into the fast-fail read timeout and no write did.
func TestRegistrationAdminReadsHaveTimeout(t *testing.T) {
	for _, r := range RegistrationAdminRoutes {
		isRead := r.Method == "GET"
		if isRead && r.Timeout != regReadTimeout {
			t.Errorf("%s %s (%s): reads must set regReadTimeout, got %v", r.Method, r.Pattern, r.Queue, r.Timeout)
		}
		if !isRead && r.Timeout != 0 {
			t.Errorf("%s %s (%s): writes must keep the default timeout, got %v", r.Method, r.Pattern, r.Queue, r.Timeout)
		}
	}
}
