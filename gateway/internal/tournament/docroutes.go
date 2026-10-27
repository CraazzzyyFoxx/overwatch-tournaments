package tournament

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// BinaryDocRoutes documents the multipart upload endpoints handled by the
// tournament binary handler (binary.go), which the JSON edge.Dispatcher can't
// serve. Documentation-only: keep in sync with the mux.HandleFunc registrations
// in cmd/gateway/main.go. Queue is the RPC subject (manifest lookup key); Media
// is the multipart form. The paired image deletes are plain JSON and live in AdminCrudRoutes /
// PublicWriteRoutes.
var BinaryDocRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/v1/admin/teams/{team_id}/image", Queue: "rpc.tournament.teams.image_upload", Auth: edge.AuthRequired, Media: edge.Media{Files: []string{"file"}}},                           // team logo
	{Method: "POST", Pattern: "/api/v1/registration-teams/{team_id}/image", Queue: "rpc.tournament.regteam_image_upload", Auth: edge.AuthRequired, Media: edge.Media{Files: []string{"file"}}},                  // registered-team crest (captain)
	{Method: "POST", Pattern: "/api/v1/admin/tournaments/{tournament_id}/images/{slot}", Queue: "rpc.tournament.tournaments.image_upload", Auth: edge.AuthRequired, Media: edge.Media{Files: []string{"file"}}}, // tournament cover/logo ({slot})
}
