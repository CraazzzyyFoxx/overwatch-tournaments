package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// BinaryDocRoutes documents the multipart/download endpoints handled by the
// app binary handler (binary.go), which the JSON edge.Dispatcher can't serve.
// Documentation-only: keep in sync with the mux.HandleFunc registrations in
// cmd/gateway/main.go. All are admin-surface (AuthRequired).
var BinaryDocRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/v1/workspaces/{id}/icon", Auth: edge.AuthRequired},         // multipart upload
	{Method: "DELETE", Pattern: "/api/v1/workspaces/{id}/icon", Auth: edge.AuthRequired},       // remove icon
	{Method: "POST", Pattern: "/api/v1/assets/{asset_type}/{slug}", Auth: edge.AuthRequired},   // multipart upload
	{Method: "DELETE", Pattern: "/api/v1/assets/{asset_type}/{slug}", Auth: edge.AuthRequired}, // remove asset
	{Method: "GET", Pattern: "/api/v1/matches/{match_id}/log", Auth: edge.AuthRequired},        // match-log download
	{Method: "POST", Pattern: "/api/v1/admin/users/{id}/avatar", Auth: edge.AuthRequired},      // multipart upload
	{Method: "POST", Pattern: "/api/v1/user/create/csv", Auth: edge.AuthRequired},              // CSV/Sheets user import
}
