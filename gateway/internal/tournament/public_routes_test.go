package tournament

import (
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

// Visibility-gated public reads must forward identity so an eligible
// admin/preview viewer of a HIDDEN tournament is not treated as anonymous and
// 404'd. AuthNone would drop the identity (see edge/dispatch.go), reintroducing
// the #115 regression.
func TestVisibilityGatedPublicReadsForwardIdentity(t *testing.T) {
	gated := map[string]bool{
		"rpc.tournament.captain_map_pool": true,
		"rpc.tournament.reg_pub_form":     true,
		"rpc.tournament.reg_pub_list":     true,
	}
	seen := map[string]bool{}
	for _, r := range PublicWriteRoutes {
		if gated[r.Queue] {
			seen[r.Queue] = true
			if r.Auth == edge.AuthNone {
				t.Errorf("%s %s (%s) is AuthNone; must be AuthOptional so hidden-tournament gating sees the viewer", r.Method, r.Pattern, r.Queue)
			}
		}
	}
	for q := range gated {
		if !seen[q] {
			t.Errorf("route %s not found in PublicWriteRoutes", q)
		}
	}
}
