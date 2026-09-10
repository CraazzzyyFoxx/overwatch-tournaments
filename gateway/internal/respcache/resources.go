package respcache

// Resource -> the cached-entry URL substrings that resource can have staled.
// Mirrors backend/shared/realtime/resources.json; resources_test.go asserts
// this table and the manifest are exactly each other's mirror, so a resource
// cannot be published without the cache knowing what to drop, and a rule
// cannot outlive the resource it serves.
//
// An EMPTY (non-nil) slice is meaningful and different from a missing entry:
// it says "this cache holds nothing for that resource" — the registration form
// is admin configuration nothing here caches, notifications are per-user and
// never cached anonymously. A MISSING entry falls back to nil, which drops
// every entry for the scope; that is the fail-safe for a resource added to the
// manifest before this table caught up, and the parity test exists so it stays
// theoretical.
var resourcePatterns = map[string][]string{
	// The tournament read model. bareTournamentDetailPattern (not a literal
	// substring) because the path segment is either a numeric id or an opaque
	// slug — see Rule.ExtractFromBody.
	"tournament.detail": {bareTournamentDetailPattern},
	"tournament.stages": {"/stages"},
	// Encounter reads carry tournament_id as a query param; the list route and
	// the overview share the prefix.
	"tournament.encounters": {"/api/v1/encounters"},
	"tournament.standings":  {"/standings"},
	"tournament.teams":      {"/api/v1/teams"},
	// A section appearing or disappearing changes every page-shell read.
	"tournament.structure": {
		bareTournamentDetailPattern,
		"/stages",
		"/standings",
		"/api/v1/encounters",
		"/api/v1/teams",
	},
	// The public participants list, plus the detail read that embeds live
	// participants_count / registrations_count.
	"tournament.registrations": {"/registration/list", bareTournamentDetailPattern},
	// Not cached here at all, and deliberately not cached server-side either
	// (registration/admission.py: a stale form is a false refusal or a false
	// admission). Empty, so a form edit evicts nothing.
	"tournament.registration_form": {},
	"tournament.streams":           {"/api/streams/tournament/"},
	// Workspace- and user-scoped resources: this cache only ever stores
	// anonymous public reads, so there is nothing of theirs to drop.
	"workspace.logs":           {},
	"workspace.pickup_mix":     {},
	"workspace.subscriptions":  {},
	"workspace.analytics_jobs": {},
	"user.notifications":       {},
}
