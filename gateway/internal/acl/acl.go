// Package acl ports realtime-service's topic ACL: which principals may
// subscribe to which topics. Rules are evaluated in registration order; the
// first matching pattern decides.
package acl

import (
	"context"
	"strconv"
	"strings"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
)

// WorkspaceResolver maps a tournament to its owning workspace.
type WorkspaceResolver interface {
	TournamentWorkspaceID(ctx context.Context, tournamentID int64) (workspaceID int64, found bool, err error)
}

// MembershipChecker reports workspace membership, encounter captaincy and
// draft-session captaincy — the "is this principal a participant" lookups the
// rules below need.
type MembershipChecker interface {
	IsWorkspaceMember(ctx context.Context, userID, workspaceID int64) (bool, error)
	IsWorkspaceOrganizer(ctx context.Context, userID, workspaceID int64) (bool, error)
	IsEncounterCaptain(ctx context.Context, authUserID, encounterID int64) (bool, error)
	IsDraftSessionCaptain(ctx context.Context, authUserID, sessionID int64) (bool, error)
}

// VisibilityChecker answers hidden-tournament visibility for WS topic gating
// (issue #115). Mirrors the shared REST guard: a hidden tournament's live
// spectating topics are visible only to insiders + the preview allowlist.
// RoomSpectatorRead adds the chat rooms' own organizer-controlled toggle, which
// narrows that audience further but never widens it past the hidden gate.
type VisibilityChecker interface {
	TournamentIsHidden(ctx context.Context, tournamentID int64) (hidden bool, found bool, err error)
	IsPreviewAllowed(ctx context.Context, userID, tournamentID int64) (bool, error)
	EncounterTournamentID(ctx context.Context, encounterID int64) (tournamentID int64, found bool, err error)
	DraftSessionTournamentID(ctx context.Context, sessionID int64) (tournamentID int64, found bool, err error)
	RoomSpectatorRead(ctx context.Context, roomKind string, refID int64) (bool, error)
}

// Pattern is a segment matcher for realtime topics. "*" matches exactly one
// segment; topic shapes stay simple (tournament:<id>:bracket, workspace:<id>:*).
type Pattern struct {
	segments []string
}

// NewPattern compiles a topic pattern.
func NewPattern(pattern string) Pattern {
	return Pattern{segments: strings.Split(pattern, ":")}
}

// Match returns the captured "*" segments and whether the topic matches.
func (p Pattern) Match(topic string) ([]string, bool) {
	parts := strings.Split(topic, ":")
	if len(parts) != len(p.segments) {
		return nil, false
	}
	groups := make([]string, 0, len(p.segments))
	for i, expected := range p.segments {
		if expected == "*" {
			groups = append(groups, parts[i])
			continue
		}
		if expected != parts[i] {
			return nil, false
		}
	}
	return groups, true
}

type checkFunc func(ctx context.Context, user *auth.User, groups []string) (bool, error)

type rule struct {
	pattern Pattern
	check   checkFunc
}

// Registry evaluates topic access rules.
type Registry struct {
	resolver WorkspaceResolver
	members  MembershipChecker
	vis      VisibilityChecker
	rules    []rule
}

// New builds the registry with the rules ported from realtime-service. The
// spectating topics are public UNLESS the tournament is hidden (issue #115).
func New(resolver WorkspaceResolver, members MembershipChecker, vis VisibilityChecker) *Registry {
	r := &Registry{resolver: resolver, members: members, vis: vis}
	// Invalidation topics carry no data — only the names of resources that
	// went stale — but they are gated exactly like the domain topics of the
	// same scope: which tournaments/workspaces exist, and when they change, is
	// itself information. There is deliberately no global invalidation topic
	// for that reason (design: 2026-09-09-unified-event-delivery.md D2), and
	// no encounter one (an encounter write stales tournament.encounters).
	r.register("tournament:*:invalidation", r.allowSpectateTournament)
	r.register("user:*:invalidation", r.allowOwnNotifications)
	// workspace:*:invalidation is already covered by the workspace:*:* rule
	// below; a separate registration would be dead code the first-match loop
	// never reaches.
	r.register("tournament:*:bracket", r.allowSpectateTournament)     // public unless hidden
	r.register("tournament:*:draft", r.allowSpectateTournament)       // public unless hidden
	r.register("encounter:*:map-veto", r.allowSpectateEncounter)      // public unless hidden
	r.register("encounter:*:pick-ban:hero", r.allowSpectateEncounter) // public unless hidden
	// The two chat rooms. Participants always; everyone who may already watch
	// the room only while the organizer leaves spectator read ON (default: off
	// for a pre-game room, on for a draft).
	r.register("encounter:*:chat", r.allowEncounterChat)          // participant, or spectator when open
	r.register("draft:*:chat", r.allowDraftChat)                  // participant, or spectator when open
	r.register("tournament:*:balancer", r.allowBalancer)          // admin tool: workspace member
	r.register("tournament:*:streams", r.allowSpectateTournament) // public unless hidden
	r.register("workspace:*:*", r.allowWorkspaceMember)           // workspace member
	r.register("user:*:notifications", r.allowOwnNotifications)   // the user themself, no bypass
	return r
}

