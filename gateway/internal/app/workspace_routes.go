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
}
