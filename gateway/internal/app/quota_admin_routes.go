package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// QuotaAdminRoutes are the platform-wide quota policy: the plans every tenant
// inherits from, and what each metered operation costs. Superuser-only, and
// enforced in app-service -- the edge only requires a credential.
//
// Deliberately not workspace-scoped: a plan is the platform's statement, and a
// tenant's own deviation from it is the per-workspace override in
// WorkspaceWriteRoutes. Both writes are PUT-shaped upserts keyed by slug rather
// than POST/PATCH pairs, because a plan is read as a complete statement of its
// tier (a partial update would leave a scope nobody remembers setting).
var QuotaAdminRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/admin/quota/plans", Queue: "rpc.app.quota.plans", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/v1/admin/quota/plans", Queue: "rpc.app.quota.plan_upsert", Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/quota/operations", Queue: "rpc.app.quota.operations", Auth: edge.AuthRequired},
	{Method: "PUT", Pattern: "/api/v1/admin/quota/operations", Queue: "rpc.app.quota.operation_upsert", Body: true, Auth: edge.AuthRequired},
}
