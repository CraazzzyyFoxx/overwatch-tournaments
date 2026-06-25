package parser

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// BinaryDocRoutes documents the multipart upload endpoints handled by the parser
// binary handler (binary.go). Documentation-only: keep in sync with the
// mux.HandleFunc registrations in cmd/gateway/main.go. Queue is the RPC subject
// (manifest lookup key). Admin-surface.
var BinaryDocRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/v1/admin/logs/upload", Queue: "rpc.parser.logs.upload", Auth: edge.AuthRequired},               // match-log files upload
	{Method: "POST", Pattern: "/api/v1/teams/create/balancer", Queue: "rpc.parser.teams.create_balancer", Auth: edge.AuthRequired}, // balancer teams import
}
