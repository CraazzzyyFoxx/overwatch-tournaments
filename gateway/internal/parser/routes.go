// Package parser holds the gateway route table for parser-service, translated to
// typed RPC via the shared edge.Dispatcher. The table is data; the dispatcher is
// generic. Specific patterns here win over the /api/parser reverse proxy by
// ServeMux specificity, so endpoints cut over to RPC incrementally.
//
// Paths keep the external /api/parser/* scheme verbatim (Kong strip_path:false +
// FastAPI root_path="/api/parser" + router prefixes), so the frontend is
// unchanged. Only parser-unique domains migrate here (match-log admin, OverFast
// rank, achievement engine + rules admin, OverFast metadata sync, settings,
// discord-channel); everything else is owned by app-service / tournament-service.
package parser

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// Routes are the migrated parser endpoints (typed RPC). Permission gating is
// enforced in the worker handlers; AuthRequired here injects identity + rejects
// anonymous callers (mirroring the route dependencies).
var Routes = []edge.RouteSpec{
	// match-log admin (src/routes/admin/logs.py); JSON reads/writes.
	{Method: "GET", Pattern: "/api/parser/admin/logs/queue-status", Queue: "rpc.parser.logs.queue_status", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/parser/admin/logs/history", Queue: "rpc.parser.logs.history", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/logs/{id}/retry", Queue: "rpc.parser.logs.retry", IDParam: "id", Auth: edge.AuthRequired},
	// match-log enqueue (src/routes/match_logs.py); admin-role gated in the handler.
	{Method: "POST", Pattern: "/api/parser/logs/{id}", Queue: "rpc.parser.logs.process_tournament", IDParam: "id", Auth: edge.AuthRequired},

	// OverFast rank history (src/routes/rank_history.py); public reads.
	{Method: "GET", Pattern: "/api/parser/users/{id}/rank-history", Queue: "rpc.parser.rank.user_history", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/parser/users/{id}/current-ranks", Queue: "rpc.parser.rank.user_current", IDParam: "id", Query: []string{"platform"}, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/parser/battle-tags/{id}/rank-history", Queue: "rpc.parser.rank.battle_tag_history", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},

	// OverFast rank collection admin (src/routes/admin/rank_collection.py); admin role.
	{Method: "GET", Pattern: "/api/parser/admin/rank/fetch-log", Queue: "rpc.parser.rank.fetch_log", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/parser/admin/rank/users/{id}/collection", Queue: "rpc.parser.rank.user_collection", IDParam: "id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/rank/collect", Queue: "rpc.parser.rank.collect", Body: true, Auth: edge.AuthRequired},

	// Achievement calculate (src/routes/achievement.py); global admin role in the handler.
	{Method: "POST", Pattern: "/api/parser/achievement/calculate", Queue: "rpc.parser.ach.calculate", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/achievement/calculate/{tournament_id}", Queue: "rpc.parser.ach.calculate_tournament", Path: []string{"tournament_id"}, Body: true, Auth: edge.AuthRequired},

	// OverFast metadata sync (src/routes/{hero,map,gamemode}.py); <entity>.sync perm.
	{Method: "POST", Pattern: "/api/parser/heroes/update", Queue: "rpc.parser.metadata.sync_heroes", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/maps/update", Queue: "rpc.parser.metadata.sync_maps", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/gamemodes/update", Queue: "rpc.parser.metadata.sync_gamemodes", Auth: edge.AuthRequired},

	// Global settings (src/routes/admin/settings.py); superuser in the handler.
	{Method: "GET", Pattern: "/api/parser/admin/settings", Queue: "rpc.parser.settings.list", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/parser/admin/settings/{key}", Queue: "rpc.parser.settings.get", Path: []string{"key"}, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/parser/admin/settings/{key}", Queue: "rpc.parser.settings.upsert", Path: []string{"key"}, Body: true, Auth: edge.AuthRequired},

	// Per-tournament Discord channel (src/routes/admin/discord_channel.py); discord_channel perm.
	{Method: "GET", Pattern: "/api/parser/admin/tournaments/{id}/discord-channel", Queue: "rpc.parser.discord_channel.get", IDParam: "id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/tournaments/{id}/discord-channel", Queue: "rpc.parser.discord_channel.upsert", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/parser/admin/tournaments/{id}/discord-channel", Queue: "rpc.parser.discord_channel.delete", IDParam: "id", Auth: edge.AuthRequired, Success: 204},
}

// AchievementAdminRoutes are the workspace-scoped achievement rule/library/override
// admin endpoints (src/routes/admin/achievement_rule.py), served via the ordered
// edge.Subtree matcher under /api/parser/admin/ws/ (literal segments like
// rules/export collide with rules/{rule_id} under the stdlib ServeMux). ORDER
// MATTERS: literal routes precede the {rule_id} catch-alls. All require auth;
// the workspace "achievement.<action>" permission is enforced in each handler.
var AchievementAdminRoutes = []edge.RouteSpec{
	// --- rules: literal segments first ---
	{Method: "GET", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/condition-types", Queue: "rpc.parser.ach.condition_types", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/validate", Queue: "rpc.parser.ach.validate", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/seed", Queue: "rpc.parser.ach.seed", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/reset", Queue: "rpc.parser.ach.reset", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/export", Queue: "rpc.parser.ach.export", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/import", Queue: "rpc.parser.ach.import", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/runs", Queue: "rpc.parser.ach.runs", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/evaluate", Queue: "rpc.parser.ach.evaluate", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	// --- rules: {rule_id}/<sub> (2-segment) ---
	{Method: "GET", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/{rule_id}/users", Queue: "rpc.parser.ach.rule_users", Path: []string{"workspace_id", "rule_id"}, AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/{rule_id}/test", Queue: "rpc.parser.ach.test", Path: []string{"workspace_id", "rule_id"}, Query: []string{"tournament_id"}, Auth: edge.AuthRequired},
	// --- rules: {rule_id} catch-alls ---
	{Method: "GET", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/{rule_id}", Queue: "rpc.parser.ach.get", Path: []string{"workspace_id", "rule_id"}, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/{rule_id}", Queue: "rpc.parser.ach.update", Path: []string{"workspace_id", "rule_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules/{rule_id}", Queue: "rpc.parser.ach.delete", Path: []string{"workspace_id", "rule_id"}, Auth: edge.AuthRequired, Success: 204},
	// --- rules: collection (list/create) ---
	{Method: "GET", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules", Queue: "rpc.parser.ach.list", Path: []string{"workspace_id"}, AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/rules", Queue: "rpc.parser.ach.create", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	// --- library ---
	{Method: "GET", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/library/workspaces", Queue: "rpc.parser.ach.lib_workspaces", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/library", Queue: "rpc.parser.ach.lib_list", Path: []string{"workspace_id"}, Query: []string{"source_workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/library/import", Queue: "rpc.parser.ach.lib_import", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	// --- overrides ---
	{Method: "GET", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/overrides", Queue: "rpc.parser.ach.overrides_list", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/overrides", Queue: "rpc.parser.ach.override_create", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "DELETE", Pattern: "/api/parser/admin/ws/{workspace_id}/achievements/overrides/{override_id}", Queue: "rpc.parser.ach.override_delete", Path: []string{"workspace_id", "override_id"}, Auth: edge.AuthRequired, Success: 204},
}
