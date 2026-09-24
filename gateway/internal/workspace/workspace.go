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
	// workspace_member is anchored on player_id (a players."user" row), not on the
	// RBAC auth identity: the identity/workspace refactor (iwrefac07) dropped
	// workspace_member.auth_user_id. The gateway only ever holds an auth user id
	// (from the JWT), so it must bridge through players."user".auth_user_id —
	// mirroring WorkspaceMemberRepository.get_member in
	// backend/shared/repository/workspace.py. "user" is a reserved word, hence
	// the quoting.
	isMemberSQL = `SELECT EXISTS(
		SELECT 1
		FROM workspace_member wm
		JOIN players."user" u ON u.id = wm.player_id
		WHERE u.auth_user_id = $1 AND wm.workspace_id = $2
	)`
	// Organizer staff of a workspace, as opposed to anyone on its roster. Mirror
	// of AuthUser.has_admin_panel_access(workspace_id) on the REST side: a role
	// scoped to this workspace (or a global one) carrying at least one non-read
	// grant. The `custom_game` exclusion mirrors _NON_ADMIN_PANEL_RESOURCES —
	// hosting a mix is a member-level capability, not organizing. Membership
	// itself is NOT this: workspace_member rows (and the baseline `member` role
	// they autofill) are created for every tournament registrant.
	isOrganizerSQL = `SELECT EXISTS(
		SELECT 1
		FROM auth.user_roles ur
		JOIN auth.roles r ON r.id = ur.role_id
		JOIN auth.role_permissions rp ON rp.role_id = r.id
		JOIN auth.permissions p ON p.id = rp.permission_id
		WHERE ur.user_id = $1
		  AND (r.workspace_id = $2 OR r.workspace_id IS NULL)
		  AND p.resource <> 'custom_game'
		  AND p.action <> 'read'
	)`
	// Only a workspace whose custom domain has completed DNS TXT verification
	// matches; a domain that is merely set (custom_domain_verified_at IS NULL,
	// still pending/unverified) never does. See
	// docs/superpowers/specs/2026-07-06-workspace-multidomain-design.md and the
	// mirrored predicate in backend/shared/repository/workspace.py
	// (get_by_verified_custom_domain).
	customDomainVerifiedSQL = `SELECT EXISTS(SELECT 1 FROM workspace WHERE custom_domain = $1 AND custom_domain_verified_at IS NOT NULL)`

	// Hidden-tournament visibility (issue #115): the WS topic ACL must not leak
	// a hidden tournament's live bracket/draft/map-veto to outsiders. A tournament
	// also reads hidden when its owning workspace is (Python's
	// shared/services/tournament_visibility.py:can_view_workspace_tournaments) --
	// the OR below cascades that without a second cached lookup. allowSpectate's
	// existing member/superuser/preview-allowlist check already covers the wider
	// "any member" audience the workspace dimension needs, so no other change
	// is required here.
	tournamentHiddenSQL    = `SELECT t.is_hidden OR w.is_hidden FROM tournament.tournament t JOIN workspace w ON w.id = t.workspace_id WHERE t.id = $1`
	previewAllowedSQL      = `SELECT EXISTS(SELECT 1 FROM tournament.tournament_preview_access WHERE tournament_id = $1 AND auth_user_id = $2)`
	encounterTournamentSQL = `SELECT tournament_id FROM tournament.encounter WHERE id = $1`
	// Same players."user" bridge as isMemberSQL above, for the other direction:
	// tournament.team.captain_id references players."user".id, while the gateway
	// only ever holds an auth user id (from the JWT). An encounter's teams are
	// its two sides for a duel and its participant rows for an ffa lobby; one of
	// the two lists is always empty, and both are indexed lookups by encounter
	// id, so the union costs one extra index probe
	// (ix_tournament_team_captain_id still covers the captain side).
	isEncounterCaptainSQL = `SELECT EXISTS(
		SELECT 1
		FROM tournament.team t
		JOIN players."user" u ON u.id = t.captain_id
		WHERE u.auth_user_id = $2
		  AND t.id IN (
			SELECT e.home_team_id FROM tournament.encounter e WHERE e.id = $1
			UNION ALL SELECT e.away_team_id FROM tournament.encounter e WHERE e.id = $1
			UNION ALL SELECT p.team_id FROM tournament.encounter_participant p WHERE p.encounter_id = $1
		  )
	)`
	// The draft room's participants. balancer.draft_team carries the captain's
	// AUTH id directly (captain_auth_user_id), so this needs no players."user"
	// bridge, unlike isEncounterCaptainSQL above; a session has one row per team
	// and ix_balancer_draft_team_captain_auth_user_id covers the predicate.
	isDraftSessionCaptainSQL = `SELECT EXISTS(
		SELECT 1
		FROM balancer.draft_team
		WHERE session_id = $1 AND captain_auth_user_id = $2
	)`
	draftSessionTournamentSQL = `SELECT tournament_id FROM balancer.draft_session WHERE id = $1`
	// Per-room chat settings (default schema, table chat_room_settings). The row
	// is lazily materialized, so "no row" is not "no such room": it means the
	// room still runs on its kind's default — see roomSpectatorReadDefault.
	roomSpectatorReadSQL = `SELECT spectators_can_read FROM chat_room_settings WHERE room_kind = $1 AND room_ref_id = $2`

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
	// The shortest TTL here, deliberately: spectators_can_read gates a single
	// observable organizer action ("hide the chat"), and ws.TopicRevoker re-runs
	// the topic ACL for every live subscriber the moment that toggle is
	// published — a re-check answered from a stale entry would leave the
	// spectator it is meant to evict subscribed. The revoker invalidates this
	// gateway's entry first (InvalidateRoomSpectatorRead); 15s only bounds how
	// long ANOTHER gateway process can keep admitting new subscribes on the old
	// answer.
	roomSettingsCacheTTL = 15 * time.Second
)

