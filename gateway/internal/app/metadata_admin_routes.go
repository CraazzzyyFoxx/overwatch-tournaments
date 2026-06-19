package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// MetadataAdminRoutes are the game-metadata admin CRUD endpoints (hero / map /
// gamemode), relocated from parser-service into app-service (which already owns
// the public reads). All require auth; the global "<entity>.<action>" permission
// is enforced in the worker handler. Served under /api/v1/core/admin/* (the
// frontend calls apiFetch("app", "admin/<entity>")).
var MetadataAdminRoutes = []edge.RouteSpec{
	// heroes
	{Method: "GET", Pattern: "/api/v1/core/admin/heroes", Queue: "rpc.app.heroes.admin_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/core/admin/heroes", Queue: "rpc.app.heroes.admin_create", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/core/admin/heroes/{id}", Queue: "rpc.app.heroes.admin_update", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/core/admin/heroes/{id}", Queue: "rpc.app.heroes.admin_delete", IDParam: "id", Auth: edge.AuthRequired, Success: 204},
	// maps
	{Method: "GET", Pattern: "/api/v1/core/admin/maps", Queue: "rpc.app.maps.admin_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/core/admin/maps", Queue: "rpc.app.maps.admin_create", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/core/admin/maps/{id}", Queue: "rpc.app.maps.admin_update", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/core/admin/maps/{id}", Queue: "rpc.app.maps.admin_delete", IDParam: "id", Auth: edge.AuthRequired, Success: 204},
	// gamemodes
	{Method: "GET", Pattern: "/api/v1/core/admin/gamemodes", Queue: "rpc.app.gamemodes.admin_list", AllQuery: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/core/admin/gamemodes", Queue: "rpc.app.gamemodes.admin_create", Body: true, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/core/admin/gamemodes/{id}", Queue: "rpc.app.gamemodes.admin_update", IDParam: "id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/core/admin/gamemodes/{id}", Queue: "rpc.app.gamemodes.admin_delete", IDParam: "id", Auth: edge.AuthRequired, Success: 204},
}
