import { describe, expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { DraftGating } from "@/lib/draft/logic";
import type { DraftBoard, DraftPick, DraftPlayer, DraftTeam } from "@/types/draft.types";
import type { DraftMutations } from "@/hooks/useDraftData";
import type { Tournament } from "@/types/tournament.types";

mock.module("next-intl", () => ({
  useLocale: () => "en",
  useFormatter: () => ({
    dateTime: () => "",
    number: (value: number) => String(value),
    relativeTime: () => ""
  }),
  useTranslations: () => (key: string, values?: Record<string, unknown>) =>
    values ? `${key}:${JSON.stringify(values)}` : key
}));

// Dynamic, not static: `mock.module` only applies to modules imported after it
// runs, and the whole tree calls `useTranslations` at render time.
const { DraftWorkspace } = await import("./DraftWorkspace");

const team = (id: number, position: number): DraftTeam => ({
  id,
  session_id: 1,
  captain_user_id: null,
  captain_auth_user_id: id * 100,
  name: `Team ${id}`,
  draft_position: position,
  exported_team_id: null
});

const player = (id: number, overrides: Partial<DraftPlayer> = {}): DraftPlayer => ({
  id,
  session_id: 1,
  registration_id: id * 10,
  user_id: null,
  battle_tag: `P${id}#1`,
  primary_role: "support",
  sub_role: null,
  is_flex: false,
  effective_rank: 3000,
  status: "available",
  is_captain: false,
  drafted_by_team_id: null,
  secondary_roles: ["damage"],
  role_ranks: { support: 3000, damage: 2800 },
  role_sources: {},
  role_top_heroes: {},
  role_sub_roles: {},
  notes: null,
  custom_fields: [],
  version: 1,
  ...overrides
});

const onClockPick: DraftPick = {
  id: 1,
  session_id: 1,
  overall_no: 1,
  round_no: 1,
  pick_in_round: 1,
  draft_team_id: 10,
  target_role: null,
  target_rank_value: null,
  status: "on_clock",
  picked_player_id: null,
  picked_by_user_id: null,
  is_autopick: false,
  is_admin_override: false,
  clock_started_at: null,
  clock_expires_at: null,
  overtime_started_at: null,
  version: 2
};

function board(overrides: Partial<DraftBoard> = {}, session: Partial<DraftBoard["session"]> = {}): DraftBoard {
  return {
    session: {
      id: 1,
      tournament_id: 5,
      workspace_id: 2,
      status: "live",
      blocked_reason: null,
      format: "snake",
      rounds: 2,
      pick_time_seconds: 45,
      overtime_seconds: 15,
      roster_shape: {
        slots: { tank: 1, damage: 2, support: 2 },
        team_size: 5,
        flex_slots: 0,
        has_role_slots: true,
        draft_rounds: 4,
        source: "tournament"
      },
      current_pick_id: 1,
      pool_source: "manual",
      source_balance_id: null,
      autopick_strategy: "best_fit",
      allow_admin_override: true,
      exported_at: null,
      export_status: null,
      settings_json: {},
      version: 0,
      created_at: null,
      ...session
    },
    teams: [team(10, 1), team(11, 2)],
    picks: [onClockPick, { ...onClockPick, id: 2, overall_no: 2, pick_in_round: 2, draft_team_id: 11, status: "upcoming" }],
    players: [player(50), player(51)],
    current_pick: onClockPick,
    server_time: "2026-06-05T00:00:00Z",
    last_event_id: 0,
    ...overrides
  };
}

const noop = () => {};
const mutations = {
  makePick: { mutate: noop, isPending: false },
  autopick: { mutate: noop, isPending: false },
  override: { mutate: noop, isPending: false },
  lifecycle: { mutate: noop, isPending: false },
  editPlayerRole: { mutate: noop, isPending: false },
  extendClock: { mutate: noop, isPending: false }
} as unknown as DraftMutations;

const tournament = { id: 5, name: "Cup #41", workspace_id: 2 } as unknown as Tournament;

const gating = (overrides: Partial<DraftGating>): DraftGating => ({
  myTeamId: null,
  isCaptain: false,
  isAdmin: false,
  isMyPick: false,
  isSpectator: false,
  ...overrides
});

const spectator = gating({ isSpectator: true });
const captainOnClock = gating({ isCaptain: true, isMyPick: true, myTeamId: 10 });
const admin = gating({ isAdmin: true });

// Quotes unescaped so assertions can name the translation payloads as written.
function render(seat: DraftGating, snapshot: DraftBoard = board()) {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DraftWorkspace
        tournament={tournament}
        board={snapshot}
        gating={seat}
        presence={{ users: {}, anonymous_viewer_count: 3 }}
        options={null}
        optionsLoading={false}
        onRetryOptions={noop}
        connectionState="connected"
        viewParams={{ role: "all", sort: "rank", view: "pool", pool: "available", teams: "rosters", query: "" }}
        onViewParamsChange={noop}
        mutations={mutations}
        divisionGrid={{ tiers: [] }}
        onlineCaptainIds={new Set()}
      />
    </QueryClientProvider>
  ).replaceAll("&quot;", '"');
}

