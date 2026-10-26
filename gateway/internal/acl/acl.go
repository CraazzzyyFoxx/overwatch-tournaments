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

// MembershipChecker reports workspace membership, encounter captaincy,
// draft-session captaincy, mix-draft hosting and mix-room membership — the "is
// this principal a participant" lookups the rules below need.
type MembershipChecker interface {
	IsWorkspaceMember(ctx context.Context, userID, workspaceID int64) (bool, error)
	IsWorkspaceOrganizer(ctx context.Context, userID, workspaceID int64) (bool, error)
	IsEncounterCaptain(ctx context.Context, authUserID, encounterID int64) (bool, error)
	IsDraftSessionCaptain(ctx context.Context, authUserID, sessionID int64) (bool, error)
	IsDraftSessionMixHost(ctx context.Context, authUserID, sessionID int64) (bool, error)
	IsMixRoomMember(ctx context.Context, authUserID, encounterID int64) (bool, error)
}

// VisibilityChecker answers hidden-tournament visibility for WS topic gating
// (issue #115). Mirrors the shared REST guard: a hidden tournament's live
// spectating topics are visible only to insiders + the preview allowlist.
// RoomSpectatorRead adds the chat rooms' own organizer-controlled toggle, which
// narrows that audience further but never widens it past the hidden gate.
type VisibilityChecker interface {
	TournamentIsHidden(ctx context.Context, tournamentID int64) (hidden bool, found bool, err error)
	IsPreviewAllowed(ctx context.Context, userID, tournamentID int64) (bool, error)
	EncounterOwner(ctx context.Context, encounterID int64) (tournamentID int64, mix bool, found bool, err error)
	DraftSessionOwner(ctx context.Context, sessionID int64) (tournamentID int64, mix bool, found bool, err error)
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
	r.register("draft:*:board", r.allowSpectateDraft)                 // a mix's draft is public; a tournament's unless hidden
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
	r.register("user:*:catalog-sync", r.allowOwnNotifications)    // the starter's catalog sync progress, same rule
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

// allowSpectateTournament gates a tournament:<id>:bracket topic: public unless
// the tournament is hidden.
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

// allowSpectateEncounter gates encounter:<id>:{map-veto,pick-ban:hero}: a mix match's room is public (spec §4.4), a
// tournament encounter's follows its tournament's hidden-visibility rule.
func (r *Registry) allowSpectateEncounter(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if len(groups) == 0 {
		return false, nil
	}
	encounterID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	tournamentID, mix, found, err := r.vis.EncounterOwner(ctx, encounterID)
	if err != nil || !found {
		return false, err
	}
	if mix {
		return true, nil
	}
	return r.allowSpectate(ctx, user, tournamentID)
}

// allowSpectateDraft gates draft:<session_id>:board, the draft board of a tournament or of a mix lobby (spec §9.6): a
// mix draft is public (spec §4.4), a tournament draft follows its tournament's hidden-visibility rule.
func (r *Registry) allowSpectateDraft(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if len(groups) == 0 {
		return false, nil
	}
	sessionID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	tournamentID, mix, found, err := r.vis.DraftSessionOwner(ctx, sessionID)
	if err != nil || !found {
		return false, err
	}
	if mix {
		return true, nil
	}
	return r.allowSpectate(ctx, user, tournamentID)
}

// allowEncounterChat gates encounter:<id>:chat. A mix match's chat (spec §4.4) is its seated players' and its
// hosts' only: no spectator branch, because the in-game lobby code is shared there. A tournament pre-game room:
// participants always -- superuser, a captain of either side, the organizing workspace's staff -- and everyone else
// only while the room's spectators_can_read is on (OFF by default here; see allowRoomChat).
func (r *Registry) allowEncounterChat(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if len(groups) == 0 {
		return false, nil
	}
	encounterID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	if isSuperuser(user) {
		return true, nil
	}
	tournamentID, mix, found, err := r.vis.EncounterOwner(ctx, encounterID)
	if err != nil || !found {
		return false, err
	}
	if mix {
		// A mix belongs to no workspace, so a workspace-scoped key holds no
		// seat in its room.
		if user == nil || user.APIKeyWorkspaceID != 0 {
			return false, nil
		}
		return r.members.IsMixRoomMember(ctx, user.ID, encounterID)
	}
	if user, err = r.scopeToTournament(ctx, user, tournamentID); err != nil {
		return false, err
	}
	if user != nil {
		captain, err := r.members.IsEncounterCaptain(ctx, user.ID, encounterID)
		if err != nil {
			return false, err
		}
		if captain {
			return true, nil
		}
	}
	return r.allowRoomChat(ctx, user, "encounter", encounterID, tournamentID)
}

// allowDraftChat gates draft:<session_id>:chat, the draft room. Same shape as
// allowEncounterChat with the draft's own participant lookup: a captain here is
// a captain of one of the SESSION's draft teams (the room is the session, not
// the tournament — a re-seed is a different draft and a different room).
// Spectator read is ON by default for a draft: it is a show, and viewers and
// casters follow it. A mix lobby's draft is run by the mix's host and co-hosts,
// who get in whatever the toggle says (U4); everyone else only while it is on.
func (r *Registry) allowDraftChat(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if len(groups) == 0 {
		return false, nil
	}
	sessionID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	if isSuperuser(user) {
		return true, nil
	}
	tournamentID, mix, found, err := r.vis.DraftSessionOwner(ctx, sessionID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, nil
	}
	// Every participant grant below belongs to the draft's workspace; a key
	// from elsewhere, or in a mix (which belongs to none), only spectates.
	if mix {
		if user != nil && user.APIKeyWorkspaceID != 0 {
			user = nil
		}
	} else if user, err = r.scopeToTournament(ctx, user, tournamentID); err != nil {
		return false, err
	}
	if user != nil {
		captain, err := r.members.IsDraftSessionCaptain(ctx, user.ID, sessionID)
		if err != nil {
			return false, err
		}
		if captain {
			return true, nil
		}
	}
	if mix {
		if user != nil {
			host, err := r.members.IsDraftSessionMixHost(ctx, user.ID, sessionID)
			if err != nil {
				return false, err
			}
			if host {
				return true, nil
			}
		}
		// A mix draft's chat is public while its spectator read is on (spec §4.4); it has no workspace staff or
		// hidden-tournament gate to consult.
		return r.vis.RoomSpectatorRead(ctx, "draft", sessionID)
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
// NOTE: the edge User carries only ID+IsSuperuser (+ an API key's workspace; no
// RBAC), so we use workspace MEMBER — not strictly ADMIN as the REST guard does
// — as the closest available insider signal, consistent with allowBalancer
// above. Outsiders (anon, non-member, non-allowlisted, a key from another
// workspace) are always denied, so this never leaks to the public; it is at
// most marginally more permissive to workspace insiders.
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
	if isSuperuser(user) {
		return true, nil
	}
	workspaceID, wsFound, err := r.resolver.TournamentWorkspaceID(ctx, tournamentID)
	if err != nil {
		return false, err
	}
	if !keyInScope(user, workspaceID, wsFound) {
		return false, nil
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
	if isSuperuser(user) {
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
	if !found || !keyInScope(user, workspaceID, true) {
		return false, nil
	}
	return r.members.IsWorkspaceMember(ctx, user.ID, workspaceID)
}

func (r *Registry) allowWorkspaceMember(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if user == nil || len(groups) == 0 {
		return false, nil
	}
	if isSuperuser(user) {
		return true, nil
	}
	workspaceID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil || !keyInScope(user, workspaceID, true) {
		return false, nil
	}
	return r.members.IsWorkspaceMember(ctx, user.ID, workspaceID)
}

// isSuperuser is the superuser bypass every workspace-scoped rule shares, and
// never an API key's: a key acts as itself inside one workspace, not as its
// owner — whose superuser bit would otherwise open every workspace's feed.
func isSuperuser(user *auth.User) bool {
	return user != nil && user.IsSuperuser && user.APIKeyWorkspaceID == 0
}

// keyInScope reports whether user may use workspace-scoped grants in
// workspaceID: a session always, a workspace-scoped API key only in its own
// workspace (found=false: the workspace is unknown, so never). The membership
// lookups are keyed by the key OWNER's user id, so without this a key pinned to
// one workspace would inherit every workspace its owner belongs to.
func keyInScope(user *auth.User, workspaceID int64, found bool) bool {
	return user.APIKeyWorkspaceID == 0 || (found && workspaceID == user.APIKeyWorkspaceID)
}

// scopeToTournament returns user unchanged, or nil (anonymous) for an API key
// outside the tournament's workspace, for the chat rules whose participant
// grants (captain, staff) all hang off that workspace. Sessions skip the lookup.
func (r *Registry) scopeToTournament(ctx context.Context, user *auth.User, tournamentID int64) (*auth.User, error) {
	if user == nil || user.APIKeyWorkspaceID == 0 {
		return user, nil
	}
	workspaceID, found, err := r.resolver.TournamentWorkspaceID(ctx, tournamentID)
	if err != nil {
		return nil, err
	}
	if !keyInScope(user, workspaceID, found) {
		return nil, nil
	}
	return user, nil
}

// allowOwnNotifications gates user:<id>:notifications, the personal inbox
// signal. Only that user; deliberately no superuser bypass, unlike every rule
// above — nobody needs to read someone else's inbox, and a rule with no
// exception cannot be widened by accident. It needs no external lookup: the
// topic's own id segment is the whole authorization question. An API key is
// never its owner here: these topics are the person's, outside any workspace a
// key can be scoped to.
func (r *Registry) allowOwnNotifications(_ context.Context, user *auth.User, groups []string) (bool, error) {
	if user == nil || user.APIKeyWorkspaceID != 0 || len(groups) == 0 {
		return false, nil
	}
	userID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	return userID == user.ID, nil
}
