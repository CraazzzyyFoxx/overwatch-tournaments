import { describe, expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { DraftGating } from "@/lib/draft-logic";
import type { DraftBoard, DraftPick, DraftPlayer, DraftTeam } from "@/types/draft.types";
import type { DraftMutations } from "@/hooks/useDraftData";

mock.module("next-intl", () => ({
  useLocale: () => "en",
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

function board(overrides: Partial<DraftBoard> = {}): DraftBoard {
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
      created_at: null
    },
    teams: [team(10, 1), team(11, 2)],
    picks: [onClockPick, { ...onClockPick, id: 2, overall_no: 2, draft_team_id: 11, status: "upcoming" }],
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

const gating = (overrides: Partial<DraftGating>): DraftGating => ({
  myTeamId: null,
  isCaptain: false,
  isAdmin: false,
  isMyPick: false,
  isSpectator: false,
  ...overrides
});

function render(seat: DraftGating, boardOverrides: Partial<DraftBoard> = {}) {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DraftWorkspace
        board={board(boardOverrides)}
        gating={seat}
        options={null}
        optionsLoading={false}
        onRetryOptions={noop}
        connectionState="connected"
        viewParams={{ role: "all", sort: "rank", view: "pool", pool: "available", query: "" }}
        onViewParamsChange={noop}
        mutations={mutations}
        divisionGrid={{ tiers: [] }}
      />
    </QueryClientProvider>
  );
}

describe("DraftWorkspace seats", () => {
  test("a spectator gets the board and the clock, and nothing to press", () => {
    const html = render(gating({ isSpectator: true }));

    expect(html).not.toContain("pickAs:");
    expect(html).not.toContain("confirmPick");
    expect(html).not.toContain("admin.pause");
    // The bar is still there: the clock and who is on it are public.
    expect(html).toContain('role="timer"');
    expect(html).toContain("spectatorReadOnly");
  });

  test("a captain on the clock confirms straight from the bar", () => {
    const html = render(gating({ isCaptain: true, isMyPick: true, myTeamId: 10 }));

    expect(html).toContain("confirmPick");
    // One click, not a review dialog restating the selection beside it.
    expect(html).not.toContain("confirmPickTitle");
    expect(html).toContain("pickAs:");
    // My own open role slots double as pool filters.
    expect(html).toContain("filterBySlot:");
  });

  test("an admin gets the dock, a captain does not", () => {
    const adminHtml = render(gating({ isAdmin: true }));
    const captainHtml = render(gating({ isCaptain: true, myTeamId: 10 }));

    expect(adminHtml).toContain("admin.pause");
    expect(adminHtml).toContain("admin.rollback");
    expect(captainHtml).not.toContain("admin.pause");
  });

  test("an admin who also captains keeps both affordances", () => {
    const html = render(gating({ isAdmin: true, isCaptain: true, isMyPick: true, myTeamId: 10 }));

    expect(html).toContain("admin.pause");
    expect(html).toContain("confirmPick");
  });

  test("the mobile and desktop trees each own their heading ids", () => {
    // Both are mounted at once, so a shared id would make every
    // aria-labelledby in the room resolve to the first match.
    const html = render(gating({ isSpectator: true }));

    expect(html).toContain('id="player-pool-mobile-heading"');
    expect(html).toContain('id="player-pool-desktop-heading"');
    // Radix mounts only the active tab panel, so the order rail's own pair is
    // covered by the desktop rail plus the mobile one the tab renders when open.
    expect(html).toContain('id="draft-order-desktop-heading"');
  });

  test("overtime is announced on the bar, not only on the ring", () => {
    const pick = { ...onClockPick, overtime_started_at: "2026-06-05T00:00:45Z" };
    const html = render(gating({ isSpectator: true }), { current_pick: pick, picks: [pick] });

    expect(html).toContain(">overtime<");
  });
});
