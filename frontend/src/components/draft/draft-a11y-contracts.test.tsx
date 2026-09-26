import { describe, expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { buildTeamViews, needRoles, type QueueControls } from "@/lib/draft/room-model";
import { draftPoolView, type DraftPoolTab, type DraftViewParams } from "@/lib/draft/workspace-model";
import type { RosterSlotMap } from "@/lib/roster/shape";
import type { DraftBoard, DraftPickOptionsResponse, DraftPlayer, DraftStatus } from "@/types/draft.types";

vi.mock("next-intl", () => ({
  useLocale: () => "en",
  // Shared across bun test files: DraftJournal (loaded by siblings) reads it.
  useTranslations: () => (key: string, values?: Record<string, unknown>) =>
    values ? `${key}:${JSON.stringify(values)}` : key
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString() })
}));

// Dynamic, not static: `mock.module` only applies to modules imported after it
// runs, and both components call `useTranslations` at render time.
const { PlayerPool } = await import("./PlayerPool");
const { DraftClockRing } = await import("./DraftClockRing");

const OW5: RosterSlotMap = { tank: 1, damage: 2, support: 2 };

function makePlayer(id: number, patch: Partial<DraftPlayer> = {}): DraftPlayer {
  return {
    id,
    session_id: 1,
    registration_id: id * 10,
    user_id: null,
    battle_tag: `P${id}#1`,
    status: "available",
    primary_role: "damage",
    sub_role: null,
    is_flex: false,
    is_captain: false,
    effective_rank: 2500,
    secondary_roles: [],
    role_ranks: { damage: 2500 },
    role_sources: {},
    role_top_heroes: {},
    role_sub_roles: {},
    drafted_by_team_id: null,
    notes: null,
    custom_fields: [],
    version: 1,
    ...patch
  };
}

const ana = makePlayer(7, {
  battle_tag: "Ana#1234",
  primary_role: "support",
  effective_rank: 3000,
  secondary_roles: ["damage"],
  role_ranks: { support: 3000, damage: 2800 }
});

function makeBoard(players: DraftPlayer[], slots: RosterSlotMap, status: DraftStatus): DraftBoard {
  const teamSize = Object.values(slots).reduce((sum, count) => sum + (count ?? 0), 0);
  const team = (id: number, name: string, position: number) => ({
    id,
    session_id: 1,
    captain_user_id: null,
    captain_auth_user_id: null,
    name,
    draft_position: position,
    exported_team_id: null
  });
  return {
    session: {
      status,
      roster_shape: {
        slots,
        team_size: teamSize,
        flex_slots: slots.flex ?? 0,
        has_role_slots: Object.keys(slots).some((code) => code !== "flex"),
        draft_rounds: teamSize,
        source: null
      }
    },
    teams: [team(3, "Team Three", 1), team(4, "Team Four", 2)],
    picks: [],
    players,
    current_pick: null,
    server_time: "2026-09-23T10:00:00Z",
    last_event_id: null
  } as unknown as DraftBoard;
}

const QUEUE: QueueControls = { ids: [], toggle: () => {}, move: () => {} };

function renderPool({
  players = [ana],
  slots = OW5,
  status = "live",
  acting = 3,
  queue = null,
  pool = "available",
  options = null,
  safetyRequired = false,
  headingId = "player-pool-heading"
}: {
  players?: DraftPlayer[];
  slots?: RosterSlotMap;
  status?: DraftStatus;
  /** Acting team id; `null` = a spectator. */
  acting?: number | null;
  queue?: QueueControls | null;
  pool?: DraftPoolTab;
  options?: DraftPickOptionsResponse | null;
  safetyRequired?: boolean;
  headingId?: string;
} = {}) {
  const board = makeBoard(players, slots, status);
  const teamViews = buildTeamViews(board);
  const actingTeam = acting == null ? null : teamViews.get(acting) ?? null;
  const viewParams: DraftViewParams = {
    role: "all",
    sort: "rank",
    view: "pool",
    pool,
    teams: "rosters",
    query: ""
  };
  return renderToStaticMarkup(
    <PlayerPool
      board={board}
      pool={draftPoolView(board.players, viewParams, queue?.ids ?? [], actingTeam ? needRoles(actingTeam) : null)}
      viewParams={viewParams}
      onViewParamsChange={() => {}}
      teamViews={teamViews}
      actingTeam={actingTeam}
      selection={null}
      profileId={null}
      onSelect={() => {}}
      onOpenProfile={() => {}}
      onPrefetchCard={() => {}}
      queue={queue}
      fit={null}
      options={options}
      safetyRequired={safetyRequired}
      divisionGrid={{ tiers: [] } as never}
      headingId={headingId}
      bottomInset={0}
    />
  );
}

const pickAs = (player: string, role: string) =>
  `aria-label="pickAs:{&quot;player&quot;:&quot;${player}&quot;,&quot;role&quot;:&quot;roles.${role}&quot;}"`;
// PlayerRoleIcon names itself `common.roles.*`; the pool's own labels are `roles.*`.
const poolRole = (role: string) => new RegExp(`(?<!common\\.)roles\\.${role}`);

