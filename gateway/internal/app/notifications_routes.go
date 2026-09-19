package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// NotificationRoutes is the personal inbox: a paginated read, the bulk
// read-mark write and the delete. All AuthRequired — the audience is computed
// in the worker from the injected identity alone, never from a client-supplied
// id, so there is nothing here to serve without one.
//
// Delete is a POST to a verb path rather than DELETE /api/v1/notifications: the
// body carries the id list (and the "clear read" flag), and a request body on
// DELETE is the part of HTTP that caches, proxies and fetch polyfills disagree
// about. It is the same shape as the sibling /read write.
var NotificationRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/notifications", Queue: "rpc.app.notifications_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/notifications/read", Queue: "rpc.app.notifications_mark_read", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/notifications/delete", Queue: "rpc.app.notifications_delete", Body: true, Auth: edge.AuthRequired},
}

// NotificationAdminRoutes is the operator screen for the notifications a
// workspace's own activity produced (notification.source_workspace_id).
//
// AuthRequired only; the real gate is notification.read / notification.delete
// inside the workspace the request names, checked in app-service. There is no
// platform-wide variant on purpose — unlike announcements, every row here
// belongs to exactly one tenant, so an unscoped list would be a cross-tenant
// read with no workspace to authorize or audit it against.
//
// Retire is a POST with a body rather than DELETE /{id}: it takes a selection
// or a whole kind, which is a filter, not a path segment.
var NotificationAdminRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/admin/notifications", Queue: "rpc.app.notification_admin_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/notifications/retire", Queue: "rpc.app.notification_admin_retire", Body: true, Auth: edge.AuthRequired},
}

// AnnouncementPublicRoutes serves the site-wide banner.
//
// AuthOptional, not AuthNone: under AuthNone the dispatcher never injects
// data["identity"], so the worker could not filter out the announcements this
// viewer already dismissed — every logged-in reader would keep seeing them.
// stream.PublicRoutes documents the same choice for the same reason. Anonymous
// visitors still reach it and get the global-audience rows.
var AnnouncementPublicRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/announcements/active", Queue: "rpc.app.active_announcements", Auth: edge.AuthOptional},
}

// AnnouncementAdminRoutes is the operator CRUD. AuthRequired only; which
// principal is actually needed depends on the row's audience (workspace grant
// vs. platform superuser) and is decided in app-service, which is the only
// side that can see the stored audience of an existing row.
var AnnouncementAdminRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/admin/announcements", Queue: "rpc.app.announcement_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/announcements", Queue: "rpc.app.announcement_create", Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "PATCH", Pattern: "/api/v1/admin/announcements/{id}", Queue: "rpc.app.announcement_update", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/admin/announcements/{id}", Queue: "rpc.app.announcement_delete", IDParam: "id", Auth: edge.AuthRequired, Success: 204},
}