describe("DraftWorkspace seats", () => {
  test("a spectator reads the clock, and gets no organizer strip", () => {
    const html = render(spectator);

    expect(html).toContain('role="timer"');
    expect(html).toContain("shell.seat.spectator");
    expect(html).toContain("shell.strip.picking");
    expect(html).not.toContain("shell.admin.label");
    expect(html).not.toContain("admin.pause");
  });

  test("a captain on the clock is told it is their turn", () => {
    const html = render(captainOnClock);

    expect(html).toContain('shell.seat.captain:{"team":"Team 10"}');
    expect(html).toContain("shell.strip.myTurn");
    expect(html).not.toContain("shell.admin.label");
  });

  test("a captain waiting for their turn sees how far away it is", () => {
    const html = render(gating({ isCaptain: true, myTeamId: 11 }));

    expect(html).toContain('shell.strip.myTurnIn:{"count":1}');
    expect(html).not.toContain("shell.strip.myTurn<");
  });

  test("an admin gets the organizer strip, a captain does not", () => {
    const adminHtml = render(admin);
    const captainHtml = render(gating({ isCaptain: true, myTeamId: 10 }));

    expect(adminHtml).toContain("shell.seat.admin");
    expect(adminHtml).toContain("admin.pause");
    expect(adminHtml).toContain("shell.admin.autopickNow");
    expect(adminHtml).toContain('shell.admin.captainsOnline:{"online":0,"total":2}');
    expect(captainHtml).not.toContain("admin.pause");
  });

  test("an admin who also captains keeps both affordances", () => {
    const html = render(gating({ isAdmin: true, isCaptain: true, isMyPick: true, myTeamId: 10 }));

    expect(html).toContain('shell.seat.captain_admin:{"team":"Team 10"}');
    expect(html).toContain("admin.pause");
    expect(html).toContain("shell.strip.myTurn");
  });

  test("rollback names the pick it would undo", () => {
    const done: DraftPick = { ...onClockPick, status: "completed", picked_player_id: 50 };
    const next: DraftPick = { ...onClockPick, id: 2, overall_no: 2, pick_in_round: 2, draft_team_id: 11 };
    const html = render(admin, board({ picks: [done, next], current_pick: next }));

    expect(html).toContain('shell.admin.rollbackPick:{"pick":1}');
  });

  test("the header links back to the tournament and counts the room", () => {
    const html = render(spectator);

    expect(html).toContain('href="/tournaments/5"');
    expect(html).toContain("Cup #41");
    expect(html).toContain('shell.viewers:{"count":3}');
    expect(html).toContain("shell.formatLine:");
  });
});

describe("DraftWorkspace banner", () => {
  test("a pause reads differently to the captain waiting on it than to a spectator", () => {
    const paused = board({}, { status: "paused" });

    expect(render(gating({ isCaptain: true, myTeamId: 10 }), paused)).toContain("shell.banner.pausedCaptain");
    expect(render(spectator, paused)).toContain("shell.banner.pausedSpectator");
  });

  test("a blocked draft links the organizer to the fix, nobody else", () => {
    const blocked = board({}, { status: "paused", blocked_reason: "role_shortage" });
    const link = 'href="/admin/tournaments/5/teams/draft"';

    expect(render(admin, blocked)).toContain("shell.banner.blocked.role_shortage");
    expect(render(admin, blocked)).toContain(link);
    expect(render(spectator, blocked)).not.toContain(link);
  });

  test("overtime of another team names that team", () => {
    const pick = { ...onClockPick, overtime_started_at: "2026-06-05T00:00:45Z" };
    const html = render(spectator, board({ current_pick: pick, picks: [pick] }));

    expect(html).toContain("shell.banner.overtimeOther:");
    expect(html).toContain('"team":"Team 10"');
  });

  test("a finished draft says so, and the strip stops naming a team on the clock", () => {
    const html = render(spectator, board({ current_pick: null }, { status: "completed" }));

    expect(html).toContain("shell.banner.finished:");
    expect(html).toContain("shell.strip.completed");
  });
});
