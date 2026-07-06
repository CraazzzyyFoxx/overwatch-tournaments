package identity

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// Documentation-only route tables.
//
// The /api/auth/* surface is wired with bespoke handlers in main.go (not via the
// edge.Dispatcher), so these tables exist purely to feed the OpenAPI generator.
// Keep them in sync with the mux.HandleFunc registrations in cmd/gateway/main.go.
// Queue is the RPC subject the handler dispatches to — it is the manifest lookup
// key that resolves the request/response schema (see internal/openapi).

// PublicDocRoutes documents the user-facing identity endpoints (auth, sessions,
// profile, OAuth, API keys, player linking, self-service avatar).
var PublicDocRoutes = []edge.RouteSpec{
	// session lifecycle
	{Method: "POST", Pattern: "/api/auth/validate", Queue: "rpc.identity.validate_token", Body: true, Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/register", Queue: "rpc.identity.register", Body: true, Auth: edge.AuthNone, Success: 201},
	{Method: "POST", Pattern: "/api/auth/login", Queue: "rpc.identity.login", Body: true, Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/refresh", Queue: "rpc.identity.refresh", Body: true, Auth: edge.AuthOptional},
	{Method: "POST", Pattern: "/api/auth/logout", Queue: "rpc.identity.logout", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/logout-all", Queue: "rpc.identity.logout_all", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/auth/sessions", Queue: "rpc.identity.list_sessions", Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/sessions/{id}", Queue: "rpc.identity.revoke_session", Auth: edge.AuthRequired, Success: 204},
	// current user
	{Method: "GET", Pattern: "/api/auth/me", Queue: "rpc.identity.get_me", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/auth/me", Queue: "rpc.identity.update_me", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/set-password", Queue: "rpc.identity.set_password", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/me/avatar", Queue: "rpc.identity.me.avatar_set", Auth: edge.AuthRequired},      // multipart upload
	{Method: "DELETE", Pattern: "/api/auth/me/avatar", Queue: "rpc.identity.me.avatar_delete", Auth: edge.AuthRequired}, // multipart upload
	// OAuth
	{Method: "GET", Pattern: "/api/auth/providers", Queue: "rpc.identity.oauth_providers", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/auth/oauth/providers", Queue: "rpc.identity.oauth_providers", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/auth/oauth/connections", Queue: "rpc.identity.oauth_connections", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/auth/oauth/{provider}/url", Queue: "rpc.identity.oauth_url", Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/auth/oauth/{provider}/callback", Queue: "rpc.identity.oauth_callback", Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/oauth/{provider}/callback", Queue: "rpc.identity.oauth_callback", Body: true, Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/oauth/{provider}/link", Queue: "rpc.identity.oauth_link", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/oauth/{provider}/unlink", Queue: "rpc.identity.oauth_unlink", Auth: edge.AuthRequired, Success: 204},
	// API keys
	{Method: "GET", Pattern: "/api/auth/api-keys", Queue: "rpc.identity.list_api_keys", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/api-keys", Queue: "rpc.identity.create_api_key", Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "PATCH", Pattern: "/api/auth/api-keys/{id}", Queue: "rpc.identity.update_api_key", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/api-keys/{id}", Queue: "rpc.identity.revoke_api_key", Auth: edge.AuthRequired, Success: 204},
	// player linking
	{Method: "POST", Pattern: "/api/auth/player/link", Queue: "rpc.identity.player.link", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/player/unlink/{player_id}", Queue: "rpc.identity.player.unlink", Auth: edge.AuthRequired, Success: 204},
	{Method: "GET", Pattern: "/api/auth/player/linked", Queue: "rpc.identity.player.linked", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/auth/player/linked/{player_id}/primary", Queue: "rpc.identity.player.set_primary", Auth: edge.AuthRequired},
}

// AdminDocRoutes documents the RBAC admin endpoints and the service-to-service
// token endpoints.
var AdminDocRoutes = []edge.RouteSpec{
	// service auth (machine-to-machine)
	{Method: "POST", Pattern: "/api/auth/service/token", Queue: "rpc.identity.service_token", Body: true, Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/service/validate", Queue: "rpc.identity.validate_service_token", Body: true, Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/service/invalidate-session/{user_id}", Queue: "rpc.identity.invalidate_session", Auth: edge.AuthRequired},
	// permissions
	{Method: "GET", Pattern: "/api/auth/rbac/permissions", Queue: "rpc.identity.rbac.list_permissions", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/rbac/permissions", Queue: "rpc.identity.rbac.create_permission", Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "DELETE", Pattern: "/api/auth/rbac/permissions/{permission_id}", Queue: "rpc.identity.rbac.delete_permission", Auth: edge.AuthRequired, Success: 204},
	// roles
	{Method: "GET", Pattern: "/api/auth/rbac/roles", Queue: "rpc.identity.rbac.list_roles", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/rbac/roles", Queue: "rpc.identity.rbac.create_role", Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "GET", Pattern: "/api/auth/rbac/roles/{role_id}", Queue: "rpc.identity.rbac.get_role", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/auth/rbac/roles/{role_id}", Queue: "rpc.identity.rbac.update_role", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/rbac/roles/{role_id}", Queue: "rpc.identity.rbac.delete_role", Auth: edge.AuthRequired, Success: 204},
	// user ↔ role/player administration
	{Method: "GET", Pattern: "/api/auth/rbac/users", Queue: "rpc.identity.rbac.list_auth_users", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/rbac/users/assign-role", Queue: "rpc.identity.rbac.assign_role", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/rbac/users/remove-role", Queue: "rpc.identity.rbac.remove_role", Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/auth/rbac/users/{user_id}", Queue: "rpc.identity.rbac.get_auth_user", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/auth/rbac/users/{user_id}/roles", Queue: "rpc.identity.rbac.get_user_roles", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/auth/rbac/users/{user_id}/denies", Queue: "rpc.identity.rbac.list_user_denies", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/rbac/users/{user_id}/denies", Queue: "rpc.identity.rbac.add_user_deny", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/rbac/users/{user_id}/denies/{permission_id}", Queue: "rpc.identity.rbac.remove_user_deny", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/rbac/users/{user_id}/linked-players", Queue: "rpc.identity.rbac.assign_linked_player", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/rbac/users/{user_id}/linked-players/{player_id}", Queue: "rpc.identity.rbac.remove_linked_player", Auth: edge.AuthRequired, Success: 204},
	// oauth connections + sessions (read/manage)
	{Method: "GET", Pattern: "/api/auth/rbac/oauth-connections", Queue: "rpc.identity.rbac.list_oauth_connections", Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/rbac/oauth-connections/{connection_id}", Queue: "rpc.identity.rbac.delete_oauth_connection", Auth: edge.AuthRequired, Success: 204},
	{Method: "GET", Pattern: "/api/auth/rbac/sessions", Queue: "rpc.identity.rbac.list_sessions", Auth: edge.AuthRequired},
}
