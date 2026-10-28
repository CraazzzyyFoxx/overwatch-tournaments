package respcache

// Resource -> the cached-entry URL substrings that resource can have staled.
// Mirrors backend/shared/realtime/resources.json; resources_test.go asserts
// this table and the manifest are exactly each other's mirror, so a resource
// cannot be published without the cache knowing what to drop, and a rule
// cannot outlive the resource it serves.
//
// An EMPTY (non-nil) slice is meaningful and different from nil: it says
// "this cache holds nothing for that resource" — notifications are per-user
// and never cached anonymously. nil — set deliberately, or a MISSING entry —
// drops every entry for the scope: deliberate for a resource that can change
// any page, and the fail-safe for a resource added to the manifest before
// this table caught up (the parity test exists so that stays theoretical).
var resourcePatterns = map[string][]string{
	// The tournament read model. bareTournamentDetailPattern (not a literal
	// substring) because the path segment is either a numeric id or an opaque
	// slug — see Rule.ExtractFromBody.
	"tournament.detail": {bareTournamentDetailPattern},
	"tournament.stages": {"/stages"},
	// Encounter reads carry tournament_id as a query param; the list route and
	// the overview share the prefix. "/ffa" is the stage's lobby tables
	// (/tournaments/{id}/stages/{stage_id}/ffa): an FFA result write emits
	// only tournament.encounters and the recalculation it enqueues only
	// standings/detail/encounters, so without it the entry lived out its TTL
	// while the standings beside it were already fresh. "/api/v1/users/" is
	// a player's page for this tournament (/users/{id}/tournaments/{tid} and
	// its /encounters and /leaderboard, stats.PublicCacheableReads) and
	// "/player-stats" every player's leaderboard rows at once: parsed logs
	// emit only encounters/standings. The scope already narrows it to this
	// tournament — a user's TTL-only profile reads live under id 0.
	"tournament.encounters": {"/api/v1/encounters", "/ffa", "/api/v1/users/", "/player-stats"},
	"tournament.standings":  {"/standings", "/ffa", "/api/v1/users/", "/player-stats"},
	"tournament.teams":      {"/api/v1/teams"},
	// Every page of the tournament: a section appearing or disappearing
	// changes the page-shell reads, and the same resource carries a
	// visibility flip (is_hidden), after which no anonymous entry of the
	// tournament may survive — the participants list included.
	"tournament.structure": nil,
	// The public participants list, plus the detail read that embeds live
	// participants_count / registrations_count.
	"tournament.registrations": {"/registration/list", bareTournamentDetailPattern},
	// The form route itself is never cached (a stale form is a false refusal
	// or a false admission), but the participants list renders from the form:
	// hide_registrations, max_participants and which answers are public. Same
	// rule as tournament-service's own cache (cache_resources.py).
	"tournament.registration_form": {"/registration/list"},
	"tournament.streams":           {"/api/v1/streams/tournament/"},
	// Workspace- and user-scoped resources: this cache only ever stores
	// anonymous public reads, so there is nothing of theirs to drop.
	"workspace.logs":           {},
	"workspace.pickup_mix":     {},
	"workspace.subscriptions":  {},
	"workspace.analytics_jobs": {},
	"user.notifications":       {},
}
