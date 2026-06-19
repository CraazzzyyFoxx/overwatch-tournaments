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
	rules    []rule
}

// New builds the registry with the four rules ported from realtime-service.
func New(resolver WorkspaceResolver, members MembershipChecker) *Registry {
	r := &Registry{resolver: resolver, members: members}
	r.register("tournament:*:bracket", allowPublic)      // public spectating
	r.register("tournament:*:draft", allowPublic)        // public spectating
	r.register("encounter:*:map-veto", allowPublic)      // public spectating (map veto)
	r.register("tournament:*:balancer", r.allowBalancer) // admin tool: workspace member
	r.register("workspace:*:*", r.allowWorkspaceMember)  // workspace member
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

func allowPublic(context.Context, *auth.User, []string) (bool, error) {
	return true, nil
}

// allowBalancer gates the tournament-scoped admin tool on membership of the
// tournament's owning workspace.
func (r *Registry) allowBalancer(ctx context.Context, user *auth.User, groups []string) (bool, error) {
	if user == nil || len(groups) == 0 {
		return false, nil
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
	workspaceID, err := strconv.ParseInt(groups[0], 10, 64)
	if err != nil {
		return false, nil
	}
	return r.members.IsWorkspaceMember(ctx, user.ID, workspaceID)
}
