// Package tournament — gateway route table (continued).
//
// PublicWriteRoutes are the migrated PUBLIC / captain write+read endpoints
// (typed RPC). Mirrors src/routes/{captain,registration,encounter}.py.
//
// Auth:
//   - Captain actions (my-role, report, veto), registration me/create/check-in,
//     and the saved-view writes all require a logged-in user -> AuthRequired.
//   - The captain map-pool read and the public registration form/list reads are
//     visibility-gated (hidden tournaments 404 for ineligible viewers) -> AuthOptional,
//     so an eligible admin/preview viewer's identity reaches the handler; anonymous
//     viewers are still allowed (and see non-hidden tournaments).
//
// The map-pool WebSocket (/{encounter_id}/map-pool/ws) is intentionally NOT here;
// it is re-architected onto the realtime hub separately.
package tournament

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

var PublicWriteRoutes = []edge.RouteSpec{
	// captain.py — encounter result submission + map veto.
	{Method: "GET", Pattern: "/api/v1/encounters/{encounter_id}/my-role", Queue: "rpc.tournament.captain_my_role", IDParam: "encounter_id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/encounters/{encounter_id}/report", Queue: "rpc.tournament.captain_submit_report", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/encounters/{encounter_id}/reports", Queue: "rpc.tournament.captain_reports", IDParam: "encounter_id", Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/encounters/{encounter_id}/map-pool", Queue: "rpc.tournament.captain_map_pool", IDParam: "encounter_id", Auth: edge.AuthOptional},
	{Method: "GET", Pattern: "/api/v1/encounters/{encounter_id}/map-pool/state", Queue: "rpc.tournament.captain_map_pool_state", IDParam: "encounter_id", Auth: edge.AuthOptional},
	{Method: "POST", Pattern: "/api/v1/encounters/{encounter_id}/map-pool/veto", Queue: "rpc.tournament.captain_veto", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},

	// encounter.py — saved-view writes (the GET /views read is already migrated).
	{Method: "POST", Pattern: "/api/v1/encounters/views", Queue: "rpc.tournament.saved_view_create", Query: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired, Success: 200},
	{Method: "DELETE", Pattern: "/api/v1/encounters/views/{saved_view_id}", Queue: "rpc.tournament.saved_view_delete", Path: []string{"saved_view_id"}, Query: []string{"workspace_id"}, Auth: edge.AuthRequired, Success: 204},

	// registration.py — public user sign-up (prefix /tournaments/{tournament_id}/registration).
	{Method: "GET", Pattern: "/api/v1/tournaments/{tournament_id}/registration/form", Queue: "rpc.tournament.reg_pub_form", Path: []string{"tournament_id"}, Auth: edge.AuthOptional},
	{Method: "POST", Pattern: "/api/v1/tournaments/{tournament_id}/registration", Queue: "rpc.tournament.reg_pub_create", Path: []string{"tournament_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "GET", Pattern: "/api/v1/tournaments/{tournament_id}/registration/me", Queue: "rpc.tournament.reg_pub_get_me", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/tournaments/{tournament_id}/registration/me", Queue: "rpc.tournament.reg_pub_update_me", Path: []string{"tournament_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/tournaments/{tournament_id}/registration/me", Queue: "rpc.tournament.reg_pub_withdraw_me", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/tournaments/{tournament_id}/registration/me/check-in", Queue: "rpc.tournament.reg_pub_check_in", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/tournaments/{tournament_id}/registration/list", Queue: "rpc.tournament.reg_pub_list", Path: []string{"tournament_id"}, Auth: edge.AuthOptional},
}
