package tournament

import (
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

// Visibility-gated public reads must forward identity so an eligible
// admin/preview viewer of a HIDDEN tournament is not treated as anonymous and
// 404'd. AuthNone would drop the identity (see edge/dispatch.go), reintroducing
// the #115 regression.
func TestVisibilityGatedPublicReadsForwardIdentity(t *testing.T) {
	gated := map[string]bool{
		"rpc.tournament.reg_pub_form":         true,
		"rpc.tournament.reg_pub_list":         true,
		"rpc.tournament.get_pick_ban_configs": true,
	}
	seen := map[string]bool{}
	for _, r := range PublicWriteRoutes {
		if gated[r.Queue] {
			seen[r.Queue] = true
			if r.Auth == edge.AuthNone {
				t.Errorf("%s %s (%s) is AuthNone; must be AuthOptional so hidden-tournament gating sees the viewer", r.Method, r.Pattern, r.Queue)
			}
		}
	}
	for q := range gated {
		if !seen[q] {
			t.Errorf("route %s not found in PublicWriteRoutes", q)
		}
	}
}

// `IDParam` copies the path value to `data["id"]`; `Path` copies params verbatim
// under their own names. A worker reading the id via `_require_id` therefore
// REQUIRES `IDParam`. `get_pick_ban_configs` lives in tournament-service's
// `reads.py`, whose whole-module contract is `data["id"]`.
func TestRequireIDWorkersUseIDParam(t *testing.T) {
	requireID := map[string]bool{
		"rpc.tournament.get_pick_ban_configs":   true,
		"rpc.tournament.encounter_chat_history": true,
		"rpc.tournament.encounter_chat_post":    true,
		// The delete/mute routes carry a second path param (message_id /
		// target_user_id) alongside IDParam, so they are deliberately not listed:
		// the assertion below forbids that pairing, and for them it is correct.
		"rpc.tournament.encounter_chat_settings": true,
	}
	seen := map[string]bool{}
	for _, r := range PublicWriteRoutes {
		if !requireID[r.Queue] {
			continue
		}
		seen[r.Queue] = true
		if r.IDParam == "" {
			t.Errorf(
				"%s %s (%s) has no IDParam; its worker reads data[\"id\"] via _require_id, so Path alone 422s every call",
				r.Method, r.Pattern, r.Queue,
			)
		}
		if len(r.Path) > 0 {
			t.Errorf(
				"%s %s (%s) sets both IDParam and Path=%v; the id must arrive exactly once, as data[\"id\"]",
				r.Method, r.Pattern, r.Queue, r.Path,
			)
		}
	}
	for q := range requireID {
		if !seen[q] {
			t.Errorf("route %s not found in PublicWriteRoutes", q)
		}
	}
}

// TestPickBanV2RouteContracts pins the surface ruleset v2 added
// (docs/plans/2026-09-28-pick-ban-constructor.md §8). A missing or mis-shaped
// entry here is a 404 or a 422 in the live pick-ban room, which is exactly
// where nobody can afford one: the captain writes must carry the `kind` path
// segment AND a body, and the admin probes must hand the worker `data["id"]`.
func TestPickBanV2RouteContracts(t *testing.T) {
	type want struct {
		method  string
		idParam string
		path    []string
		body    bool
		auth    edge.AuthMode
	}
	captain := want{method: "POST", idParam: "encounter_id", path: []string{"kind"}, body: true, auth: edge.AuthRequired}
	adminEncounter := want{method: "POST", idParam: "encounter_id", body: true, auth: edge.AuthRequired}
	adminTournament := want{method: "POST", idParam: "tournament_id", body: true, auth: edge.AuthRequired}
	expected := map[string]want{
		"rpc.tournament.captain_pick_ban_submit":       captain,
		"rpc.tournament.captain_pick_ban_dispute":      captain,
		"rpc.tournament.pick_ban_rules_catalog":        {method: "GET", auth: edge.AuthOptional},
		"rpc.tournament.admin_pick_ban_submit":         adminEncounter,
		"rpc.tournament.admin_pick_ban_reopen":         adminEncounter,
		"rpc.tournament.admin_pick_ban_rules_validate": adminTournament,
		"rpc.tournament.admin_pick_ban_rules_preview":  adminTournament,
		// The pre-game room overrides: readiness is a body write on an
		// encounter, the rooms board a bodyless read on a tournament.
		"rpc.tournament.admin_encounter_readiness_set": adminEncounter,
		"rpc.tournament.admin_pregame_rooms":           {method: "GET", idParam: "tournament_id", auth: edge.AuthRequired},
		// The room journal: a bodyless read keyed on the encounter, so it must
		// not drift onto the tournament id the rooms board uses.
		"rpc.tournament.admin_pregame_room_history": {method: "GET", idParam: "encounter_id", auth: edge.AuthRequired},
		// The room's emergency controls, all four body writes on an encounter:
		// a missing one strands the organizer panel's buttons on a 404.
		"rpc.tournament.admin_pick_ban_pause":           adminEncounter,
		"rpc.tournament.admin_pick_ban_extend":          adminEncounter,
		"rpc.tournament.admin_pick_ban_cancel":          adminEncounter,
		"rpc.tournament.admin_encounter_technical_loss": adminEncounter,
	}

	seen := map[string]bool{}
	for _, table := range [][]edge.RouteSpec{PublicWriteRoutes, AdminMiscRoutes} {
		for _, r := range table {
			exp, ok := expected[r.Queue]
			if !ok {
				continue
			}
			seen[r.Queue] = true
			if r.Method != exp.method || r.IDParam != exp.idParam || r.Body != exp.body || r.Auth != exp.auth {
				t.Errorf("%s: unexpected contract %#v", r.Queue, r)
			}
			if len(r.Path) != len(exp.path) {
				t.Errorf("%s: Path=%v, want %v", r.Queue, r.Path, exp.path)
				continue
			}
			for i := range exp.path {
				if r.Path[i] != exp.path[i] {
					t.Errorf("%s: Path=%v, want %v", r.Queue, r.Path, exp.path)
				}
			}
		}
	}
	for q := range expected {
		if !seen[q] {
			t.Errorf("route %s is not registered", q)
		}
	}
}