// Store answers ACL lookups against the database, with small TTL caches.
type Store struct {
	pool          *pgxpool.Pool
	tournament    *ttlCache[int64, int64]
	members       *ttlCache[memberKey, bool]
	organizers    *ttlCache[memberKey, bool]
	customDomains *ttlCache[string, bool]
	hidden        *ttlCache[int64, bool]
	preview       *ttlCache[previewKey, bool]
	encTournament *ttlCache[int64, int64]
	captains      *ttlCache[captainKey, bool]
	draftCaptains *ttlCache[draftCaptainKey, bool]
	draftTourn    *ttlCache[int64, int64]
	roomSettings  *ttlCache[roomKey, bool]
}

type memberKey struct {
	userID, workspaceID int64
}

type previewKey struct {
	userID, tournamentID int64
}

type captainKey struct {
	userID, encounterID int64
}

type draftCaptainKey struct {
	userID, sessionID int64
}

type roomKey struct {
	kind  string
	refID int64
}

// New returns a workspace Store backed by the given pool.
func New(pool *pgxpool.Pool) *Store {
	return &Store{
		pool:          pool,
		tournament:    newTTLCache[int64, int64](tournamentCacheTTL),
		members:       newTTLCache[memberKey, bool](membershipCacheTTL),
		organizers:    newTTLCache[memberKey, bool](membershipCacheTTL),
		customDomains: newBoundedTTLCache[string, bool](customDomainCacheTTL, customDomainCacheMaxEntries),
		hidden:        newTTLCache[int64, bool](hiddenCacheTTL),
		preview:       newTTLCache[previewKey, bool](previewCacheTTL),
		encTournament: newTTLCache[int64, int64](tournamentCacheTTL),
		captains:      newTTLCache[captainKey, bool](membershipCacheTTL),
		draftCaptains: newTTLCache[draftCaptainKey, bool](membershipCacheTTL),
		draftTourn:    newTTLCache[int64, int64](tournamentCacheTTL),
		roomSettings:  newTTLCache[roomKey, bool](roomSettingsCacheTTL),
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

// IsWorkspaceOrganizer reports whether the user is staff of the workspace --
// the chat-moderation audience -- rather than merely on its roster. Cached and
// fail-closed exactly like IsWorkspaceMember: a query error is returned, never
// memoized.
func (s *Store) IsWorkspaceOrganizer(ctx context.Context, userID, workspaceID int64) (bool, error) {
	key := memberKey{userID: userID, workspaceID: workspaceID}
	if v, ok := s.organizers.get(key); ok {
		return v, nil
	}

	var organizer bool
	if err := s.pool.QueryRow(ctx, isOrganizerSQL, userID, workspaceID).Scan(&organizer); err != nil {
		return false, fmt.Errorf("organizer lookup: %w", err)
	}

	s.organizers.set(key, organizer)
	return organizer, nil
}

// IsEncounterCaptain reports whether the auth user captains a team of the
// encounter — either side of a duel, or any team seated in an ffa lobby.
// Both outcomes are cached like IsWorkspaceMember; on a query error
// nothing is cached and the error is returned, so a transient DB failure is
// never memoized as "allowed" (callers must treat an error as denied).
func (s *Store) IsEncounterCaptain(ctx context.Context, authUserID, encounterID int64) (bool, error) {
	key := captainKey{userID: authUserID, encounterID: encounterID}
	if v, ok := s.captains.get(key); ok {
		return v, nil
	}

	var captain bool
	if err := s.pool.QueryRow(ctx, isEncounterCaptainSQL, encounterID, authUserID).Scan(&captain); err != nil {
		return false, fmt.Errorf("encounter captain lookup: %w", err)
	}

	s.captains.set(key, captain)
	return captain, nil
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

// IsDraftSessionCaptain reports whether the auth user captains one of the
// session's draft teams. Cached exactly like IsEncounterCaptain: both outcomes
// cached, nothing cached on a query error.
func (s *Store) IsDraftSessionCaptain(ctx context.Context, authUserID, sessionID int64) (bool, error) {
	key := draftCaptainKey{userID: authUserID, sessionID: sessionID}
	if v, ok := s.draftCaptains.get(key); ok {
		return v, nil
	}

	var captain bool
	if err := s.pool.QueryRow(ctx, isDraftSessionCaptainSQL, sessionID, authUserID).Scan(&captain); err != nil {
		return false, fmt.Errorf("draft session captain lookup: %w", err)
	}

	s.draftCaptains.set(key, captain)
	return captain, nil
}

// DraftSessionTournamentID returns the tournament a draft session belongs to.
// found is false when the session does not exist (callers must deny).
func (s *Store) DraftSessionTournamentID(ctx context.Context, sessionID int64) (int64, bool, error) {
	if v, ok := s.draftTourn.get(sessionID); ok {
		return v, true, nil
	}

	var tournamentID int64
	err := s.pool.QueryRow(ctx, draftSessionTournamentSQL, sessionID).Scan(&tournamentID)
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, false, nil
	}
	if err != nil {
		return 0, false, fmt.Errorf("draft session tournament lookup: %w", err)
	}

	s.draftTourn.set(sessionID, tournamentID)
	return tournamentID, true, nil
}

// RoomSpectatorRead reports whether spectators may read a chat room. A missing
// chat_room_settings row is not an error: the row is lazily materialized, so
// its absence means the room still runs on its kind's default.
func (s *Store) RoomSpectatorRead(ctx context.Context, roomKind string, refID int64) (bool, error) {
	key := roomKey{kind: roomKind, refID: refID}
	if v, ok := s.roomSettings.get(key); ok {
		return v, nil
	}

	var canRead bool
	err := s.pool.QueryRow(ctx, roomSpectatorReadSQL, roomKind, refID).Scan(&canRead)
	if errors.Is(err, pgx.ErrNoRows) {
		canRead = roomSpectatorReadDefault(roomKind)
	} else if err != nil {
		return false, fmt.Errorf("room spectator read lookup: %w", err)
	}

	s.roomSettings.set(key, canRead)
	return canRead, nil
}

// InvalidateRoomSpectatorRead drops the cached setting for one room, so the
// next RoomSpectatorRead re-reads it. ws.TopicRevoker calls this before
// re-authorizing a room's live subscribers: the whole point of that pass is to
// act on the value the organizer just wrote.
func (s *Store) InvalidateRoomSpectatorRead(roomKind string, refID int64) {
	s.roomSettings.del(roomKey{kind: roomKind, refID: refID})
}

// roomSpectatorReadDefault mirrors _SPECTATORS_CAN_READ_DEFAULT in
// backend/shared/services/chat/room.py — a draft is a show and viewers follow
// it; a pre-game room is where captains trade custom-lobby codes and they do
// not. The two MUST NOT drift: the gateway gates the live topic, Python gates
// the REST history, and a disagreement means one of them lies. An unknown kind
// reads closed, so a typo fails shut.
func roomSpectatorReadDefault(roomKind string) bool {
	return roomKind == "draft"
}
