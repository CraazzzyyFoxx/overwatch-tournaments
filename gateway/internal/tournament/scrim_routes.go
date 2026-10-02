package tournament

import "github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"

// ScrimRoutes are the ad-hoc pre-game ("scrim") room endpoints served by typed
// RPC methods in src/rpc/scrim.py (design:
// docs/plans/2026-08-12-scrim-rooms.md). A room is a shareable one-time map
// veto + hero ban + report loop with no tournament, no bracket and no organizer;
// the room UI, the pick-ban engine and the captain-identity resolver are reused
// verbatim, so the only new surface is provisioning plus these five calls.
//
// Auth:
//   - Create/list/claim/close require a logged-in user (only a workspace MEMBER
//     may open a room; the worker enforces that and the per-user active-room cap
//     from the global Settings table) -> AuthRequired.
//   - The room read is visibility-gated: a room lives under a hidden "Scrims"
//     tournament, so it 404s for anyone who is neither a workspace insider nor
//     preview-allowlisted -> AuthOptional, so an eligible viewer's identity
//     reaches the handler while anonymous callers are still answered (with 404).
//
// The share token is an opaque URL-safe string, NOT a numeric id: it travels as
// `Path` (copied verbatim into the RPC body), never as `IDParam` — the latter
// lands in data["id"], which the reads dispatcher parses as an entity id.
//
// The bare collection and the {token} routes cannot shadow each other: the
// stdlib ServeMux matches by specificity, and "/api/v1/scrims" is an exact
// (trailing-slash-less) pattern, so it never swallows a longer path. The
// literal-suffixed /claim and /close are more specific still.
var ScrimRoutes = []edge.RouteSpec{
	{Method: "POST", Pattern: "/api/v1/scrims", Queue: "rpc.tournament.scrim_create", Body: true, Auth: edge.AuthRequired, Success: 201},
	// `scope` is optional: absent (or "mine") lists the caller's own rooms, while
	// "workspace" lists every room of the workspace for staff holding
	// match.result — the worker owns both the vocabulary and that gate.
	{Method: "GET", Pattern: "/api/v1/scrims", Queue: "rpc.tournament.scrim_list_mine", Query: []string{"workspace_id", "scope"}, Auth: edge.AuthRequired},
	{Method: "GET", Pattern: "/api/v1/scrims/{token}", Queue: "rpc.tournament.scrim_get", Path: []string{"token"}, Auth: edge.AuthOptional},
	{Method: "POST", Pattern: "/api/v1/scrims/{token}/claim", Queue: "rpc.tournament.scrim_claim", Path: []string{"token"}, Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/scrims/{token}/close", Queue: "rpc.tournament.scrim_close", Path: []string{"token"}, Auth: edge.AuthRequired},
}
