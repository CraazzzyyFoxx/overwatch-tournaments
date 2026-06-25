package tournament

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// StageSubtreeRoutes covers ALL /api/v1/admin/stages/* routing — stage CRUD + list
// (generic engine), stage_item/stage_item_input create/update (generic engine), and
// the stage workflows (typed rpc.tournament.stage_*). The patterns are ambiguous
// under the stdlib ServeMux (e.g. /stages/tournament/{id} vs /stages/{id}/items), so
// they are served via edge.Subtree (ordered, first-match-wins) mounted at
// /api/v1/admin/stages/. ORDER: literal-prefix + longer paths first; the
// /{stage_id}/... wildcard forms after their literal siblings.
var StageSubtreeRoutes = []edge.RouteSpec{
	// tournament-scoped (literal "tournament")
	{Method: "GET", Pattern: "/api/v1/admin/stages/tournament/{tournament_id}/progress", Queue: "rpc.tournament.stage_progress", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/admin/stages/tournament/{tournament_id}", Queue: "rpc.tournament.admin.list", Entity: "stage", Action: "list", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/stages/tournament/{tournament_id}", Queue: "rpc.tournament.admin.create", Entity: "stage", Action: "create", Path: []string{"tournament_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	// stage_item / stage_item_input (literal "items"/"inputs")
	{Method: "PATCH", Pattern: "/api/v1/admin/stages/items/inputs/{input_id}", Queue: "rpc.tournament.admin.update", Entity: "stage_item_input", Action: "update", IDParam: "input_id", Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/stages/items/{stage_item_id}/inputs", Queue: "rpc.tournament.admin.create", Entity: "stage_item_input", Action: "create", Path: []string{"stage_item_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "PATCH", Pattern: "/api/v1/admin/stages/items/{stage_item_id}", Queue: "rpc.tournament.admin.update", Entity: "stage_item", Action: "update", IDParam: "stage_item_id", Body: true, Auth: edge.AuthRequired},
	// stage workflows (literal verb after {stage_id})
	{Method: "POST", Pattern: "/api/v1/admin/stages/{stage_id}/merge-group-stages", Queue: "rpc.tournament.stage_merge", Path: []string{"stage_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/stages/{stage_id}/activate-and-generate", Queue: "rpc.tournament.stage_activate_and_generate", Path: []string{"stage_id"}, Query: []string{"force"}, Auth: edge.AuthRequired, Success: 202},
	{Method: "POST", Pattern: "/api/v1/admin/stages/{stage_id}/activate", Queue: "rpc.tournament.stage_activate", Path: []string{"stage_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/stages/{stage_id}/generate", Queue: "rpc.tournament.stage_generate", Path: []string{"stage_id"}, Auth: edge.AuthRequired, Success: 202},
	{Method: "POST", Pattern: "/api/v1/admin/stages/{stage_id}/wire-from-groups", Queue: "rpc.tournament.stage_wire", Path: []string{"stage_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/stages/{stage_id}/seed-teams", Queue: "rpc.tournament.stage_seed", Path: []string{"stage_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/stages/{stage_id}/items", Queue: "rpc.tournament.admin.create", Entity: "stage_item", Action: "create", Path: []string{"stage_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	// stage CRUD by id
	{Method: "GET", Pattern: "/api/v1/admin/stages/{stage_id}", Queue: "rpc.tournament.admin.get", Entity: "stage", Action: "get", IDParam: "stage_id", Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/admin/stages/{stage_id}", Queue: "rpc.tournament.admin.update", Entity: "stage", Action: "update", IDParam: "stage_id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/admin/stages/{stage_id}", Queue: "rpc.tournament.admin.delete", Entity: "stage", Action: "delete", IDParam: "stage_id", Auth: edge.AuthRequired, Success: 204},
}
