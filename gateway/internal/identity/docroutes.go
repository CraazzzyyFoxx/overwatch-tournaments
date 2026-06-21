package identity

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// Documentation-only route tables.
//
// The /api/auth/* surface is wired with bespoke handlers in main.go (not via the
// edge.Dispatcher), so these tables exist purely to feed the OpenAPI generator.
// Keep them in sync with the mux.HandleFunc registrations in cmd/gateway/main.go.
// Queue is intentionally empty — the generator falls back to "METHOD /path".

// PublicDocRoutes documents the user-facing identity endpoints (auth, sessions,
// profile, OAuth, API keys, player linking, self-service avatar).
var PublicDocRoutes = []edge.RouteSpec{
	// session lifecycle
	{Method: "POST", Pattern: "/api/auth/validate", Body: true, Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/register", Body: true, Auth: edge.AuthNone, Success: 201},
	{Method: "POST", Pattern: "/api/auth/login", Body: true, Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/refresh", Body: true, Auth: edge.AuthOptional},
	{Method: "POST", Pattern: "/api/auth/logout", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/logout-all", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/auth/sessions", Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/sessions/{id}", Auth: edge.AuthRequired, Success: 204},
	// current user
	{Method: "GET", Pattern: "/api/auth/me", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/auth/me", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/set-password", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/me/avatar", Auth: edge.AuthRequired},   // multipart upload
	{Method: "DELETE", Pattern: "/api/auth/me/avatar", Auth: edge.AuthRequired}, // multipart upload
	// OAuth
	{Method: "GET", Pattern: "/api/auth/providers", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/auth/oauth/providers", Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/auth/oauth/connections", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/auth/oauth/{provider}/url", Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/auth/oauth/{provider}/callback", Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/oauth/{provider}/callback", Body: true, Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/oauth/{provider}/link", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/oauth/{provider}/unlink", Auth: edge.AuthRequired, Success: 204},
	// API keys
	{Method: "GET", Pattern: "/api/auth/api-keys", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/api-keys", Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "PATCH", Pattern: "/api/auth/api-keys/{id}", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/api-keys/{id}", Auth: edge.AuthRequired, Success: 204},
	// player linking
	{Method: "POST", Pattern: "/api/auth/player/link", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/player/unlink/{player_id}", Auth: edge.AuthRequired, Success: 204},
	{Method: "GET", Pattern: "/api/auth/player/linked", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/auth/player/linked/{player_id}/primary", Auth: edge.AuthRequired},
}

// AdminDocRoutes documents the RBAC admin endpoints and the service-to-service
// token endpoints.
var AdminDocRoutes = []edge.RouteSpec{
	// service auth (machine-to-machine)
	{Method: "POST", Pattern: "/api/auth/service/token", Body: true, Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/service/validate", Body: true, Auth: edge.AuthNone},
	{Method: "POST", Pattern: "/api/auth/service/invalidate-session/{user_id}", Auth: edge.AuthRequired},
	// permissions
	{Method: "GET", Pattern: "/api/auth/rbac/permissions", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/rbac/permissions", Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "DELETE", Pattern: "/api/auth/rbac/permissions/{permission_id}", Auth: edge.AuthRequired, Success: 204},
	// roles
	{Method: "GET", Pattern: "/api/auth/rbac/roles", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/rbac/roles", Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "GET", Pattern: "/api/auth/rbac/roles/{role_id}", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/auth/rbac/roles/{role_id}", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/rbac/roles/{role_id}", Auth: edge.AuthRequired, Success: 204},
	// user ↔ role/player administration
	{Method: "GET", Pattern: "/api/auth/rbac/users", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/rbac/users/assign-role", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/rbac/users/remove-role", Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/auth/rbac/users/{user_id}", Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/auth/rbac/users/{user_id}/roles", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/auth/rbac/users/{user_id}/linked-players", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/rbac/users/{user_id}/linked-players/{player_id}", Auth: edge.AuthRequired, Success: 204},
	// oauth connections + sessions (read/manage)
	{Method: "GET", Pattern: "/api/auth/rbac/oauth-connections", Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/auth/rbac/oauth-connections/{connection_id}", Auth: edge.AuthRequired, Success: 204},
	{Method: "GET", Pattern: "/api/auth/rbac/sessions", Auth: edge.AuthRequired},
}
