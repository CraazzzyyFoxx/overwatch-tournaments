package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// WorkspaceWriteRoutes are the authenticated workspace mutations. create is
// superuser-global; update/delete go through the shared CRUD engine
// (Entity=workspace); member ops are workspace-scoped. All require identity
// (AuthRequired); the worker enforces superuser / workspace permission.
//
// These are flat: distinct methods + segment counts mean no ServeMux conflict
// with the Phase 1 GET /workspaces and GET /workspaces/{id} reads.
var WorkspaceWriteRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/v1/workspaces", Queue: "rpc.app.workspaces.create", Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "PATCH", Pattern: "/api/v1/workspaces/{id}", Queue: "rpc.app.admin.update", Entity: "workspace", Action: "update", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/workspaces/{id}", Queue: "rpc.app.admin.delete", Entity: "workspace", Action: "delete", IDParam: "id", Auth: edge.AuthRequired, Success: 204},
	{Method: "GET", Pattern: "/api/v1/workspaces/{workspace_id}/members", Queue: "rpc.app.workspaces.members_list", Path: []string{"workspace_id"}, AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/workspaces/{workspace_id}/members/autofill-roles", Queue: "rpc.app.workspaces.members_autofill_roles", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/workspaces/{workspace_id}/members", Queue: "rpc.app.workspaces.member_add", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "PATCH", Pattern: "/api/v1/workspaces/{workspace_id}/members/{auth_user_id}", Queue: "rpc.app.workspaces.member_update", Path: []string{"workspace_id", "auth_user_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/workspaces/{workspace_id}/members/{auth_user_id}", Queue: "rpc.app.workspaces.member_remove", Path: []string{"workspace_id", "auth_user_id"}, Auth: edge.AuthRequired, Success: 204},
	// --- custom domain (white-label Phase 2): set stores + tokens (unverified),
	// verify DNS-checks the TXT record, clear removes it. All workspace.update.
	{Method: "POST", Pattern: "/api/v1/workspaces/{workspace_id}/custom-domain", Queue: "rpc.app.workspaces.set_custom_domain", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/workspaces/{workspace_id}/custom-domain/verify", Queue: "rpc.app.workspaces.verify_custom_domain", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/workspaces/{workspace_id}/custom-domain", Queue: "rpc.app.workspaces.clear_custom_domain", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	// --- discord entities: read the linked guild's roles, text channels and
	// connection status for the workspace settings pickers. Reads, but gated on
	// workspace.update in the worker like the custom-domain endpoints -- a guild's
	// role and channel names are not public.
	{Method: "GET", Pattern: "/api/v1/workspaces/{workspace_id}/discord/roles", Queue: "rpc.app.workspaces.discord_roles", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/workspaces/{workspace_id}/discord/channels", Queue: "rpc.app.workspaces.discord_channels", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/workspaces/{workspace_id}/discord/guild", Queue: "rpc.app.workspaces.discord_guild", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	// --- discord guild verification (self-service design §4.1): proves the
	// caller administers the guild on Discord (via identity-service) before it
	// can be bound to the workspace. workspace.update, like every sibling here.
	{Method: "POST", Pattern: "/api/v1/workspaces/{workspace_id}/discord-guild", Queue: "rpc.app.workspaces.discord_guild_verify", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/workspaces/{workspace_id}/discord-guild", Queue: "rpc.app.workspaces.discord_guild_clear", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	// --- verification tier (self-service design §4.2): superuser sets a
	// workspace's verification_status (unverified/verified/trusted), which
	// gates public directory listing. Enforced in app-service, not here.
	{Method: "POST", Pattern: "/api/v1/workspaces/{workspace_id}/verification", Queue: "rpc.app.workspaces.verification_set", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	// --- owner: resolves owner_id to a person (GET, workspace.update in the
	// worker like the discord_* reads -- the public workspace model carries no
	// owner at all), and reassigns it (PUT, superuser-only: owner_id is what the
	// per-account create cap is counted over).
	{Method: "GET", Pattern: "/api/v1/workspaces/{workspace_id}/owner", Queue: "rpc.app.workspaces.owner_get", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/v1/workspaces/{workspace_id}/owner", Queue: "rpc.app.workspaces.owner_set", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	// Transfer moves the stamp and the owner role together, and is open to the
	// current owner as well as superusers -- the person on the hook is the one
	// entitled to get off it. Enforced in app-service, not here.
	{Method: "POST", Pattern: "/api/v1/workspaces/{workspace_id}/owner/transfer", Queue: "rpc.app.workspaces.owner_transfer", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
}
