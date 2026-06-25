// Package workspace resolves the data the topic ACL needs from the shared DB:
// a tournament's owning workspace, and whether a user is a member of a
// workspace. Both are cached briefly in memory because they change rarely and
// are hit on every gated subscribe.
package workspace

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	tournamentWorkspaceSQL = `SELECT workspace_id FROM tournament.tournament WHERE id = $1`
	isMemberSQL            = `SELECT EXISTS(SELECT 1 FROM workspace_member WHERE auth_user_id = $1 AND workspace_id = $2)`

	tournamentCacheTTL = 5 * time.Minute
	// Matches the auth-service RBAC cache TTL, so membership changes propagate
	// within roughly the same window.
	membershipCacheTTL = 60 * time.Second
)

// Store answers ACL lookups against the database, with small TTL caches.
type Store struct {
	pool       *pgxpool.Pool
	tournament *ttlCache[int64, int64]
	members    *ttlCache[memberKey, bool]
}

type memberKey struct {
	userID, workspaceID int64
}

// New returns a workspace Store backed by the given pool.
func New(pool *pgxpool.Pool) *Store {
	return &Store{
		pool:       pool,
		tournament: newTTLCache[int64, int64](tournamentCacheTTL),
		members:    newTTLCache[memberKey, bool](membershipCacheTTL),
	}
}

// TournamentWorkspaceID returns the workspace that owns a tournament. found is
// false when the tournament does not exist.
func (s *Store) TournamentWorkspaceID(ctx context.Context, tournamentID int64) (int64, bool, error) {
	if v, ok := s.tournament.get(tournamentID); ok {
		return v, true, nil
	}

	var workspaceID int64
	err := s.pool.QueryRow(ctx, tournamentWorkspaceSQL, tournamentID).Scan(&workspaceID)
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, false, nil
	}
	if err != nil {
		return 0, false, fmt.Errorf("tournament workspace lookup: %w", err)
	}

	s.tournament.set(tournamentID, workspaceID)
	return workspaceID, true, nil
}

// IsWorkspaceMember reports whether the user belongs to the workspace.
func (s *Store) IsWorkspaceMember(ctx context.Context, userID, workspaceID int64) (bool, error) {
	key := memberKey{userID: userID, workspaceID: workspaceID}
	if v, ok := s.members.get(key); ok {
		return v, nil
	}

	var member bool
	if err := s.pool.QueryRow(ctx, isMemberSQL, userID, workspaceID).Scan(&member); err != nil {
		return false, fmt.Errorf("membership lookup: %w", err)
	}

	s.members.set(key, member)
	return member, nil
}
