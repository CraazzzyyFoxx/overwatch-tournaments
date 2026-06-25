package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// BinaryDocRoutes documents the multipart/download endpoints handled by the
// app binary handler (binary.go), which the JSON edge.Dispatcher can't serve.
// Documentation-only: keep in sync with the mux.HandleFunc registrations in
// cmd/gateway/main.go. Queue is the RPC subject (manifest lookup key). All are
// admin-surface (AuthRequired).
var BinaryDocRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/v1/workspaces/{id}/icon", Queue: "rpc.app.workspaces.icon_upload", Auth: edge.AuthRequired},   // multipart upload
	{Method: "DELETE", Pattern: "/api/v1/workspaces/{id}/icon", Queue: "rpc.app.workspaces.icon_delete", Auth: edge.AuthRequired}, // remove icon
	{Method: "POST", Pattern: "/api/v1/assets/{asset_type}/{slug}", Queue: "rpc.app.assets.upload", Auth: edge.AuthRequired},      // multipart upload
	{Method: "DELETE", Pattern: "/api/v1/assets/{asset_type}/{slug}", Queue: "rpc.app.assets.delete", Auth: edge.AuthRequired},    // remove asset
	{Method: "GET", Pattern: "/api/v1/matches/{match_id}/log", Queue: "rpc.app.matches.log", Auth: edge.AuthRequired},             // match-log download (raw bytes)
	{Method: "POST", Pattern: "/api/v1/admin/users/{id}/avatar", Queue: "rpc.app.users.avatar_upload", Auth: edge.AuthRequired},   // multipart upload
	{Method: "POST", Pattern: "/api/v1/user/create/csv", Queue: "rpc.app.users.csv_import", Auth: edge.AuthRequired},              // CSV/Sheets user import
}
