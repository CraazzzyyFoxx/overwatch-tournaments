package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// UsersAdminRoutes are the user + identity admin CRUD + profile-merge endpoints,
// relocated from parser-service into app-service (which owns user reads). All
// require auth; the global "user.<action>" permission (or superuser for merge)
// is enforced in the worker handler. Served under /api/v1/core/admin/users/*
// (frontend calls apiFetch("app", "admin/users...")). Avatar upload + CSV import
// are multipart -> base64 binary handlers (see binary.go), not in this table.
var UsersAdminRoutes = []edge.RouteSpec{
	// user CRUD
	{Method: "GET", Pattern: "/api/v1/core/admin/users", Queue: "rpc.app.users.admin_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/core/admin/users", Queue: "rpc.app.users.admin_create", Body: true, Auth: edge.AuthRequired},
	// profile merge (superuser in handler)
	{Method: "POST", Pattern: "/api/v1/core/admin/users/merge/preview", Queue: "rpc.app.users.merge_preview", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/core/admin/users/merge/execute", Queue: "rpc.app.users.merge_execute", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/core/admin/users/{id}", Queue: "rpc.app.users.admin_update", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/core/admin/users/{id}", Queue: "rpc.app.users.admin_delete", IDParam: "id", Auth: edge.AuthRequired, Success: 204},
	// Discord identities
	{Method: "POST", Pattern: "/api/v1/core/admin/users/{id}/discord", Queue: "rpc.app.users.discord_add", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/core/admin/users/{id}/discord/{identity_id}", Queue: "rpc.app.users.discord_update", IDParam: "id", Path: []string{"identity_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/core/admin/users/{id}/discord/{identity_id}", Queue: "rpc.app.users.discord_delete", IDParam: "id", Path: []string{"identity_id"}, Auth: edge.AuthRequired, Success: 204},
	// BattleTag identities
	{Method: "POST", Pattern: "/api/v1/core/admin/users/{id}/battle-tag", Queue: "rpc.app.users.battletag_add", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/core/admin/users/{id}/battle-tag/{identity_id}", Queue: "rpc.app.users.battletag_update", IDParam: "id", Path: []string{"identity_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/core/admin/users/{id}/battle-tag/{identity_id}", Queue: "rpc.app.users.battletag_delete", IDParam: "id", Path: []string{"identity_id"}, Auth: edge.AuthRequired, Success: 204},
	// Twitch identities
	{Method: "POST", Pattern: "/api/v1/core/admin/users/{id}/twitch", Queue: "rpc.app.users.twitch_add", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/core/admin/users/{id}/twitch/{identity_id}", Queue: "rpc.app.users.twitch_update", IDParam: "id", Path: []string{"identity_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/core/admin/users/{id}/twitch/{identity_id}", Queue: "rpc.app.users.twitch_delete", IDParam: "id", Path: []string{"identity_id"}, Auth: edge.AuthRequired, Success: 204},
	// avatar delete (JSON; upload is the multipart binary handler)
	{Method: "DELETE", Pattern: "/api/v1/core/admin/users/{id}/avatar", Queue: "rpc.app.users.avatar_delete", IDParam: "id", Auth: edge.AuthRequired},
}