func (r *Registry) register(pattern string, check checkFunc) {
	r.rules = append(r.rules, rule{pattern: NewPattern(pattern), check: check})
}

// Allow reports whether the (possibly anonymous) user may subscribe to topic.
// Unknown topics are denied.
func (r *Registry) Allow(ctx context.Context, user *auth.User, topic string) (bool, error) {
	for _, ru := range r.rules {
		if groups, ok := ru.pattern.Match(topic); ok {
			return ru.check(ctx, user, groups)
		}
	}
	return false, nil
}

// allowSpectateTournament gates a tournament:<id>:{bracket,draft} topic: public
// unless the tournament is hidden.
func (r *Registry) allowSpectateTournament(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if len(groups) == 0 {
		return false, nil
	}
	tournamentID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	return r.allowSpectate(ctx, user, tournamentID)
}

// allowSpectateEncounter gates encounter:<id>:map-veto by resolving the owning
// tournament first, then applying the same hidden-visibility rule.
func (r *Registry) allowSpectateEncounter(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if len(groups) == 0 {
		return false, nil
	}
	encounterID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	tournamentID, found, err := r.vis.EncounterTournamentID(ctx, encounterID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, nil
	}
	return r.allowSpectate(ctx, user, tournamentID)
}

// allowEncounterChat gates encounter:<id>:chat, the pregame room. Participants
// always: superuser, a captain of either side, or a member of the workspace
// running the tournament (the organizers who have to moderate it).
//
// Everyone else is a spectator, and a spectator is admitted only while the
// room's spectators_can_read is on. It is OFF by default here, because this is
// where the two captains exchange the custom-lobby code and a publicly
// readable lobby code is an open invitation for griefers to join the match; an
// organizer running a broadcast can switch it on. Anonymous counts as a
// spectator like anyone else — see allowRoomChat for why that is safe.
func (r *Registry) allowEncounterChat(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if len(groups) == 0 {
		return false, nil
	}
	encounterID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	if user != nil {
		if user.IsSuperuser {
			return true, nil
		}
		captain, err := r.members.IsEncounterCaptain(ctx, user.ID, encounterID)
		if err != nil {
			return false, err
		}
		if captain {
			return true, nil
		}
	}
	tournamentID, found, err := r.vis.EncounterTournamentID(ctx, encounterID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, nil
	}
	return r.allowRoomChat(ctx, user, "encounter", encounterID, tournamentID)
}

// allowDraftChat gates draft:<session_id>:chat, the draft room. Same shape as
// allowEncounterChat with the draft's own participant lookup: a captain here is
// a captain of one of the SESSION's draft teams (the room is the session, not
// the tournament — a re-seed is a different draft and a different room).
// Spectator read is ON by default for a draft: it is a show, and viewers and
// casters follow it.
func (r *Registry) allowDraftChat(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if len(groups) == 0 {
		return false, nil
	}
	sessionID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	if user != nil {
		if user.IsSuperuser {
			return true, nil
		}
		captain, err := r.members.IsDraftSessionCaptain(ctx, user.ID, sessionID)
		if err != nil {
			return false, err
		}
		if captain {
			return true, nil
		}
	}
	tournamentID, found, err := r.vis.DraftSessionTournamentID(ctx, sessionID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, nil
	}
	return r.allowRoomChat(ctx, user, "draft", sessionID, tournamentID)
}

