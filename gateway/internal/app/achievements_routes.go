package app

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// AchievementsSubtreeRoutes is mounted at /api/v1/achievements/ via the
// ordered edge.Subtree matcher. Plain Register would panic: /{id}/users and
// /user/{user_id} are both 2-segment and cross-specific (neither is uniformly
// more specific), which the stdlib ServeMux rejects. First-match-wins order
// mirrors FastAPI declaration order (literal-bearing patterns before the bare
// {id} get).
//
// The achievements *list* (/api/v1/achievements, no trailing slash) is a
// flat ReadRoutes entry — the subtree mount only covers /achievements/*.
var AchievementsSubtreeRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/achievements/user/{user_id}", Queue: "rpc.app.achievements.user", IDParam: "user_id", AllQuery: true, Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/achievements/{id}/users", Queue: "rpc.app.achievements.users", IDParam: "id", AllQuery: true, Auth: edge.AuthNone},
	{Method: "GET", Pattern: "/api/v1/achievements/{id}", Queue: "rpc.app.read.get", Entity: "achievement", Action: "get", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthNone},
}
