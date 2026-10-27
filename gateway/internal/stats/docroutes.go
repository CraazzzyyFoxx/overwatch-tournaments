package stats

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// BinaryDocRoutes documents the multipart upload endpoints handled by the stats
// binary handler (binary.go). Documentation-only: keep in sync with the
// mux.HandleFunc registrations in cmd/gateway/main.go. Queue is the RPC subject
// (manifest lookup key); Media is the multipart form. Admin-surface.
var BinaryDocRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/v1/admin/logs/upload", Queue: "rpc.stats.logs.upload", Auth: edge.AuthRequired,
		Media: edge.Media{Files: []string{"files[]"}, Fields: []string{"tournament_id", "encounter_id"}}},
}
