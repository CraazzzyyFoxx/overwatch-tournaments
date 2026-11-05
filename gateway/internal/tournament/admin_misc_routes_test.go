package tournament

import (
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

// TestFlowNodeTransitionRouteContract pins the node lifecycle write: POST with a JSON body, the node id as the
// RPC id, signed-in callers only (the worker checks workspace tournament.update).
func TestFlowNodeTransitionRouteContract(t *testing.T) {
	const pattern = "/api/v1/admin/flow-nodes/{node_id}/transition"

	var got *edge.RouteSpec
	for i, r := range AdminMiscRoutes {
		if r.Pattern == pattern {
			got = &AdminMiscRoutes[i]
		}
	}
	if got == nil {
		t.Fatalf("%s is not registered", pattern)
	}
	if got.Method != "POST" || got.Queue != "rpc.tournament.flow_node_transition" || got.IDParam != "node_id" || !got.Body || got.Auth != edge.AuthRequired {
		t.Fatalf("unexpected flow_node_transition contract: %#v", *got)
	}
}
