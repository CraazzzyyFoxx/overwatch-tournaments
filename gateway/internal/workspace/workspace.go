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
	// backend/shared/repository/workspace.py. An observed_only anchor (made by a stats
	// observation, never admitted) is not a membership. "user" is a reserved word, hence
	// the quoting.
	isMemberSQL = `SELECT EXISTS(
		SELECT 1
		FROM workspace_member wm
		JOIN players."user" u ON u.id = wm.player_id
		WHERE u.auth_user_id = $1 AND wm.workspace_id = $2 AND wm.removed_at IS NULL
		  AND wm.observed_only IS FALSE
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
	tournamentHiddenSQL = `SELECT t.is_hidden OR w.is_hidden FROM tournament.tournament t JOIN workspace w ON w.id = t.workspace_id WHERE t.id = $1`
	previewAllowedSQL   = `SELECT EXISTS(SELECT 1 FROM tournament.tournament_preview_access WHERE tournament_id = $1 AND auth_user_id = $2)`
	// The encounter's owner: its tournament, or (tournament_id NULL) a pickup mix. found is false only for a missing
	// encounter, so a mix room is "known, public" rather than "unknown, denied".
	encounterOwnerSQL = `SELECT COALESCE(tournament_id, 0), custom_game_id IS NOT NULL FROM encounter.encounter WHERE id = $1`
	// Inside a mix match's room (spec §4.4): a seated player -- the roster snapshot's live row, through its workspace
	// member's player and that player's linked account -- or the mix's host or a co-host.
	isMixRoomMemberSQL = `SELECT EXISTS(
		SELECT 1
		FROM encounter.encounter e
		JOIN mix.custom_game g ON g.id = e.custom_game_id
		WHERE e.id = $1
		  AND (g.host_user_id = $2
		    OR EXISTS (SELECT 1 FROM mix.co_host ch WHERE ch.custom_game_id = g.id AND ch.user_id = $2)
		    OR EXISTS (
		      SELECT 1
		      FROM encounter.team_member tm
		      JOIN workspace_member wm ON wm.id = tm.workspace_member_id
		      JOIN players."user" u ON u.id = wm.player_id
		      WHERE tm.encounter_id = e.id AND tm.active AND u.auth_user_id = $2))
	)`
	// Same players."user" bridge as isMemberSQL above, for the other direction:
	// tournament.team.captain_id references players."user".id, while the gateway
	// only ever holds an auth user id (from the JWT). An encounter's participants
	// are the LIVE rows of encounter.team (spec §13.3) -- one per seat, however
	// many seats the card has, so a duel and an ffa lobby answer through the same
	// lookup. A retired participation (active = false) is history and no longer
	// captains anything; a seat whose source team was deleted (team_id IS NULL)
	// has no captain to find. Both ends are indexed:
	// uq_team_active_slot covers the encounter_id probe and
	// ix_tournament_team_captain_id the captain side.
	isEncounterCaptainSQL = `SELECT EXISTS(
		SELECT 1
		FROM encounter.team et
		JOIN tournament.team t ON t.id = et.team_id
		JOIN players."user" u ON u.id = t.captain_id
		WHERE et.encounter_id = $1
		  AND et.active
		  AND et.team_id IS NOT NULL
		  AND u.auth_user_id = $2
	)`
	// The draft room's participants. draft.team carries the captain's
	// AUTH id directly (captain_auth_user_id), so this needs no players."user"
	// bridge, unlike isEncounterCaptainSQL above; a session has one row per team
	// and ix_draft_team_captain_auth_user_id covers the predicate.
	isDraftSessionCaptainSQL = `SELECT EXISTS(
		SELECT 1
		FROM draft.team
		WHERE session_id = $1 AND captain_auth_user_id = $2
	)`
	// The draft session's owner: its tournament, or (tournament_id NULL) one lobby of a pickup mix (spec §9.1).
	// found is false only for a missing session, so a mix draft is "known, public" rather than "unknown, denied".
	draftSessionOwnerSQL = `SELECT COALESCE(tournament_id, 0), custom_game_id IS NOT NULL FROM draft.session WHERE id = $1`
	// Who runs a mix lobby's draft (U4): its mix's host or a co-host, as isMixRoomMemberSQL's host branch. A
	// tournament's session has no mix, so nobody matches.
	isDraftSessionMixHostSQL = `SELECT EXISTS(
		SELECT 1
		FROM draft.session s
		JOIN mix.custom_game g ON g.id = s.custom_game_id
		WHERE s.id = $1
		  AND (g.host_user_id = $2
		    OR EXISTS (SELECT 1 FROM mix.co_host ch WHERE ch.custom_game_id = g.id AND ch.user_id = $2))
	)`
	// Per-room chat settings (default schema, table chat_room_settings). The row
	// is lazily materialized, so "no row" is not "no such room": it means the
	// room still runs on its kind's default — see roomSpectatorReadDefault.
	roomSpectatorReadSQL = `SELECT spectators_can_read FROM chat_room_settings WHERE room_kind = $1 AND room_ref_id = $2`
	// Effective workspace-scope requests_per_minute, resolved exactly the way
	// PolicyStore does in backend/shared/quota/policy.py: the workspace's own
	// override, else its plan's row, else NULL (unlimited). The plan is the
	// explicitly assigned one when there is one, otherwise the plan named after
	// the workspace's verification_status tier. One row per call, all lookups
	// by primary key or unique index.
	workspaceRPMSQL = `SELECT COALESCE(
		(SELECT wl.requests_per_minute FROM quota.workspace_limit wl
		  WHERE wl.workspace_id = w.id AND wl.scope = 'workspace'),
		(SELECT pl.requests_per_minute FROM quota.plan_limit pl
		  WHERE pl.scope = 'workspace'
		    AND pl.plan_id = COALESCE(
		      (SELECT p.id FROM quota.plan p WHERE p.id = w.quota_plan_id),
		      (SELECT p.id FROM quota.plan p WHERE p.slug = w.verification_status)))
	) FROM workspace w WHERE w.id = $1`

	tournamentCacheTTL = 5 * time.Minute
	// A backstop only: identity-svc announces every membership/role change on
	// realtime:user:{id}:rbac and EvictUser drops that user's answers at once.
	membershipCacheTTL = 60 * time.Second
	// Hidden flag + preview allowlist change when an admin toggles them; keep the
	// window short so the WS gate reflects changes within roughly a minute.
	hiddenCacheTTL  = 60 * time.Second
	previewCacheTTL = 60 * time.Second
	// Short TTL so a domain that is unclaimed, re-pointed, or has its
	// verification revoked stops being accepted for new WebSocket handshakes
	// within roughly this window, mirroring membershipCacheTTL above.
	customDomainCacheTTL = 60 * time.Second
	// customDomainCacheMaxEntries bounds the customDomains cache, tighter than
	// aclCacheMaxEntries: this one is keyed by an Origin host that is fully
	// attacker-controlled and reachable pre-handshake from a single
	// unauthenticated HTTP GET (see ws.Handler.acceptOptionsFor). 4096
	// comfortably covers any realistic number of concurrently-verified
	// white-label custom domains plus headroom, while still capping worst-case
	// memory from a distinct-host flood; see ttlCache's FIFO eviction.
	customDomainCacheMaxEntries = 4096
	// The shortest TTL here, deliberately: spectators_can_read gates a single
	// observable organizer action ("hide the chat"), and ws.TopicRevoker re-runs
	// the topic ACL for every live subscriber the moment that toggle is
	// published — a re-check answered from a stale entry would leave the
	// spectator it is meant to evict subscribed. The revoker invalidates this
	// gateway's entry first (InvalidateRoomAccess); 15s only bounds how
	// long ANOTHER gateway process can keep admitting new subscribes on the old
	// answer.
	roomSettingsCacheTTL = 15 * time.Second
	// A quota change (plan move, superuser override) should take effect within
	// about a minute, same window as membershipCacheTTL. Bounded like
	// customDomains and for the same reason: the key is a workspace id taken
	// from an anonymous request's query string.
	workspaceRPMCacheTTL        = 60 * time.Second
	workspaceRPMCacheMaxEntries = 4096
	// aclCacheMaxEntries bounds every other cache. None of their key spaces is
	// operator-controlled: a client picks the workspace, tournament, encounter
	// or session id of every subscribe, and negative answers are cached too, so
	// cycling made-up ids would otherwise grow these maps for the life of the
	// process. 50 000 live answers per cache sits well above one gateway's
	// working set within a TTL; past it, FIFO eviction only costs a re-query.
	aclCacheMaxEntries = 50_000
)

// Store answers ACL lookups against the database, with small bounded TTL
// caches. Concurrent misses for one key share a single query (ttlCache.fill).
type Store struct {
	pool          *pgxpool.Pool
	tournament    *ttlCache[int64, int64]
	members       *ttlCache[memberKey, bool]
	organizers    *ttlCache[memberKey, bool]
	customDomains *ttlCache[string, bool]
	hidden        *ttlCache[int64, bool]
	preview       *ttlCache[previewKey, bool]
	encOwner      *ttlCache[int64, encounterOwner]
	mixMembers    *ttlCache[captainKey, bool]
	captains      *ttlCache[captainKey, bool]
	draftCaptains *ttlCache[draftCaptainKey, bool]
	draftHosts    *ttlCache[draftCaptainKey, bool]
	draftOwner    *ttlCache[int64, encounterOwner]
	roomSettings  *ttlCache[roomKey, bool]
	wsRPM         *ttlCache[int64, wsRPM]
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

// wsRPM is one cached answer of WorkspaceRequestsPerMinute. The zero value is
// the "no such workspace" answer, which is cached like any other.
type wsRPM struct {
	limit   int
	limited bool
	exists  bool
}

type encounterOwner struct {
	tournamentID int64
	mix          bool
}

// New returns a workspace Store backed by the given pool.
func New(pool *pgxpool.Pool) *Store {
	return &Store{
		pool:          pool,
		tournament:    newBoundedTTLCache[int64, int64](tournamentCacheTTL, aclCacheMaxEntries),
		members:       newBoundedTTLCache[memberKey, bool](membershipCacheTTL, aclCacheMaxEntries),
		organizers:    newBoundedTTLCache[memberKey, bool](membershipCacheTTL, aclCacheMaxEntries),
		customDomains: newBoundedTTLCache[string, bool](customDomainCacheTTL, customDomainCacheMaxEntries),
		hidden:        newBoundedTTLCache[int64, bool](hiddenCacheTTL, aclCacheMaxEntries),
		preview:       newBoundedTTLCache[previewKey, bool](previewCacheTTL, aclCacheMaxEntries),
		encOwner:      newBoundedTTLCache[int64, encounterOwner](tournamentCacheTTL, aclCacheMaxEntries),
		mixMembers:    newBoundedTTLCache[captainKey, bool](membershipCacheTTL, aclCacheMaxEntries),
		captains:      newBoundedTTLCache[captainKey, bool](membershipCacheTTL, aclCacheMaxEntries),
		draftCaptains: newBoundedTTLCache[draftCaptainKey, bool](membershipCacheTTL, aclCacheMaxEntries),
		draftHosts:    newBoundedTTLCache[draftCaptainKey, bool](membershipCacheTTL, aclCacheMaxEntries),
		draftOwner:    newBoundedTTLCache[int64, encounterOwner](tournamentCacheTTL, aclCacheMaxEntries),
		roomSettings:  newBoundedTTLCache[roomKey, bool](roomSettingsCacheTTL, aclCacheMaxEntries),
		wsRPM:         newBoundedTTLCache[int64, wsRPM](workspaceRPMCacheTTL, workspaceRPMCacheMaxEntries),
	}
}

// TournamentWorkspaceID returns the workspace that owns a tournament. found is
// false when the tournament does not exist.
func (s *Store) TournamentWorkspaceID(ctx context.Context, tournamentID int64) (int64, bool, error) {
	if v, ok := s.tournament.get(tournamentID); ok {
		return v, true, nil
	}
	workspaceID, found, err := s.tournament.fill(ctx, tournamentID, func(ctx context.Context) (int64, bool, error) {
		var workspaceID int64
		err := s.pool.QueryRow(ctx, tournamentWorkspaceSQL, tournamentID).Scan(&workspaceID)
		if errors.Is(err, pgx.ErrNoRows) {
			return 0, false, nil
		}
		return workspaceID, true, err
	})
	if err != nil {
		return 0, false, fmt.Errorf("tournament workspace lookup: %w", err)
	}
	return workspaceID, found, nil
}

// IsWorkspaceMember reports whether the user belongs to the workspace.
func (s *Store) IsWorkspaceMember(ctx context.Context, userID, workspaceID int64) (bool, error) {
	key := memberKey{userID: userID, workspaceID: workspaceID}
	if v, ok := s.members.get(key); ok {
		return v, nil
	}
	member, _, err := s.members.fill(ctx, key, func(ctx context.Context) (bool, bool, error) {
		var member bool
		err := s.pool.QueryRow(ctx, isMemberSQL, userID, workspaceID).Scan(&member)
		return member, true, err
	})
	if err != nil {
		return false, fmt.Errorf("membership lookup: %w", err)
	}
	return member, nil
}

// EvictUser drops every cached membership and organizer answer of the auth
// user, and keeps a lookup already in flight from storing its pre-change
// answer. identity-svc publishes realtime:user:{id}:rbac after every change
// to that user's memberships or roles; ws.TopicRevoker calls this before
// re-checking the user's live subscriptions, so neither that re-check nor the
// next subscribe is answered from the old entry.
func (s *Store) EvictUser(userID int64) {
	match := func(k memberKey) bool { return k.userID == userID }
	s.members.evictWhere(match)
	s.organizers.evictWhere(match)
}

// WorkspaceRequestsPerMinute returns the workspace-scope requests_per_minute
// ceiling in force for a workspace: limited=false means "no ceiling anywhere"
// (unlimited), exists=false means there is no such workspace at all.
//
// It MIRRORS PolicyStore.resolve for the `workspace` scope in
// backend/shared/quota/policy.py and must change with it: nearest level that
// names a value wins — the workspace's own quota.workspace_limit override
// first, then its plan's quota.plan_limit row, where the plan is
// workspace.quota_plan_id when set and otherwise the plan whose slug equals
// the workspace's verification_status. NULL the whole way down is unlimited.
//
// Both outcomes are cached, including "no such workspace": the id reaching
// here can come from an ANONYMOUS request's ?workspace_id= query string, so a
// flood of made-up ids must cost at most one query each per TTL (concurrent
// misses share one, see ttlCache.fill) and must not grow the cache past its
// bound (hence workspaceRPMCacheMaxEntries). A query error caches nothing —
// the next request retries.
func (s *Store) WorkspaceRequestsPerMinute(ctx context.Context, workspaceID int64) (int, bool, bool, error) {
	if v, ok := s.wsRPM.get(workspaceID); ok {
		return v.limit, v.limited, v.exists, nil
	}
	v, _, err := s.wsRPM.fill(ctx, workspaceID, func(ctx context.Context) (wsRPM, bool, error) {
		var limit *int32
		err := s.pool.QueryRow(ctx, workspaceRPMSQL, workspaceID).Scan(&limit)
		if errors.Is(err, pgx.ErrNoRows) {
			return wsRPM{}, true, nil
		}
		v := wsRPM{exists: true}
		if limit != nil {
			v.limit, v.limited = int(*limit), true
		}
		return v, true, err
	})
	if err != nil {
		return 0, false, false, fmt.Errorf("workspace rpm lookup: %w", err)
	}
	return v.limit, v.limited, v.exists, nil
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
	organizer, _, err := s.organizers.fill(ctx, key, func(ctx context.Context) (bool, bool, error) {
		var organizer bool
		err := s.pool.QueryRow(ctx, isOrganizerSQL, userID, workspaceID).Scan(&organizer)
		return organizer, true, err
	})
	if err != nil {
		return false, fmt.Errorf("organizer lookup: %w", err)
	}
	return organizer, nil
}

// IsEncounterCaptain reports whether the auth user captains one of the
// encounter's live participations — any seat of the card, duel or lobby alike.
// Both outcomes are cached like IsWorkspaceMember; on a query error
// nothing is cached and the error is returned, so a transient DB failure is
// never memoized as "allowed" (callers must treat an error as denied).
func (s *Store) IsEncounterCaptain(ctx context.Context, authUserID, encounterID int64) (bool, error) {
	key := captainKey{userID: authUserID, encounterID: encounterID}
	if v, ok := s.captains.get(key); ok {
		return v, nil
	}
	captain, _, err := s.captains.fill(ctx, key, func(ctx context.Context) (bool, bool, error) {
		var captain bool
		err := s.pool.QueryRow(ctx, isEncounterCaptainSQL, encounterID, authUserID).Scan(&captain)
		return captain, true, err
	})
	if err != nil {
		return false, fmt.Errorf("encounter captain lookup: %w", err)
	}
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
// one, and concurrent misses for a host share one query (ttlCache.fill), so a
// flood of lookups for the SAME host — verified or not — costs at most one
// query per customDomainCacheTTL while its entry stays cached. The cache
// itself is size-bounded (see customDomainCacheMaxEntries) so a flood of
// DISTINCT hosts still can't grow it past a fixed ceiling.
//
// Fail-closed: on a query error, the error is returned, verified is always
// false, and — critically — the result is NOT cached (fill never stores an
// error), so a transient DB failure can never be memoized as either
// "allowed" or "denied"; the next lookup for that host gets a fresh query.
// Callers (ws.Handler) must treat an error as "not allowed", never as
// "allowed".
func (s *Store) IsVerifiedCustomDomain(ctx context.Context, host string) (bool, error) {
	if v, ok := s.customDomains.get(host); ok {
		return v, nil
	}
	verified, _, err := s.customDomains.fill(ctx, host, func(ctx context.Context) (bool, bool, error) {
		var verified bool
		err := s.pool.QueryRow(ctx, customDomainVerifiedSQL, host).Scan(&verified)
		return verified, true, err
	})
	if err != nil {
		return false, fmt.Errorf("custom domain lookup: %w", err)
	}
	return verified, nil
}

// TournamentIsHidden reports whether a tournament is hidden. found is false when
// the tournament does not exist (callers must deny — no existence disclosure).
func (s *Store) TournamentIsHidden(ctx context.Context, tournamentID int64) (bool, bool, error) {
	if v, ok := s.hidden.get(tournamentID); ok {
		return v, true, nil
	}
	hidden, found, err := s.hidden.fill(ctx, tournamentID, func(ctx context.Context) (bool, bool, error) {
		var hidden bool
		err := s.pool.QueryRow(ctx, tournamentHiddenSQL, tournamentID).Scan(&hidden)
		if errors.Is(err, pgx.ErrNoRows) {
			return false, false, nil
		}
		return hidden, true, err
	})
	if err != nil {
		return false, false, fmt.Errorf("tournament hidden lookup: %w", err)
	}
	return hidden, found, nil
}

// IsPreviewAllowed reports whether the user is on a tournament's preview
// allowlist. Both outcomes are cached (short TTL).
func (s *Store) IsPreviewAllowed(ctx context.Context, userID, tournamentID int64) (bool, error) {
	key := previewKey{userID: userID, tournamentID: tournamentID}
	if v, ok := s.preview.get(key); ok {
		return v, nil
	}
	allowed, _, err := s.preview.fill(ctx, key, func(ctx context.Context) (bool, bool, error) {
		var allowed bool
		err := s.pool.QueryRow(ctx, previewAllowedSQL, tournamentID, userID).Scan(&allowed)
		return allowed, true, err
	})
	if err != nil {
		return false, fmt.Errorf("preview access lookup: %w", err)
	}
	return allowed, nil
}

// EncounterOwner returns who owns an encounter: its tournament, or mix=true for a pickup mix's match. found is false
// when the encounter does not exist (callers must deny).
func (s *Store) EncounterOwner(ctx context.Context, encounterID int64) (int64, bool, bool, error) {
	if v, ok := s.encOwner.get(encounterID); ok {
		return v.tournamentID, v.mix, true, nil
	}
	owner, found, err := s.encOwner.fill(ctx, encounterID, func(ctx context.Context) (encounterOwner, bool, error) {
		var owner encounterOwner
		err := s.pool.QueryRow(ctx, encounterOwnerSQL, encounterID).Scan(&owner.tournamentID, &owner.mix)
		if errors.Is(err, pgx.ErrNoRows) {
			return encounterOwner{}, false, nil
		}
		return owner, true, err
	})
	if err != nil {
		return 0, false, false, fmt.Errorf("encounter owner lookup: %w", err)
	}
	return owner.tournamentID, owner.mix, found, nil
}

// IsMixRoomMember reports whether the auth user sits in the mix encounter or hosts its mix. Cached like
// IsEncounterCaptain: both outcomes, nothing on a query error.
func (s *Store) IsMixRoomMember(ctx context.Context, authUserID, encounterID int64) (bool, error) {
	key := captainKey{userID: authUserID, encounterID: encounterID}
	if v, ok := s.mixMembers.get(key); ok {
		return v, nil
	}
	inside, _, err := s.mixMembers.fill(ctx, key, func(ctx context.Context) (bool, bool, error) {
		var inside bool
		err := s.pool.QueryRow(ctx, isMixRoomMemberSQL, encounterID, authUserID).Scan(&inside)
		return inside, true, err
	})
	if err != nil {
		return false, fmt.Errorf("mix room member lookup: %w", err)
	}
	return inside, nil
}

// IsDraftSessionCaptain reports whether the auth user captains one of the
// session's draft teams. Cached like IsEncounterCaptain: both outcomes cached,
// nothing cached on a query error, and nothing cached from a lookup that
// started before InvalidateRoomAccess dropped the session's answers.
func (s *Store) IsDraftSessionCaptain(ctx context.Context, authUserID, sessionID int64) (bool, error) {
	key := draftCaptainKey{userID: authUserID, sessionID: sessionID}
	if v, ok := s.draftCaptains.get(key); ok {
		return v, nil
	}
	captain, _, err := s.draftCaptains.fill(ctx, key, func(ctx context.Context) (bool, bool, error) {
		var captain bool
		err := s.pool.QueryRow(ctx, isDraftSessionCaptainSQL, sessionID, authUserID).Scan(&captain)
		return captain, true, err
	})
	if err != nil {
		return false, fmt.Errorf("draft session captain lookup: %w", err)
	}
	return captain, nil
}

// IsDraftSessionMixHost reports whether the auth user hosts or co-hosts the mix whose lobby the draft session forms.
// Cached like IsDraftSessionCaptain: both outcomes, nothing on a query error.
func (s *Store) IsDraftSessionMixHost(ctx context.Context, authUserID, sessionID int64) (bool, error) {
	key := draftCaptainKey{userID: authUserID, sessionID: sessionID}
	if v, ok := s.draftHosts.get(key); ok {
		return v, nil
	}
	host, _, err := s.draftHosts.fill(ctx, key, func(ctx context.Context) (bool, bool, error) {
		var host bool
		err := s.pool.QueryRow(ctx, isDraftSessionMixHostSQL, sessionID, authUserID).Scan(&host)
		return host, true, err
	})
	if err != nil {
		return false, fmt.Errorf("draft session mix host lookup: %w", err)
	}
	return host, nil
}

// DraftSessionOwner returns a draft session's owner: its tournament, or mix=true for a mix lobby's draft. found is
// false when the session does not exist (callers must deny).
func (s *Store) DraftSessionOwner(ctx context.Context, sessionID int64) (int64, bool, bool, error) {
	if v, ok := s.draftOwner.get(sessionID); ok {
		return v.tournamentID, v.mix, true, nil
	}
	owner, found, err := s.draftOwner.fill(ctx, sessionID, func(ctx context.Context) (encounterOwner, bool, error) {
		var owner encounterOwner
		err := s.pool.QueryRow(ctx, draftSessionOwnerSQL, sessionID).Scan(&owner.tournamentID, &owner.mix)
		if errors.Is(err, pgx.ErrNoRows) {
			return encounterOwner{}, false, nil
		}
		return owner, true, err
	})
	if err != nil {
		return 0, false, false, fmt.Errorf("draft session owner lookup: %w", err)
	}
	return owner.tournamentID, owner.mix, found, nil
}

// RoomSpectatorRead reports whether spectators may read a chat room. A missing
// chat_room_settings row is not an error: the row is lazily materialized, so
// its absence means the room still runs on its kind's default. Nothing is
// cached from a lookup that started before InvalidateRoomAccess dropped the
// room's setting.
func (s *Store) RoomSpectatorRead(ctx context.Context, roomKind string, refID int64) (bool, error) {
	key := roomKey{kind: roomKind, refID: refID}
	if v, ok := s.roomSettings.get(key); ok {
		return v, nil
	}
	canRead, _, err := s.roomSettings.fill(ctx, key, func(ctx context.Context) (bool, bool, error) {
		var canRead bool
		err := s.pool.QueryRow(ctx, roomSpectatorReadSQL, roomKind, refID).Scan(&canRead)
		if errors.Is(err, pgx.ErrNoRows) {
			return roomSpectatorReadDefault(roomKind), true, nil
		}
		return canRead, true, err
	})
	if err != nil {
		return false, fmt.Errorf("room spectator read lookup: %w", err)
	}
	return canRead, nil
}

// InvalidateRoomAccess drops the cached answers a room's re-authorization must
// not reuse: its spectator setting and, for a draft room, who captains the
// session (a replaced captain is announced on the same event), and fences the
// lookups of them already in flight — a settings read that started before the
// toggle must not store its pre-toggle answer after it. ws.TopicRevoker calls
// this before re-authorizing a room's live subscribers: the whole point of
// that pass is to act on what was just written.
func (s *Store) InvalidateRoomAccess(roomKind string, refID int64) {
	key := roomKey{kind: roomKind, refID: refID}
	s.roomSettings.evictWhere(func(k roomKey) bool { return k == key })
	if roomKind == "draft" {
		s.draftCaptains.evictWhere(func(k draftCaptainKey) bool { return k.sessionID == refID })
	}
}

// Reset drops every cached answer and fences every lookup in flight. The
// realtime bus calls it (through ws.TopicRevoker, an events.Fanout leg) once
// its Redis subscription is re-established after a loss: the RBAC and chat
// visibility frames published in the gap never arrived, so no cached answer is
// known to be current.
func (s *Store) Reset() {
	s.tournament.reset()
	s.members.reset()
	s.organizers.reset()
	s.customDomains.reset()
	s.hidden.reset()
	s.preview.reset()
	s.encOwner.reset()
	s.mixMembers.reset()
	s.captains.reset()
	s.draftCaptains.reset()
	s.draftHosts.reset()
	s.draftOwner.reset()
	s.roomSettings.reset()
	s.wsRPM.reset()
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