// allowRoomChat is the tail both chat rules share once the caller is known not
// to be a participant: the organizing workspace's STAFF get in (they moderate
// the room), then the spectator branch.
//
// Staff, not "any workspace member": a workspace_member row — and the baseline
// `member` role it autofills — is created for every tournament registrant, so
// membership would admit every player of the workspace to a room the organizer
// closed to spectators, live, while REST 403s them. IsWorkspaceOrganizer
// mirrors the resolver's has_admin_panel_access(workspace_id) gate.
//
// The spectator branch is two gates in series and the ORDER is the rule: the
// per-room toggle first, then the unchanged hidden-tournament gate. The toggle
// only widens the audience to people who could already see the room; it never
// makes a hidden tournament visible, so an outsider is denied even with the
// chat open. allowSpectate also denies anonymous on a hidden tournament, which
// is why admitting anonymous spectators here is safe.
func (r *Registry) allowRoomChat(ctx context.Context, user *auth.User, roomKind string, refID, tournamentID int64) (bool, error) {
	if user != nil {
		workspaceID, found, err := r.resolver.TournamentWorkspaceID(ctx, tournamentID)
		if err != nil {
			return false, err
		}
		if found {
			organizer, err := r.members.IsWorkspaceOrganizer(ctx, user.ID, workspaceID)
			if err != nil {
				return false, err
			}
			if organizer {
				return true, nil
			}
		}
	}
	open, err := r.vis.RoomSpectatorRead(ctx, roomKind, refID)
	if err != nil {
		return false, err
	}
	if !open {
		return false, nil
	}
	return r.allowSpectate(ctx, user, tournamentID)
}

// allowSpectate is the shared hidden-tournament gate for public spectating
// topics. A visible tournament is public. A hidden one requires a logged-in
// insider: superuser OR workspace member OR preview-allowlisted.
//
// NOTE: the edge User carries only ID+IsSuperuser (no RBAC), so we use workspace
// MEMBER — not strictly ADMIN as the REST guard does — as the closest available
// insider signal, consistent with allowBalancer above. Outsiders (anon,
// non-member, non-allowlisted) are always denied, so this never leaks to the
// public; it is at most marginally more permissive to workspace insiders.
func (r *Registry) allowSpectate(ctx context.Context, user *auth.User, tournamentID int64) (bool, error) {
	hidden, found, err := r.vis.TournamentIsHidden(ctx, tournamentID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, nil // unknown tournament -> deny (no existence disclosure)
	}
	if !hidden {
		return true, nil // public spectating
	}
	if user == nil {
		return false, nil
	}
	if user.IsSuperuser {
		return true, nil
	}
	workspaceID, wsFound, err := r.resolver.TournamentWorkspaceID(ctx, tournamentID)
	if err != nil {
		return false, err
	}
	if wsFound {
		member, err := r.members.IsWorkspaceMember(ctx, user.ID, workspaceID)
		if err != nil {
			return false, err
		}
		if member {
			return true, nil
		}
	}
	return r.vis.IsPreviewAllowed(ctx, user.ID, tournamentID)
}

// allowBalancer gates the tournament-scoped admin tool on membership of the
// tournament's owning workspace. Superusers bypass the membership check,
// mirroring AuthUser.is_workspace_member on the REST side (which the balancer's
// own WorkspaceAccessPolicy uses) — otherwise a superuser admin can create a
// balance job over REST but is denied the realtime job-status subscription.
func (r *Registry) allowBalancer(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if user == nil || len(groups) == 0 {
		return false, nil
	}
	if user.IsSuperuser {
		return true, nil
	}
	tournamentID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	workspaceID, found, err := r.resolver.TournamentWorkspaceID(ctx, tournamentID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, nil
	}
	return r.members.IsWorkspaceMember(ctx, user.ID, workspaceID)
}

func (r *Registry) allowWorkspaceMember(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if user == nil || len(groups) == 0 {
		return false, nil
	}
	if user.IsSuperuser {
		return true, nil
	}
	workspaceID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	return r.members.IsWorkspaceMember(ctx, user.ID, workspaceID)
}

// allowOwnNotifications gates user:<id>:notifications, the personal inbox
// signal. Only that user; deliberately no superuser bypass, unlike every rule
// above — nobody needs to read someone else's inbox, and a rule with no
// exception cannot be widened by accident. It needs no external lookup: the
// topic's own id segment is the whole authorization question.
func (r *Registry) allowOwnNotifications(_ context.Context, user *auth.User, groups []string) (bool, error) {
	if user == nil || len(groups) == 0 {
		return false, nil
	}
	userID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	return userID == user.ID, nil
}
