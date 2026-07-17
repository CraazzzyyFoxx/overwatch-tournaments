package tournament

import (
	"net/http"
	"testing"
)

// Every cacheable pattern must exist in PublicReadRoutes as a GET — a renamed
// or removed route would otherwise leave a dead rule that silently caches
// nothing (or worse, a future non-GET reuse of the pattern).
func TestPublicCacheableReadsMatchRouteTable(t *testing.T) {
	routes := make(map[string]string, len(PublicReadRoutes))
	for _, r := range PublicReadRoutes {
		routes[r.Pattern] = r.Method
	}
	for pattern := range PublicCacheableReads {
		method, ok := routes[pattern]
		if !ok {
			t.Errorf("cacheable pattern %q is not in PublicReadRoutes", pattern)
			continue
		}
		if method != http.MethodGet {
			t.Errorf("cacheable pattern %q is %s, only GET may be cached", pattern, method)
		}
	}
}

// PublicWriteCacheableReads must reference real GET routes from
// PublicWriteRoutes (same drift guard as above, against its own table).
func TestPublicWriteCacheableReadsMatchRouteTable(t *testing.T) {
	routes := make(map[string]string, len(PublicWriteRoutes))
	for _, r := range PublicWriteRoutes {
		routes[r.Pattern] = r.Method
	}
	for pattern := range PublicWriteCacheableReads {
		method, ok := routes[pattern]
		if !ok {
			t.Errorf("cacheable pattern %q is not in PublicWriteRoutes", pattern)
			continue
		}
		if method != http.MethodGet {
			t.Errorf("cacheable pattern %q is %s, only GET may be cached", pattern, method)
		}
	}
}

// The participants list is cached for anonymous AND logged-in viewers
// (product decision: the body is viewer-agnostic, and a player's personal
// state stays live via the uncached AuthRequired /registration/me). The rule
// must keep both the entry and the grant — removing either silently
// reintroduces one full RPC per participants-page view.
func TestRegistrationListCachedWithAuthedRead(t *testing.T) {
	rule, ok := PublicWriteCacheableReads["/api/v1/tournaments/{tournament_id}/registration/list"]
	if !ok {
		t.Fatal("registration list must be in PublicWriteCacheableReads")
	}
	if !rule.AuthedRead {
		t.Fatal("registration list must grant AuthedRead (deliberate product decision)")
	}
}

// The registration form stays uncached: admin form edits emit no
// bracket-topic event, and a stale form could reject valid submissions.
func TestRegistrationFormNeverCacheable(t *testing.T) {
	const form = "/api/v1/tournaments/{tournament_id}/registration/form"
	if _, ok := PublicCacheableReads[form]; ok {
		t.Fatalf("%s must not be cached", form)
	}
	if _, ok := PublicWriteCacheableReads[form]; ok {
		t.Fatalf("%s must not be cached", form)
	}
}

// The encounters list grants AuthedRead only because the sole viewer-
// dependent shape (scope=my_team) is carved out; the grant without the
// carve-out would serve logged-in players the anonymous (hardcoded-empty)
// my_team body.
func TestEncountersAuthedReadRequiresMyTeamCarveOut(t *testing.T) {
	rule, ok := PublicCacheableReads["/api/v1/encounters"]
	if !ok {
		t.Fatal("/api/v1/encounters must be in PublicCacheableReads")
	}
	if rule.AuthedRead && rule.AuthedReadUnless == nil {
		t.Fatal("/api/v1/encounters AuthedRead requires the scope=my_team carve-out")
	}
}

// encounters/overview bodies carry a per-viewer my_team_count; the anonymous
// entry would always show 0 to logged-in players.
func TestEncountersOverviewNeverAuthedRead(t *testing.T) {
	rule, ok := PublicCacheableReads["/api/v1/encounters/overview"]
	if !ok {
		t.Fatal("/api/v1/encounters/overview must be in PublicCacheableReads")
	}
	if rule.AuthedRead {
		t.Fatal("/api/v1/encounters/overview must never grant AuthedRead")
	}
}