describe("draft accessibility contracts", () => {
  test("a captain gets one named button per pickable role, hearts and the shortlist tab", () => {
    const html = renderPool({ queue: QUEUE });

    expect(html).not.toContain('role="button"');
    expect(html).toContain(pickAs("Ana#1234", "support"));
    expect(html).toContain(pickAs("Ana#1234", "damage"));
    // The role's OWN rank, not the player's effective one.
    expect(html).toContain("2800");
    // The name opens the profile; it is not the pick target.
    expect(html).toContain('aria-label="openProfile:{&quot;player&quot;:&quot;Ana#1234&quot;}"');
    expect(html).toContain('aria-label="pool.queueAdd"');
    expect(html).toContain("pool.tab.shortlist");
    expect(html).toContain("pool.col.fit");
  });

  test("an unsafe option stays reachable and announces why", () => {
    const html = renderPool({
      safetyRequired: true,
      options: {
        pick_id: 1,
        pick_version: 2,
        draft_team_id: 3,
        options: [
          {
            player_id: 7,
            role: "support",
            is_safe: false,
            reason_code: "role_shortage",
            unmatched_slots: [],
            blocking_player_ids: []
          }
        ]
      }
    });

    // aria-disabled, not `disabled`: the reason has to stay readable, and a
    // disabled button is skipped by every screen reader's form controls list.
    expect(html).toContain('aria-disabled="true"');
    expect(html).not.toMatch(/<button[^>]*\sdisabled=""[^>]*pickAs/);
    expect(html).toContain('aria-describedby="player-pool-heading-7-support-reason"');
    expect(html).toMatch(/id="player-pool-heading-7-support-reason"[^>]*>optionReason\.role_shortage</);
  });

  test("a spectator gets chips, no buttons, no hearts and the demand column", () => {
    const html = renderPool({ acting: null });

    expect(html).not.toContain("pickAs:");
    expect(html).not.toContain("pool.queueAdd");
    expect(html).not.toContain("pool.tab.shortlist");
    // Still readable: the roles and their ranks are public information.
    expect(html).toContain("2800");
    expect(html).toContain("openProfile:");
    expect(html).toContain("pool.col.demand");
    expect(html).toContain('pool.demand:{&quot;count&quot;:2}');
  });

  test("an admin without a team acts for the clock but has no list", () => {
    const html = renderPool({ acting: 3, queue: null });

    expect(html).toContain(pickAs("Ana#1234", "support"));
    expect(html).not.toContain("pool.queueAdd");
    expect(html).not.toContain("pool.tab.shortlist");
  });

  test("an all-flex shape shows only the roles present in the pool and no market", () => {
    const flex = renderPool({ slots: { flex: 6 } });
    const ow = renderPool();

    expect(flex).not.toMatch(poolRole("tank"));
    expect(flex).toContain(pickAs("Ana#1234", "damage"));
    expect(flex).not.toContain("pool.market.label");
    expect(ow).toMatch(poolRole("tank"));
    expect(ow).toContain("pool.market.label");
  });

  test("a one-slot roster offers only the role its slot seats", () => {
    const html = renderPool({ slots: { damage: 1 } });

    expect(html).toContain(pickAs("Ana#1234", "damage"));
    expect(html).not.toContain(pickAs("Ana#1234", "support"));
  });

  test("a team that cannot seat any of the player's roles says so and dims every role", () => {
    // Mixed shape: both damage slots and both flex slots filled, only tank left open.
    const rostered = [
      makePlayer(1, { status: "picked", drafted_by_team_id: 3 }),
      makePlayer(2, { status: "picked", drafted_by_team_id: 3 }),
      makePlayer(3, { status: "picked", drafted_by_team_id: 3, primary_role: "support", role_ranks: { support: 2000 } }),
      makePlayer(4, { status: "picked", drafted_by_team_id: 3, primary_role: "support", role_ranks: { support: 2000 } })
    ];
    const html = renderPool({ players: [ana, ...rostered], slots: { tank: 1, damage: 2, flex: 2 } });

    expect(html).toContain("pool.note.noSlot:");
    expect(html).toContain(pickAs("Ana#1234", "support"));
    expect(html).toMatch(new RegExp(`${pickAs("Ana#1234", "support")}[^>]*aria-disabled="true"`));
    expect(html).toContain("pool.reason.noSlot:");
  });

  test("the all tab names the team of a taken player instead of offering roles", () => {
    const html = renderPool({
      pool: "all",
      players: [{ ...ana, status: "picked", drafted_by_team_id: 3 }]
    });

    expect(html).toContain('pool.note.taken:{&quot;team&quot;:&quot;Team Three&quot;}');
    expect(html).not.toContain("pickAs:");
  });

  test("each mounted pool owns a unique heading id", () => {
    // The mobile and desktop trees are both mounted, so a hardcoded id would
    // make aria-labelledby resolve to the wrong section.
    const mobile = renderPool({ headingId: "player-pool-mobile-heading" });
    const desktop = renderPool({ headingId: "player-pool-desktop-heading" });

    expect(mobile).toContain('id="player-pool-mobile-heading"');
    expect(desktop).toContain('id="player-pool-desktop-heading"');
    expect(mobile).not.toContain("player-pool-desktop-heading");
  });

  test("the pick clock exposes a named timer plus a polite region", () => {
    const html = renderToStaticMarkup(
      <DraftClockRing pick={null} paused={false} totalSeconds={60} />
    );

    expect(html).toContain('role="timer"');
    expect(html).toContain('aria-label="draft.clock.idle"');
    expect(html).toContain('aria-live="polite"');
  });
});
