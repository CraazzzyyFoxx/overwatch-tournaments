package workspace

import (
	"context"
	"errors"
	"fmt"
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
)

// Every ACL cache is keyed by ids a client picks (and caches negative answers),
// so every one must be bounded — at most aclCacheMaxEntries live keys.
func TestNewBoundsEveryCache(t *testing.T) {
	s := reflect.ValueOf(New(nil)).Elem()
	checked := 0
	for i := range s.NumField() {
		f := s.Field(i)
		if f.Kind() != reflect.Pointer || f.IsNil() || f.Elem().Kind() != reflect.Struct {
			continue
		}
		bound := f.Elem().FieldByName("maxEntries")
		if !bound.IsValid() {
			continue
		}
		checked++
		if n := bound.Int(); n <= 0 || n > aclCacheMaxEntries {
			t.Errorf("%s: maxEntries = %d, want 1..%d", s.Type().Field(i).Name, n, aclCacheMaxEntries)
		}
	}
	if checked == 0 {
		t.Fatal("found no caches to check")
	}
}

// The captain lookup runs against the encounter layer (spec §13.3): an encounter's participants are the live rows
// of `encounter.team` — there is no home/away pair and no `encounter_participant` table any more.
func TestIsEncounterCaptainSQLReadsParticipations(t *testing.T) {
	for _, want := range []string{
		"encounter.team",
		"encounter_id = $1",
		"active",
		"team_id IS NOT NULL",
	} {
		if !strings.Contains(isEncounterCaptainSQL, want) {
			t.Fatalf("isEncounterCaptainSQL must contain %q, got: %s", want, isEncounterCaptainSQL)
		}
	}
	// The dropped columns and the dropped table: a captain is now any live
	// participation's source team, whatever the slot count.
	for _, gone := range []string{"home_team_id", "away_team_id", "encounter_participant"} {
		if strings.Contains(isEncounterCaptainSQL, gone) {
			t.Fatalf("isEncounterCaptainSQL still references %q: %s", gone, isEncounterCaptainSQL)
		}
	}
}

// The membership query decides who may spectate a hidden tournament. An observed_only anchor (a stats observation's
// row for a player nobody admitted) must not count, a real member and a removed one keep their answers. Runs against
// the real schema in a rolled-back transaction; skipped when no test database is reachable.
func TestIsMemberSQLIgnoresObservationOnlyAnchors(t *testing.T) {
	host, port := os.Getenv("POSTGRES_HOST"), os.Getenv("POSTGRES_PORT")
	if host == "" || port == "" {
		t.Skip("POSTGRES_HOST/POSTGRES_PORT not set")
	}
	dsn := fmt.Sprintf("postgres://%s:%s@%s:%s/%s", os.Getenv("POSTGRES_USER"), os.Getenv("POSTGRES_PASSWORD"), host, port, os.Getenv("POSTGRES_DB"))
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Skipf("test database unreachable: %v", err)
	}
	defer conn.Close(ctx)
	tx, err := conn.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(ctx)

	var workspaceID int64
	if err := tx.QueryRow(ctx, `INSERT INTO workspace (slug, name, disciplines_enabled) VALUES ('gw-observed-test', 'gw', ARRAY['overwatch']) RETURNING id`).Scan(&workspaceID); err != nil {
		t.Skipf("cannot seed workspace (schema not the expected one): %v", err)
	}
	var authID int64
	if err := tx.QueryRow(ctx, `INSERT INTO auth."user" (email, username, is_active, is_superuser, is_verified) VALUES ('gw-observed@example.com', 'gw_observed', true, false, false) RETURNING id`).Scan(&authID); err != nil {
		t.Skipf("cannot seed auth user: %v", err)
	}
	var playerID int64
	if err := tx.QueryRow(ctx, `INSERT INTO players."user" (name, auth_user_id) VALUES ('gw-observed-player', $1) RETURNING id`, authID).Scan(&playerID); err != nil {
		t.Skipf("cannot seed player: %v", err)
	}
	member := func(observed bool, removed bool) bool {
		if _, err := tx.Exec(ctx, `DELETE FROM workspace_member WHERE workspace_id = $1 AND player_id = $2`, workspaceID, playerID); err != nil {
			t.Fatal(err)
		}
		removedAt := "NULL"
		if removed {
			removedAt = "now()"
		}
		if _, err := tx.Exec(ctx, fmt.Sprintf(`INSERT INTO workspace_member (workspace_id, player_id, observed_only, removed_at) VALUES ($1, $2, $3, %s)`, removedAt), workspaceID, playerID, observed); err != nil {
			t.Fatal(err)
		}
		var is bool
		if err := tx.QueryRow(ctx, isMemberSQL, authID, workspaceID).Scan(&is); err != nil {
			t.Fatal(err)
		}
		return is
	}
	if !member(false, false) {
		t.Fatal("an admitted member must count")
	}
	if member(true, false) {
		t.Fatal("an observation-only anchor must not count as membership")
	}
	if member(false, true) {
		t.Fatal("a removed member must not count")
	}
}

