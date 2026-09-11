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
	{Method: "POST", Pattern: "/api/v1/encounters/{encounter_id}/map-pool/{map_id}/report", Queue: "rpc.tournament.captain_report_map", IDParam: "encounter_id", Path: []string{"map_id"}, Body: true, Auth: edge.AuthRequired},
	// pick_ban_session.py — captain ready-up gate, shared by BOTH pick-ban kinds
	// (one confirmation per side covers map veto and hero bans together).
	{Method: "POST", Pattern: "/api/v1/encounters/{encounter_id}/ready", Queue: "rpc.tournament.captain_ready", IDParam: "encounter_id", Auth: edge.AuthRequired},

	// pick_ban_action.py / pick_ban_session.py — generic pregame room (map +
	// hero), used by the unified pick-ban room (design:
	// docs/plans/2026-08-09-generic-pickban-engine.md). `kind` (map|hero)
	// travels as a literal path segment, one route triple for both.
	{Method: "GET", Pattern: "/api/v1/encounters/{encounter_id}/pick-ban/{kind}/state", Queue: "rpc.tournament.captain_pick_ban_state", IDParam: "encounter_id", Path: []string{"kind"}, Auth: edge.AuthOptional},
	{Method: "POST", Pattern: "/api/v1/encounters/{encounter_id}/pick-ban/{kind}/act", Queue: "rpc.tournament.captain_pick_ban_act", IDParam: "encounter_id", Path: []string{"kind"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/encounters/{encounter_id}/pick-ban/{kind}/elect-opener", Queue: "rpc.tournament.captain_pick_ban_elect_opener", IDParam: "encounter_id", Path: []string{"kind"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/encounters/{encounter_id}/pick-ban/{kind}/undo", Queue: "rpc.tournament.captain_pick_ban_undo", IDParam: "encounter_id", Path: []string{"kind"}, Body: true, Auth: edge.AuthRequired},

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
	// `IDParam`, not `Path`: this dispatches into `reads.py`, whose handlers read
	// the path id as `data["id"]` (see its module docstring). Declaring it as
	// `Path` left `data["id"]` unset and 422'd every call.
	{Method: "GET", Pattern: "/api/v1/tournaments/{tournament_id}/pick-ban-configs", Queue: "rpc.tournament.get_pick_ban_configs", IDParam: "tournament_id", Auth: edge.AuthOptional},

	// The public "Teams" roster. AuthOptional like the participants list: anyone
	// may see the field. Invites are omitted server-side, so this cannot leak who
	// was asked and declined.
	{Method: "GET", Pattern: "/api/v1/tournaments/{tournament_id}/registration-teams", Queue: "rpc.tournament.regteam_list_public", Path: []string{"tournament_id"}, Auth: edge.AuthOptional},

	// Who a captain may invite, and what a player has been invited to. Both are
	// AuthRequired reads: the first returns strictly a subset of the public
	// participants list but exists only to act on, and the second is scoped to the
	// caller's own token — "whose invites" is never a path parameter.
	{Method: "GET", Pattern: "/api/v1/tournaments/{tournament_id}/registration-teams/free-agents", Queue: "rpc.tournament.regteam_free_agents", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/tournaments/{tournament_id}/registration-teams/my-invites", Queue: "rpc.tournament.regteam_my_invites", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	// A captain's own invite history. Captaincy-gated in the worker, not by
	// workspace permission — the organizer reads the same rows through the admin
	// route. `{team_id}` and not the caller's identity, because a captain may hold
	// more than one team across tournaments.
	{Method: "GET", Pattern: "/api/v1/registration-teams/{team_id}/invite-history", Queue: "rpc.tournament.regteam_invite_history_public", Path: []string{"team_id"}, Auth: edge.AuthRequired},

	// registration.py — public TEAM registration (captain + invitee flows).
	// See docs/plans/2026-08-20-team-registration.md §4. Every WRITE is
	// AuthRequired: even the link-invite path writes a registration bound to the
	// redeemer's account, so the token authorizes which SLOT you may take, never
	// who you are. The one exception is the invite PREVIEW below, which is
	// deliberately anonymous.
	{Method: "POST", Pattern: "/api/v1/tournaments/{tournament_id}/registration-teams", Queue: "rpc.tournament.regteam_create", Path: []string{"tournament_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "POST", Pattern: "/api/v1/registration-teams/{team_id}/invites", Queue: "rpc.tournament.regteam_invite", Path: []string{"team_id"}, Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "DELETE", Pattern: "/api/v1/registration-teams/invites/{invite_id}", Queue: "rpc.tournament.regteam_invite_revoke", Path: []string{"invite_id"}, Auth: edge.AuthRequired, Success: 204},
	// The only anonymous invite surface: a link invite exists to reach someone with
	// no account, and asking them to sign up before seeing what they were invited
	// to is backwards. POST rather than GET so the token stays in the body — see
	// the note below.
	{Method: "POST", Pattern: "/api/v1/registration-teams/invites/preview", Queue: "rpc.tournament.regteam_invite_preview", Body: true, Auth: edge.AuthOptional},
	// Accept/decline carry the invite reference in the BODY, not the path: a raw
	// token in a URL lands in access logs, browser history and Referer headers.
	{Method: "POST", Pattern: "/api/v1/registration-teams/invites/accept", Queue: "rpc.tournament.regteam_accept", Body: true, Auth: edge.AuthRequired, Success: 201},
	{Method: "POST", Pattern: "/api/v1/registration-teams/invites/decline", Queue: "rpc.tournament.regteam_decline", Body: true, Auth: edge.AuthRequired, Success: 204},
	{Method: "DELETE", Pattern: "/api/v1/registration-teams/{team_id}/members/{registration_id}", Queue: "rpc.tournament.regteam_kick", Path: []string{"team_id", "registration_id"}, Auth: edge.AuthRequired, Success: 204},
	{Method: "DELETE", Pattern: "/api/v1/registration-teams/{team_id}/members/me", Queue: "rpc.tournament.regteam_leave", Path: []string{"team_id"}, Auth: edge.AuthRequired, Success: 204},
	{Method: "POST", Pattern: "/api/v1/registration-teams/{team_id}/captain/{registration_id}", Queue: "rpc.tournament.regteam_transfer_captain", Path: []string{"team_id", "registration_id"}, Auth: edge.AuthRequired, Success: 204},
	{Method: "PATCH", Pattern: "/api/v1/registration-teams/{team_id}", Queue: "rpc.tournament.regteam_rename", Path: []string{"team_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/registration-teams/{team_id}/members/{registration_id}/place", Queue: "rpc.tournament.regteam_place_member", Path: []string{"team_id", "registration_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/registration-teams/{team_id}/members/{registration_id}/manager", Queue: "rpc.tournament.regteam_set_manager", Path: []string{"team_id", "registration_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/registration-teams/{team_id}/invites/{invite_id}/extend", Queue: "rpc.tournament.regteam_extend_invite", Path: []string{"team_id", "invite_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/registration-teams/{team_id}/lock", Queue: "rpc.tournament.regteam_lock", Path: []string{"team_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/registration-teams/{team_id}/check-in", Queue: "rpc.tournament.regteam_check_in", Path: []string{"team_id"}, Body: true, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/registration-teams/{team_id}/subscription/cover", Queue: "rpc.tournament.regteam_cover_subscription", Path: []string{"team_id"}, Body: true, Auth: edge.AuthRequired},
	// NOTE: DELETE /registration-teams/{team_id}/image is NOT here — it is
	// ambiguous with /registration-teams/invites/{invite_id} under the stdlib
	// ServeMux (both match "/registration-teams/invites/image", neither is more
	// specific) and lives in RegistrationTeamSubtreeRoutes below.
	{Method: "DELETE", Pattern: "/api/v1/registration-teams/{team_id}", Queue: "rpc.tournament.regteam_disband", Path: []string{"team_id"}, Auth: edge.AuthRequired, Success: 204},

	// Subscription entitlements — the patron's own standing plus challenge-code
	// redemption (the Boosty fallback for organizers without a Discord server).
	{Method: "GET", Pattern: "/api/v1/tournaments/{tournament_id}/subscription/me", Queue: "rpc.tournament.sub_me", Path: []string{"tournament_id"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/tournaments/{tournament_id}/subscription/redeem-code", Queue: "rpc.tournament.sub_redeem_code", Path: []string{"tournament_id"}, Body: true, Auth: edge.AuthRequired},
}

// RegistrationTeamSubtreeRoutes holds the /api/v1/registration-teams/* routes the
// stdlib ServeMux refuses to register alongside their siblings, served via
// edge.Subtree (ordered match, first wins) mounted at /api/v1/registration-teams/.
// The subtree prefix is less specific than every precise pattern in
// PublicWriteRoutes, so those still win; only what nothing else claims lands here.
//
// Captain-gated in the worker like the rest of the team-registration block — not
// a workspace permission, unlike the admin team-image pair in AdminCrudRoutes.
// The paired multipart upload can't ride the JSON dispatcher at all; it is a
// direct mux.HandleFunc (binary.go), documented in BinaryDocRoutes.
var RegistrationTeamSubtreeRoutes = []edge.RouteSpec{
	{Method: "DELETE", Pattern: "/api/v1/registration-teams/{team_id}/image", Queue: "rpc.tournament.regteam_image_delete", Path: []string{"team_id"}, Auth: edge.AuthRequired},
}
