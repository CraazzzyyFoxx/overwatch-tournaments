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
	// Only a workspace whose custom domain has completed DNS TXT verification
	// matches; a domain that is merely set (custom_domain_verified_at IS NULL,
	// still pending/unverified) never does. See
	// docs/superpowers/specs/2026-07-06-workspace-multidomain-design.md and the
	// mirrored predicate in backend/shared/repository/workspace.py
	// (get_by_verified_custom_domain).
	customDomainVerifiedSQL = `SELECT EXISTS(SELECT 1 FROM workspace WHERE custom_domain = $1 AND custom_domain_verified_at IS NOT NULL)`

	// Hidden-tournament visibility (issue #115): the WS topic ACL must not leak
	// a hidden tournament's live bracket/draft/map-veto to outsiders.
	tournamentHiddenSQL    = `SELECT is_hidden FROM tournament.tournament WHERE id = $1`
	previewAllowedSQL      = `SELECT EXISTS(SELECT 1 FROM tournament.tournament_preview_access WHERE tournament_id = $1 AND auth_user_id = $2)`
	encounterTournamentSQL = `SELECT tournament_id FROM tournament.encounter WHERE id = $1`

	tournamentCacheTTL = 5 * time.Minute
	// Matches the auth-service RBAC cache TTL, so membership changes propagate
	// within roughly the same window.
	membershipCacheTTL = 60 * time.Second
	// Hidden flag + preview allowlist change when an admin toggles them; keep the
	// window short so the WS gate reflects changes within roughly a minute.
	hiddenCacheTTL  = 60 * time.Second
	previewCacheTTL = 60 * time.Second
	// Short TTL so a domain that is unclaimed, re-pointed, or has its
	// verification revoked stops being accepted for new WebSocket handshakes
	// within roughly this window, mirroring membershipCacheTTL above.
	customDomainCacheTTL = 60 * time.Second
	// customDomainCacheMaxEntries bounds the customDomains cache. Unlike the
	// tournament/membership caches, this one is keyed by an Origin host that
	// is fully attacker-controlled and reachable pre-handshake from a single
	// unauthenticated HTTP GET (see ws.Handler.acceptOptionsFor), so it must
	// never be allowed to grow without bound. 4096 comfortably covers any
	// realistic number of concurrently-verified white-label custom domains
	// plus headroom, while still capping worst-case memory from a
	// distinct-host flood; see ttlCache's FIFO eviction.
	customDomainCacheMaxEntries = 4096
)

// Store answers ACL lookups against the database, with small TTL caches.
type Store struct {
	pool          *pgxpool.Pool
	tournament    *ttlCache[int64, int64]
	members       *ttlCache[memberKey, bool]
	customDomains *ttlCache[string, bool]
	hidden        *ttlCache[int64, bool]
	preview       *ttlCache[previewKey, bool]
	encTournament *ttlCache[int64, int64]
}

type memberKey struct {
	userID, workspaceID int64
}

type previewKey struct {
	userID, tournamentID int64
}

// New returns a workspace Store backed by the given pool.
func New(pool *pgxpool.Pool) *Store {
	return &Store{
		pool:          pool,
		tournament:    newTTLCache[int64, int64](tournamentCacheTTL),
		members:       newTTLCache[memberKey, bool](membershipCacheTTL),
		customDomains: newBoundedTTLCache[string, bool](customDomainCacheTTL, customDomainCacheMaxEntries),
		hidden:        newTTLCache[int64, bool](hiddenCacheTTL),
		preview:       newTTLCache[previewKey, bool](previewCacheTTL),
		encTournament: newTTLCache[int64, int64](tournamentCacheTTL),
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

// IsVerifiedCustomDomain reports whether host is a workspace's verified
// white-label custom domain (Phase 2). host must already be normalized
// (lowercase, no port) by the caller — this method does no normalization of
// its own, matching how the other lookups here take pre-resolved keys. The
// caller (ws.Handler.acceptOptionsFor) is additionally responsible for only
// invoking this for a genuine WS-upgrade request, bounding host's length,
// and rate-limiting the call per client IP — none of that is this method's
// job; it must stay a plain cached lookup.
//
// Both outcomes are cached, not just the positive one: a host that is NOT a
// verified custom domain (verified=false) is cached exactly like a verified
// one, via the unconditional s.customDomains.set below, so a flood of
// lookups for the SAME host — verified or not — costs at most one query per
// customDomainCacheTTL. The cache itself is size-bounded (see
// customDomainCacheMaxEntries) so a flood of DISTINCT hosts still can't grow
// it past a fixed ceiling.
//
// Fail-closed: on a query error, the error is returned, verified is always
// false, and — critically — the result is NOT cached (the set call below is
// only reached after a successful Scan), so a transient DB failure can never
// be memoized as either "allowed" or "denied"; the next lookup for that host
// gets a fresh query. Callers (ws.Handler) must treat an error as "not
// allowed", never as "allowed".
func (s *Store) IsVerifiedCustomDomain(ctx context.Context, host string) (bool, error) {
	if v, ok := s.customDomains.get(host); ok {
		return v, nil
	}

	var verified bool
	if err := s.pool.QueryRow(ctx, customDomainVerifiedSQL, host).Scan(&verified); err != nil {
		return false, fmt.Errorf("custom domain lookup: %w", err)
	}

	s.customDomains.set(host, verified)
	return verified, nil
}

// TournamentIsHidden reports whether a tournament is hidden. found is false when
// the tournament does not exist (callers must deny — no existence disclosure).
func (s *Store) TournamentIsHidden(ctx context.Context, tournamentID int64) (bool, bool, error) {
	if v, ok := s.hidden.get(tournamentID); ok {
		return v, true, nil
	}

	var hidden bool
	err := s.pool.QueryRow(ctx, tournamentHiddenSQL, tournamentID).Scan(&hidden)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, false, nil
	}
	if err != nil {
		return false, false, fmt.Errorf("tournament hidden lookup: %w", err)
	}

	s.hidden.set(tournamentID, hidden)
	return hidden, true, nil
}

// IsPreviewAllowed reports whether the user is on a tournament's preview
// allowlist. Both outcomes are cached (short TTL).
func (s *Store) IsPreviewAllowed(ctx context.Context, userID, tournamentID int64) (bool, error) {
	key := previewKey{userID: userID, tournamentID: tournamentID}
	if v, ok := s.preview.get(key); ok {
		return v, nil
	}

	var allowed bool
	if err := s.pool.QueryRow(ctx, previewAllowedSQL, tournamentID, userID).Scan(&allowed); err != nil {
		return false, fmt.Errorf("preview access lookup: %w", err)
	}

	s.preview.set(key, allowed)
	return allowed, nil
}

// EncounterTournamentID returns the tournament that owns an encounter. found is
// false when the encounter does not exist.
func (s *Store) EncounterTournamentID(ctx context.Context, encounterID int64) (int64, bool, error) {
	if v, ok := s.encTournament.get(encounterID); ok {
		return v, true, nil
	}

	var tournamentID int64
	err := s.pool.QueryRow(ctx, encounterTournamentSQL, encounterID).Scan(&tournamentID)
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, false, nil
	}
	if err != nil {
		return 0, false, fmt.Errorf("encounter tournament lookup: %w", err)
	}

	s.encTournament.set(encounterID, tournamentID)
	return tournamentID, true, nil
}
