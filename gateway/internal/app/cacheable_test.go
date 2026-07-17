package app

import (
	"net/http"
	"testing"
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
