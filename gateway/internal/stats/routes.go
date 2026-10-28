// Package stats holds the gateway route table for stats-service, translated to
// typed RPC via the shared edge.Dispatcher. The table is data; the dispatcher is
// generic.
//
// Stats-unique domains are folded into the unified /api/v1/* namespace (match-log
// admin, OverFast rank, subscription collection, achievement engine + rules admin,
// catalog sync, settings, bootstrap importers), as are the public player
// statistics, profile and achievement reads (PublicReadRoutes,
// AchievementsSubtreeRoutes). The worker's RPC queues are path-independent, so
// the external paths are clean /api/v1/* with no /api/stats prefix. Un-migrated
// stats endpoints still proxy to stats-service on their original addresses.
package stats

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// PublicReadRoutes are the flat (non-ambiguous) public player statistics,
// profile and achievement reads. Achievements' get surface is in
// AchievementsSubtreeRoutes (ServeMux can't disambiguate /{id}/users vs
// /user/{user_id}); the achievements *list* stays here.
var PublicReadRoutes = []edge.RouteSpec{
	// --- one discipline's character and map statistics (the catalog reads are app-service's native /api/v1/catalog routes).
	// Four to six segments: no clash with the three-segment /statistics/{champion,winrate,players,records} literals. ---
	{Method: "GET", Pattern: "/api/v1/statistics/{discipline}/characters/playtime", Queue: "rpc.stats.statistics.character_playtime", Path: []string{"discipline"}, AllQuery: true, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/statistics/{discipline}/characters/{entity_id}/leaderboard", Queue: "rpc.stats.statistics.character_leaderboard", IDParam: "entity_id", Path: []string{"discipline"}, AllQuery: true, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/statistics/{discipline}/maps", Queue: "rpc.stats.statistics.maps", Path: []string{"discipline"}, Query: []string{"workspace_id"}, Auth: edge.AuthNone},
	// --- one tournament's per-player stat ranks (the tournament page); no clash with tournament-service's
	// literal /api/v1/tournaments/{id}/* reads. AuthOptional: the worker 404s a hidden tournament. ---
	{Method: "GET", Pattern: "/api/v1/tournaments/{id}/player-stats", Queue: "rpc.stats.statistics.tournament_player_stats", IDParam: "id", Auth: edge.AuthOptional},
	// --- achievements (list only; get surface is the subtree) ---------------
	{Method: "GET", Pattern: "/api/v1/achievements", Queue: "rpc.stats.achievements.list", AllQuery: true, Auth: edge.AuthNone},
	// --- statistics ---------------------------------------------------------
	{Method: "GET", Pattern: "/api/v1/statistics/champion", Queue: "rpc.stats.statistics.champion", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/statistics/winrate", Queue: "rpc.stats.statistics.winrate", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/statistics/players", Queue: "rpc.stats.statistics.players", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/statistics/records", Queue: "rpc.stats.statistics.records", Query: []string{"discipline", "workspace_id"}, Auth: edge.AuthNone},
	// --- users (literals + /{id}/...; the directory and the bare /{name} slug resolution are app-service's
	// app.ReadRoutes, whose /{name} the /overview literals out-rank by ServeMux specificity) ---
	{Method: "GET", Pattern: "/api/v1/users/overview", Queue: "rpc.stats.users.overview", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/users/overview/stats", Queue: "rpc.stats.users.overview_stats", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/users/overview/catalog", Queue: "rpc.stats.users.overview_catalog", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/users/{id}/compare", Queue: "rpc.stats.users.compare", IDParam: "id", AllQuery: true, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/users/{id}/compare/characters", Queue: "rpc.stats.users.compare_characters", IDParam: "id", AllQuery: true, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/users/{id}/profile", Queue: "rpc.stats.users.get_profile", IDParam: "id", Query: []string{"workspace_id", "discipline"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/users/{id}/draft-card", Queue: "rpc.stats.users.draft_card", IDParam: "id", Query: []string{"workspace_id", "discipline"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/users/{id}/tournaments", Queue: "rpc.stats.users.tournaments", IDParam: "id", Query: []string{"workspace_id", "discipline"}, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/users/{id}/tournaments/{tournament_id}", Queue: "rpc.stats.users.tournament", IDParam: "id", Path: []string{"tournament_id"}, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/users/{id}/tournaments/{tournament_id}/encounters", Queue: "rpc.stats.users.tournament_encounters", IDParam: "id", Path: []string{"tournament_id"}, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/users/{id}/tournaments/{tournament_id}/leaderboard", Queue: "rpc.stats.users.tournament_leaderboard", IDParam: "id", Path: []string{"tournament_id"}, Query: []string{"stat"}, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/users/{id}/maps", Queue: "rpc.stats.users.maps", IDParam: "id", AllQuery: true, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/users/{id}/maps/summary", Queue: "rpc.stats.users.maps_summary", IDParam: "id", AllQuery: true, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/users/{id}/encounters", Queue: "rpc.stats.users.encounters", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/users/{id}/matches/summary", Queue: "rpc.stats.users.matches_summary", IDParam: "id", Query: []string{"workspace_id", "discipline"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/users/{id}/characters", Queue: "rpc.stats.users.characters", IDParam: "id", AllQuery: true, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/users/{id}/teammates", Queue: "rpc.stats.users.teammates", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
}

// AchievementsSubtreeRoutes is mounted at /api/v1/achievements/ via the
// ordered edge.Subtree matcher. Plain Register would panic: /{id}/users and
// /user/{user_id} are both 2-segment and cross-specific (neither is uniformly
// more specific), which the stdlib ServeMux rejects. First-match-wins order
// mirrors FastAPI declaration order (literal-bearing patterns before the bare
// {id} get).
//
// The achievements *list* (/api/v1/achievements, no trailing slash) is a
// flat PublicReadRoutes entry — the subtree mount only covers /achievements/*.
var AchievementsSubtreeRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/achievements/user/{user_id}", Queue: "rpc.stats.achievements.user", IDParam: "user_id", AllQuery: true, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/achievements/{id}/users", Queue: "rpc.stats.achievements.users", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/achievements/{id}", Queue: "rpc.stats.achievements.get", IDParam: "id", Query: []string{"entities", "workspace_id"}, Auth: edge.AuthNone},
}

// Routes are the migrated stats endpoints (typed RPC). Permission gating is
// enforced in the worker handlers; AuthRequired here injects identity + rejects
// anonymous callers (mirroring the route dependencies).
var Routes = []edge.RouteSpec{
	// match-log admin (src/routes/admin/logs.py); JSON reads/writes.
	{Method: "GET", Pattern: "/api/v1/admin/logs/queue-status", Queue: "rpc.stats.logs.queue_status", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/logs/history", Queue: "rpc.stats.logs.history", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/logs/stats", Queue: "rpc.stats.logs.stats", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/logs/{id}/retry", Queue: "rpc.stats.logs.retry", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	// Admin bind of an awaiting_link job to a game with the operator's complete team map (src/rpc/ingest.py).
	// The target game's authoritative current observation (the bind's expected_revision), src/rpc/ingest.py.
	{Method: "GET", Pattern: "/api/v1/admin/logs/games/{id}/observation", Queue: "rpc.stats.ingest.game_observation", IDParam: "id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/logs/{id}/bind", Queue: "rpc.stats.ingest.bind", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	// match-log enqueue (src/routes/match_logs.py); admin-role gated in the handler.
	{Method: "POST", Pattern: "/api/v1/logs/{id}", Queue: "rpc.stats.logs.process_tournament", IDParam: "id", Auth: edge.AuthRequired},

	// Rank history (src/rpc/rank.py); public reads. `discipline` names the game (default overwatch).
	{Method: "GET", Pattern: "/api/v1/users/{id}/rank-history", Queue: "rpc.stats.rank.user_history", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/users/{id}/current-ranks", Queue: "rpc.stats.rank.user_current", IDParam: "id", Query: []string{"platform", "discipline"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/game-accounts/{id}/rank-history", Queue: "rpc.stats.rank.game_account_history", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},

	// Rank collection admin (src/rpc/rank.py); rank.read / rank.update, where `workspace_id` is both the
	// authorization scope and the data filter, and `discipline` names the game's collector.
	{Method: "GET", Pattern: "/api/v1/admin/rank/stats", Queue: "rpc.stats.rank.stats", Query: []string{"workspace_id", "discipline"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/rank/fetch-log", Queue: "rpc.stats.rank.fetch_log", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/rank/users/{id}/collection", Queue: "rpc.stats.rank.user_collection", IDParam: "id", Query: []string{"workspace_id", "discipline"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/rank/collect", Queue: "rpc.stats.rank.collect", Body: true, Query: []string{"workspace_id", "discipline"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/rank/reenable-disabled", Queue: "rpc.stats.rank.reenable_disabled", Body: true, Query: []string{"workspace_id", "discipline"}, Auth: edge.AuthRequired},

	// Subscription collection admin (src/rpc/subscription.py); subscription.read /
	// subscription.update, where `workspace_id` is both the authorization scope and
	// the data filter — so it must reach the handler on every one of these.
	{Method: "GET", Pattern: "/api/v1/admin/subscriptions/stats", Queue: "rpc.stats.subscription.stats", Query: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/subscriptions/check-log", Queue: "rpc.stats.subscription.check_log", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/subscriptions/users/{id}/collection", Queue: "rpc.stats.subscription.user_collection", IDParam: "id", Query: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/subscriptions/collect", Queue: "rpc.stats.subscription.collect", Body: true, Query: []string{"workspace_id"}, Auth: edge.AuthRequired},

	// Achievement calculate (src/routes/achievement.py); global admin role in the handler.
	{Method: "POST", Pattern: "/api/v1/achievement/calculate", Queue: "rpc.stats.ach.calculate", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/achievement/calculate/{tournament_id}", Queue: "rpc.stats.ach.calculate_tournament", Path: []string{"tournament_id"}, Body: true, Auth: edge.AuthRequired},

	// Catalog sync of one discipline from its module's source, a background job: POST starts it, GET reads its
	// snapshot (src/services/catalog_sync.py); superuser in the handler.
	{Method: "POST", Pattern: "/api/v1/admin/catalog-sync/{discipline}", Queue: "rpc.stats.catalog.sync", Path: []string{"discipline"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/catalog-sync/{discipline}", Queue: "rpc.stats.catalog.sync_status", Path: []string{"discipline"}, Auth: edge.AuthRequired},

	// Global settings (src/routes/admin/settings.py); superuser in the handler.
	{Method: "GET", Pattern: "/api/v1/admin/settings", Queue: "rpc.stats.settings.list", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/settings/{key}", Queue: "rpc.stats.settings.get", Path: []string{"key"}, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/v1/admin/settings/{key}", Queue: "rpc.stats.settings.upsert", Path: []string{"key"}, Body: true, Auth: edge.AuthRequired},
}

// AchievementAdminRoutes are the workspace-scoped achievement rule/library/override
// admin endpoints (src/routes/admin/achievement_rule.py), served via the ordered
// edge.Subtree matcher under /api/v1/admin/ws/ (literal segments like
// rules/export collide with rules/{rule_id} under the stdlib ServeMux). ORDER
// MATTERS: literal routes precede the {rule_id} catch-alls. All require auth;
// the workspace "achievement.<action>" permission is enforced in each handler.
var AchievementAdminRoutes = []edge.RouteSpec{
	// --- rules: literal segments first ---
	{Method: "GET", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/condition-types", Queue: "rpc.stats.ach.condition_types", Path: []string{"workspace_id"}, Query: []string{"discipline"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/validate", Queue: "rpc.stats.ach.validate", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/seed", Queue: "rpc.stats.ach.seed", Path: []string{"workspace_id"}, Query: []string{"discipline"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/reset", Queue: "rpc.stats.ach.reset", Path: []string{"workspace_id"}, Query: []string{"discipline"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/export", Queue: "rpc.stats.ach.export", Path: []string{"workspace_id"}, Query: []string{"discipline"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/import", Queue: "rpc.stats.ach.import", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/runs", Queue: "rpc.stats.ach.runs", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/evaluate", Queue: "rpc.stats.ach.evaluate", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	// --- rules: {rule_id}/<sub> (2-segment) ---
	{Method: "GET", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/{rule_id}/users", Queue: "rpc.stats.ach.rule_users", Path: []string{"workspace_id", "rule_id"}, AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/{rule_id}/test", Queue: "rpc.stats.ach.test", Path: []string{"workspace_id", "rule_id"}, Query: []string{"tournament_id"}, Auth: edge.AuthRequired},
	// --- rules: {rule_id} catch-alls ---
	{Method: "GET", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/{rule_id}", Queue: "rpc.stats.ach.get", Path: []string{"workspace_id", "rule_id"}, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/{rule_id}", Queue: "rpc.stats.ach.update", Path: []string{"workspace_id", "rule_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules/{rule_id}", Queue: "rpc.stats.ach.delete", Path: []string{"workspace_id", "rule_id"}, Auth: edge.AuthRequired, Success: 204},
	// --- rules: collection (list/create) ---
	{Method: "GET", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules", Queue: "rpc.stats.ach.list", Path: []string{"workspace_id"}, AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/rules", Queue: "rpc.stats.ach.create", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	// --- library ---
	{Method: "GET", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/library/workspaces", Queue: "rpc.stats.ach.lib_workspaces", Path: []string{"workspace_id"}, Query: []string{"discipline"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/library", Queue: "rpc.stats.ach.lib_list", Path: []string{"workspace_id"}, Query: []string{"source_workspace_id", "discipline"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/library/import", Queue: "rpc.stats.ach.lib_import", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	// --- overrides ---
	{Method: "GET", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/overrides", Queue: "rpc.stats.ach.overrides_list", Path: []string{"workspace_id"}, Query: []string{"discipline"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/overrides", Queue: "rpc.stats.ach.override_create", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "DELETE", Pattern: "/api/v1/admin/ws/{workspace_id}/achievements/overrides/{override_id}", Queue: "rpc.stats.ach.override_delete", Path: []string{"workspace_id", "override_id"}, Auth: edge.AuthRequired, Success: 204},
}
