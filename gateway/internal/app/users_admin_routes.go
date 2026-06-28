package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// UsersAdminRoutes are the user + identity admin CRUD + profile-merge endpoints,
// relocated from parser-service into app-service (which owns user reads). All
// require auth; the global "user.<action>" permission (or superuser for merge)
// is enforced in the worker handler. Served under /api/v1/admin/users/*
// (frontend calls apiFetch("app", "admin/users...")). Avatar upload + CSV import
// are multipart -> base64 binary handlers (see binary.go), not in this table.
var UsersAdminRoutes = []edge.RouteSpec{
	// user CRUD
	{Method: "GET", Pattern: "/api/v1/admin/users", Queue: "rpc.app.users.admin_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/users", Queue: "rpc.app.users.admin_create", Body: true, Auth: edge.AuthRequired},
	// profile merge (superuser in handler)
	{Method: "POST", Pattern: "/api/v1/admin/users/merge/preview", Queue: "rpc.app.users.merge_preview", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/users/merge/execute", Queue: "rpc.app.users.merge_execute", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/users/{id}", Queue: "rpc.app.users.admin_update", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/admin/users/{id}", Queue: "rpc.app.users.admin_delete", IDParam: "id", Auth: edge.AuthRequired, Success: 204},
	// Social identities (unified) — all return the refreshed UserRead (200 + body)
	{Method: "POST", Pattern: "/api/v1/admin/users/{id}/social", Queue: "rpc.app.users.social_add", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/users/{id}/social/{account_id}", Queue: "rpc.app.users.social_update", IDParam: "id", Path: []string{"account_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/admin/users/{id}/social/{account_id}", Queue: "rpc.app.users.social_delete", IDParam: "id", Path: []string{"account_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/users/{id}/social/{account_id}/primary", Queue: "rpc.app.users.social_set_primary", IDParam: "id", Path: []string{"account_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/users/{id}/social/{account_id}/visibility", Queue: "rpc.app.users.social_set_visibility", IDParam: "id", Path: []string{"account_id"}, Body: true, Auth: edge.AuthRequired},
	// avatar delete (JSON; upload is the multipart binary handler)
	{Method: "DELETE", Pattern: "/api/v1/admin/users/{id}/avatar", Queue: "rpc.app.users.avatar_delete", IDParam: "id", Auth: edge.AuthRequired},
}
