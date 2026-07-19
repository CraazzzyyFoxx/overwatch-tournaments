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

// MembershipChecker reports workspace membership.
type MembershipChecker interface {
	IsWorkspaceMember(ctx context.Context, userID, workspaceID int64) (bool, error)
}

// VisibilityChecker answers hidden-tournament visibility for WS topic gating
// (issue #115). Mirrors the shared REST guard: a hidden tournament's live
// spectating topics are visible only to insiders + the preview allowlist.
type VisibilityChecker interface {
	TournamentIsHidden(ctx context.Context, tournamentID int64) (hidden bool, found bool, err error)
	IsPreviewAllowed(ctx context.Context, userID, tournamentID int64) (bool, error)
	EncounterTournamentID(ctx context.Context, encounterID int64) (tournamentID int64, found bool, err error)
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
	r.register("tournament:*:bracket", r.allowSpectateTournament) // public unless hidden
	r.register("tournament:*:draft", r.allowSpectateTournament)   // public unless hidden
	r.register("encounter:*:map-veto", r.allowSpectateEncounter)  // public unless hidden
	r.register("tournament:*:balancer", r.allowBalancer)          // admin tool: workspace member
	r.register("workspace:*:*", r.allowWorkspaceMember)           // workspace member
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
