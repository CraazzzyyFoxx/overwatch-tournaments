package balancer

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// Documentation-only tables for the multipart upload endpoints handled by the
// balancer binary handler (binary.go). Keep in sync with the mux.HandleFunc
// registrations in cmd/gateway/main.go. Queue is the RPC subject (manifest key);
// Media is the multipart form the handler reads.

// BinaryPublicDocRoutes is the user-facing balance job creation (pairs with the
// JobRoutes status/result reads).
var BinaryPublicDocRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/v1/balancer/jobs", Queue: "rpc.balancer.jobs.create", Auth: edge.AuthRequired, Success: 202,
		Media: edge.Media{Files: []string{"player_data_file"}, Fields: []string{"config_overrides", "tournament_id"}}},
}

// LobbyCallbackDocRoutes documents the public webhook a game source calls to report a bot lobby's match
// (callback.go): the token in the path is the credential, every token is answered 204.
var LobbyCallbackDocRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/v1/lobby-bot/callback/{token}", Queue: "rpc.balancer.custom.bot_lobby_callback", Path: []string{"token"}, Auth: edge.AuthNone, Success: 204},
	{Method: "POST", Pattern: "/api/v1/lobby-bot/callback/{token}/settings", Queue: "rpc.balancer.custom.bot_lobby_callback", Path: []string{"token"}, Auth: edge.AuthNone, Success: 204},
}

// BinaryAdminDocRoutes is the admin teams-import upload.
var BinaryAdminDocRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/v1/balancer/tournaments/{tournament_id}/teams/import", Queue: "rpc.balancer.admin.teams_import", Query: []string{"formation_node_id"}, Auth: edge.AuthRequired,
		Media: edge.Media{Files: []string{"data"}, Fields: []string{"payload_format"}}},
}
