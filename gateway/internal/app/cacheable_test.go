package app

import (
	"net/http"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

// Every cacheable pattern must exist in ReadRoutes as a GET — a renamed or
// removed route would otherwise leave a dead rule that silently caches
// nothing (or worse, a future non-GET reuse of the pattern).
func TestPublicCacheableReadsMatchRouteTable(t *testing.T) {
	routes := make(map[string]string, len(ReadRoutes))
	for _, r := range ReadRoutes {
		routes[r.Pattern] = r.Method
	}
	for pattern := range PublicCacheableReads {
		method, ok := routes[pattern]
		if !ok {
			t.Errorf("cacheable pattern %q is not in ReadRoutes", pattern)
			continue
		}
		if method != http.MethodGet {
			t.Errorf("cacheable pattern %q is %s, only GET may be cached", pattern, method)
		}
	}
}

// /workspaces/by-host feeds tenant-origin resolution; a stale answer there
// could mis-route SSO. It must never appear in the cacheable table.
func TestByHostNeverCacheable(t *testing.T) {
	if _, ok := PublicCacheableReads["/api/v1/workspaces/by-host"]; ok {
		t.Fatal("/api/v1/workspaces/by-host must not be cached")
	}
}

// The workspaces list is one endpoint serving three scopes; dispatch only
// forwards query params a route declares (edge/dispatch.go), so dropping
// "scope" here would silently pin every caller to the public directory —
// emptying the admin table and the workspace switcher.
func TestWorkspacesListForwardsScope(t *testing.T) {
	for _, r := range ReadRoutes {
		if r.Pattern != "/api/v1/workspaces" || r.Method != http.MethodGet {
			continue
		}
		for _, q := range r.Query {
			if q == "scope" {
				return
			}
		}
		t.Fatalf("GET /api/v1/workspaces must forward ?scope, got Query=%v AllQuery=%v", r.Query, r.AllQuery)
	}
	t.Fatal("GET /api/v1/workspaces missing from ReadRoutes")
}

// The draft room reads a player's card straight off the public surface: it must
// stay unauthenticated like /profile, and it must forward workspace_id — dispatch
// only forwards query params a route declares (edge/dispatch.go), and app-service
// rejects the read with 400 without that scope.
func TestDraftCardRouteIsPublicAndWorkspaceScoped(t *testing.T) {
	for _, r := range ReadRoutes {
		if r.Pattern != "/api/v1/users/{id}/draft-card" {
			continue
		}
		if r.Method != http.MethodGet || r.Queue != "rpc.app.users.draft_card" {
			t.Fatalf("draft-card route is %s -> %q", r.Method, r.Queue)
		}
		if r.Auth != edge.AuthNone {
			t.Errorf("draft-card must be AuthNone like /profile, got %v", r.Auth)
		}
		for _, q := range r.Query {
			if q == "workspace_id" {
				return
			}
		}
		t.Fatalf("GET /api/v1/users/{id}/draft-card must forward ?workspace_id, got Query=%v", r.Query)
	}
	t.Fatal("GET /api/v1/users/{id}/draft-card missing from ReadRoutes")
}