// Who is inside a mix match's room: a seated player (through the roster snapshot's member and its linked account)
// or a host/co-host of its mix. Also the owner lookups the rooms' rules branch on: a mix match, a tournament
// encounter, a missing encounter, and a draft session of either owner with its mix's hosts. Runs against the real
// schema in a rolled-back transaction; skipped without a test DB.
func TestIsMixRoomMemberSQL(t *testing.T) {
	host, port := os.Getenv("POSTGRES_HOST"), os.Getenv("POSTGRES_PORT")
	if host == "" || port == "" {
		t.Skip("POSTGRES_HOST/POSTGRES_PORT not set")
	}
	dsn := fmt.Sprintf("postgres://%s:%s@%s:%s/%s", os.Getenv("POSTGRES_USER"), os.Getenv("POSTGRES_PASSWORD"), host, port, os.Getenv("POSTGRES_DB"))
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Skipf("test database unreachable: %v", err)
	}
	defer conn.Close(ctx)
	tx, err := conn.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(ctx)

	seed := func(sql string, args ...any) int64 {
		var id int64
		if err := tx.QueryRow(ctx, sql, args...).Scan(&id); err != nil {
			t.Skipf("cannot seed (schema not the expected one): %v", err)
		}
		return id
	}
	account := func(name string) int64 {
		return seed(`INSERT INTO auth."user" (email, username, is_active, is_superuser, is_verified) VALUES ($1 || '@example.com', $1, true, false, false) RETURNING id`, name)
	}
	ws := seed(`INSERT INTO workspace (slug, name, disciplines_enabled) VALUES ('gw-mixroom-test', 'gw', ARRAY['overwatch']) RETURNING id`)
	player, hostID, coHost, outsider := account("gw_mix_player"), account("gw_mix_host"), account("gw_mix_cohost"), account("gw_mix_outsider")
	playerRow := seed(`INSERT INTO players."user" (name, auth_user_id) VALUES ('gw-mix-player', $1) RETURNING id`, player)
	member := seed(`INSERT INTO workspace_member (workspace_id, player_id) VALUES ($1, $2) RETURNING id`, ws, playerRow)
	rule := seed(`INSERT INTO encounter.scoring_rule (workspace_id, preset, game_formula, end_formula) VALUES ($1, 'wins', 'win', 'games >= best_of') RETURNING id`, ws)
	game := seed(`INSERT INTO mix.custom_game (workspace_id, host_user_id, name, scoring_rule_id) VALUES ($1, $2, 'gw', $3) RETURNING id`, ws, hostID, rule)
	if _, err := tx.Exec(ctx, `INSERT INTO mix.co_host (custom_game_id, user_id) VALUES ($1, $2)`, game, coHost); err != nil {
		t.Fatal(err)
	}
	encounter := seed(`INSERT INTO encounter.encounter (workspace_id, discipline, custom_game_id, scoring_rule_id, name, slot_count, best_of, status) VALUES ($1, 'overwatch', $2, $3, 'A vs B', 2, 1, 'OPEN') RETURNING id`, ws, game, rule)
	team := seed(`INSERT INTO encounter.team (encounter_id, slot, name) VALUES ($1, 1, 'A') RETURNING id`, encounter)
	seed(`INSERT INTO encounter.team_member (encounter_id, encounter_team_id, active, workspace_member_id, display_name_snapshot) VALUES ($1, $2, true, $3, 'P') RETURNING id`, encounter, team, member)

	inside := func(user int64) bool {
		var is bool
		if err := tx.QueryRow(ctx, isMixRoomMemberSQL, encounter, user).Scan(&is); err != nil {
			t.Fatal(err)
		}
		return is
	}
	for name, user := range map[string]int64{"seated player": player, "host": hostID, "co-host": coHost} {
		if !inside(user) {
			t.Fatalf("%s must be inside the room", name)
		}
	}
	if inside(outsider) {
		t.Fatal("an outsider must not be inside the room")
	}

	owner := func(id int64) (int64, bool, error) {
		var tournamentID int64
		var isMix bool
		err := tx.QueryRow(ctx, encounterOwnerSQL, id).Scan(&tournamentID, &isMix)
		return tournamentID, isMix, err
	}
	if tournamentID, isMix, err := owner(encounter); err != nil || !isMix || tournamentID != 0 {
		t.Fatalf("encounterOwnerSQL(mix) = (%d, %v, %v), want (0, true, nil)", tournamentID, isMix, err)
	}
	cup := seed(`INSERT INTO tournament.tournament (workspace_id, name, slug, status) VALUES ($1, 'gw', 'gw-mixroom-test', 'live') RETURNING id`, ws)
	cupEncounter := seed(`INSERT INTO encounter.encounter (workspace_id, discipline, tournament_id, scoring_rule_id, name, slot_count, best_of, status) VALUES ($1, 'overwatch', $2, $3, 'C vs D', 2, 1, 'OPEN') RETURNING id`, ws, cup, rule)
	if tournamentID, isMix, err := owner(cupEncounter); err != nil || isMix || tournamentID != cup {
		t.Fatalf("encounterOwnerSQL(tournament) = (%d, %v, %v), want (%d, false, nil)", tournamentID, isMix, err, cup)
	}
	// EncounterOwner maps no row to found=false, so a missing encounter must yield none.
	if _, _, err := owner(-1); !errors.Is(err, pgx.ErrNoRows) {
		t.Fatalf("encounterOwnerSQL(missing) err = %v, want pgx.ErrNoRows", err)
	}

	if _, err := tx.Exec(ctx, `INSERT INTO mix.lobby (custom_game_id, lobby_index) VALUES ($1, 0) ON CONFLICT DO NOTHING`, game); err != nil {
		t.Skipf("cannot seed (schema not the expected one): %v", err)
	}
	mixDraft := seed(`INSERT INTO draft.session (custom_game_id, lobby_index, workspace_id, discipline) SELECT id, 0, workspace_id, discipline FROM mix.custom_game WHERE id = $1 RETURNING id`, game)
	cupDraft := seed(`INSERT INTO draft.session (tournament_id, workspace_id, discipline) SELECT id, workspace_id, discipline FROM tournament.tournament WHERE id = $1 RETURNING id`, cup)
	draftOwner := func(id int64) (int64, bool, error) {
		var tournamentID int64
		var isMix bool
		err := tx.QueryRow(ctx, draftSessionOwnerSQL, id).Scan(&tournamentID, &isMix)
		return tournamentID, isMix, err
	}
	if tournamentID, isMix, err := draftOwner(mixDraft); err != nil || !isMix || tournamentID != 0 {
		t.Fatalf("draftSessionOwnerSQL(mix) = (%d, %v, %v), want (0, true, nil)", tournamentID, isMix, err)
	}
	if tournamentID, isMix, err := draftOwner(cupDraft); err != nil || isMix || tournamentID != cup {
		t.Fatalf("draftSessionOwnerSQL(tournament) = (%d, %v, %v), want (%d, false, nil)", tournamentID, isMix, err, cup)
	}
	runsDraft := func(session, user int64) bool {
		var is bool
		if err := tx.QueryRow(ctx, isDraftSessionMixHostSQL, session, user).Scan(&is); err != nil {
			t.Fatal(err)
		}
		return is
	}
	if !runsDraft(mixDraft, hostID) || !runsDraft(mixDraft, coHost) {
		t.Fatal("the mix's host and co-host run its draft")
	}
	if runsDraft(mixDraft, player) || runsDraft(mixDraft, outsider) || runsDraft(cupDraft, hostID) {
		t.Fatal("only a mix's hosts run its own draft")
	}
}
