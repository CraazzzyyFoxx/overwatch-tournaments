package balancer

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// Documentation-only tables for the multipart upload endpoints handled by the
// balancer binary handler (binary.go). Keep in sync with the mux.HandleFunc
// registrations in cmd/gateway/main.go. Queue is the RPC subject (manifest key).

// BinaryPublicDocRoutes is the user-facing balance job creation (pairs with the
// JobRoutes status/result reads).
var BinaryPublicDocRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/balancer/jobs", Queue: "rpc.balancer.jobs.create", Auth: edge.AuthRequired, Success: 202}, // multipart: create balance job
}

// BinaryAdminDocRoutes is the admin teams-import upload.
var BinaryAdminDocRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/balancer/tournaments/{tournament_id}/teams/import", Queue: "rpc.balancer.admin.teams_import", Auth: edge.AuthRequired}, // multipart
}
