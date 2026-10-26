import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { buildTeamViews, filterSortTeams } from "@/lib/draft/room-model";
import type { RosterShape } from "@/lib/roster/shape";
import { DEADLOCK_METADATA, OW_METADATA } from "@/test/discipline-metadata";
import type { DraftBoard, DraftPick, DraftPlayer, DraftSession, DraftTeam } from "@/types/draft.types";

vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () =>
    Object.assign(
      (key: string, values?: Record<string, unknown>) => (values ? `${key}:${JSON.stringify(values)}` : key),
      { has: () => false }
    )
}));

// `next/image` rewrites src through the optimizer loader; the stand-in keeps
// the stored URL so the test can read it.
vi.mock("next/image", () => ({
  // eslint-disable-next-line @next/next/no-img-element -- this IS the next/image stand-in
  default: (props: React.ImgHTMLAttributes<HTMLImageElement>) => <img {...props} alt={props.alt ?? ""} />
}));

// Dynamic, not static: `mock.module` only applies to modules imported after it
// runs, and the components call `useTranslations` at render time.
const { TeamRosters } = await import("./TeamRosters");
const { TeamsPanel } = await import("./TeamsPanel");

const ROLE_SHAPE: RosterShape = {
  slots: { tank: 1, damage: 2, support: 2 },
  team_size: 5,
  flex_slots: 0,
  has_role_slots: true,
  draft_rounds: 4,
  source: "tournament"
};
const FLEX_SHAPE: RosterShape = {
  slots: { flex: 5 },
  team_size: 5,
  flex_slots: 5,
  has_role_slots: false,
  draft_rounds: 4,
  source: "tournament"
};
const MIXED_SHAPE: RosterShape = {
  slots: { tank: 1, damage: 2, flex: 2 },
  team_size: 5,
  flex_slots: 2,
  has_role_slots: true,
  draft_rounds: 4,
  source: "tournament"
};

// Two tiers so a rank resolves to a division and the cell title carries the number.
const GRID = {
  tiers: [
    { slug: "high", number: 9, name: "High", sort_order: 0, rank_min: 4000, rank_max: 4999, icon_url: "/high.png" },
    { slug: "low", number: 4, name: "Low", sort_order: 1, rank_min: 2000, rank_max: 2999, icon_url: "/low.png" }
  ]
};

function makeTeam(id: number, name = `Team ${id}`): DraftTeam {
  return {
    id,
    session_id: 1,
    captain_user_id: null,
    captain_auth_user_id: 100 + id,
    name,
    draft_position: id,
    exported_team_id: null
  };
}

// Drafted on support at 2800, but their best role is damage at 4000 — the two
// ranks the shape has to choose between.
const drafted: DraftPlayer = {
  id: 7,
  session_id: 1,
  registration_id: 70,
  user_id: null,
  identity: { provider: "battlenet", handle: "Ana#1234" }, player_name: null,
  primary_role: { dimension: "player_role", role: "support" },
  is_flex: false,
  effective_rank: 4000,
  status: "picked",
  is_captain: false,
  drafted_by_team_id: 1,
  secondary_roles: [{ dimension: "player_role", role: "damage" }],
  role_ranks: { support: 2800, damage: 4000 },
  role_sources: { support: "registration", damage: "registration" },
  role_top_characters: {},
  role_sub_roles: {},
  notes: null,
  custom_fields: [],
  version: 1
};

function makePick(
  id: number,
  round: number,
  inRound: number,
  teamId: number,
  status: DraftPick["status"],
  extra: Partial<DraftPick> = {}
): DraftPick {
  return {
    id,
    session_id: 1,
    overall_no: id,
    round_no: round,
    pick_in_round: inRound,
    draft_team_id: teamId,
    target_role: null,
    target_rank_value: null,
    status,
    picked_player_id: null,
    picked_by_user_id: null,
    is_autopick: false,
    is_admin_override: false,
    clock_started_at: null,
    clock_expires_at: null,
    overtime_started_at: null,
    version: 1,
    ...extra
  };
}

const supportPick = makePick(1, 1, 1, 1, "completed", { picked_player_id: 7, target_role: { dimension: "player_role", role: "support" } });

function makeBoard(
  shape: RosterShape,
  { teams = [makeTeam(1)], players = [drafted], picks = [supportPick] }: {
    teams?: DraftTeam[];
    players?: DraftPlayer[];
    picks?: DraftPick[];
  } = {}
): DraftBoard {
  return {
    session: { id: 1, status: "live", format: "snake", roster_shape: shape } as unknown as DraftSession,
    teams,
    picks,
    players,
    current_pick: picks.find((pick) => pick.status === "on_clock") ?? null,
    last_event_id: null
  };
}

const noop = () => {};

function renderRosters(
  board: DraftBoard,
  {
    myTeamId = null,
    followed = new Set<number>(),
    filter = "all",
    onSlotFilter,
    ontology = OW_METADATA
  }: {
    myTeamId?: number | null;
    followed?: ReadonlySet<number>;
    filter?: "all" | "follow" | "tank" | "damage" | "support";
    onSlotFilter?: (role: "tank" | "damage" | "support") => void;
    ontology?: typeof OW_METADATA;
  } = {}
) {
  const teamViews = buildTeamViews(board);
  // The rank crests also ask for the current workspace's own grid, through the query cache.
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <TeamRosters
        board={board}
        teamViews={teamViews}
        teams={filterSortTeams(board, teamViews, { filter, sort: "order", followed, myTeamId })}
        filter={filter}
        onFilterChange={noop}
        sort="order"
        onSortChange={noop}
        followed={followed}
        onToggleFollow={noop}
        myTeamId={myTeamId}
        onlineCaptainIds={new Set([101])}
        onOpenProfile={noop}
        onSlotFilter={onSlotFilter}
        divisionGrid={GRID}
        ontology={ontology}
        clockColor="var(--aqt-fg)"
      />
    </QueryClientProvider>
  );
}

describe("roster cells", () => {
  test("a role slot shows the drafted role and that role's rank, crest included", () => {
    const html = renderRosters(makeBoard(ROLE_SHAPE));
    const cell = html.match(/<button[^>]*aria-label="Ana#1234[^"]*"[^>]*>.*?<\/button>/)?.[0] ?? "";

    expect(html).toContain('aria-label="Ana#1234 · Support · 2800 SR');
    expect(html).not.toContain("4000 SR");
    // The crest is the rank a viewer reads at a glance: the slot's, not the best role's.
    expect(cell).toContain("/low.png");
    expect(cell).not.toContain("/high.png");
  });

  test("an all-flex roster names the flex slot, uses the best rank and offers no role chips", () => {
    // Nobody holds a role under this shape: a role label would state an
    // assignment that was never made, and a role chip a need that does not exist.
    const html = renderRosters(makeBoard(FLEX_SHAPE));

    expect(html).toContain('aria-label="Ana#1234 · flex · 4000 SR');
    expect(html).not.toContain("2800 SR");
    expect(html).not.toContain("teams.chips.needAria");
  });

  test("a mixed shape spans one flex icon over its flex columns and chips only its role slots", () => {
    const html = renderRosters(makeBoard(MIXED_SHAPE, { players: [], picks: [] }));

    expect(html).toContain('title="flex" class="flex justify-center" style="grid-column:span 2"');
    expect(html).toContain("repeat(5, minmax(0,1fr))");
    expect(html).toContain("teams.chips.needAria:{&quot;role&quot;:&quot;tank&quot;,&quot;label&quot;:&quot;Tank&quot;");
    expect(html).toContain("teams.chips.needAria:{&quot;role&quot;:&quot;damage&quot;,&quot;label&quot;:&quot;Damage&quot;");
    expect(html).not.toContain("&quot;role&quot;:&quot;support&quot;");
  });

  test("a player left without a playable role gets no stand-in rank", () => {
    const html = renderRosters(
      makeBoard(ROLE_SHAPE, {
        players: [{ ...drafted, primary_role: null, secondary_roles: [], role_ranks: {} }],
        picks: []
      })
    );

    expect(html).toContain("Ana#1234");
    expect(html).not.toContain("SR");
  });

  test("columns follow the widest roster the server seated", () => {
    const shape: RosterShape = { ...ROLE_SHAPE, slots: { tank: 1 }, team_size: 1, draft_rounds: 1 };
    const html = renderRosters(makeBoard(shape, { players: [], picks: [] }));

    expect(html).toContain("repeat(1, minmax(0,1fr))");
  });
});

describe("open slots", () => {
  test("my own open role slots are buttons that filter the pool", () => {
    const html = renderRosters(makeBoard(ROLE_SHAPE), { myTeamId: 1, onSlotFilter: noop });

    expect(html).toContain('aria-label="filterBySlot:{&quot;role&quot;:&quot;Tank&quot;}"');
    expect(html).toContain('aria-label="filterBySlot:{&quot;role&quot;:&quot;Damage&quot;}"');
  });

  test("an open flex slot never filters: it asks for no role", () => {
    const html = renderRosters(makeBoard(FLEX_SHAPE), { myTeamId: 1, onSlotFilter: noop });

    expect(html).not.toContain("filterBySlot");
    expect(html).toContain("teams.cell.open:{&quot;role&quot;:&quot;flex&quot;}");
  });

  test("another captain's open slots stay inert", () => {
    const html = renderRosters(makeBoard(ROLE_SHAPE), { myTeamId: 2, onSlotFilter: noop });

    expect(html).not.toContain("filterBySlot");
    expect(html).toContain("teams.cell.open");
  });
});

describe("team rows", () => {
  const teams = [makeTeam(1), makeTeam(2)];
  const picks = [makePick(1, 1, 1, 1, "on_clock"), makePick(2, 1, 2, 2, "upcoming")];
  const board = makeBoard(ROLE_SHAPE, { teams, players: [], picks });

  test("the team on the clock reads as picking and my team counts its wait", () => {
    const html = renderRosters(board, { myTeamId: 2 });

    expect(html).toContain("teams.sub.picking");
    expect(html).toContain("teams.sub.mine:{&quot;status&quot;:&quot;teams.sub.in:{\\&quot;n\\&quot;:1}&quot;}");
  });

  test("the follow star is a named toggle", () => {
    const html = renderRosters(board, { followed: new Set([2]) });

    expect(html).toContain('aria-pressed="true" aria-label="teams.unfollow:{&quot;team&quot;:&quot;Team 2&quot;}"');
    expect(html).toContain('aria-pressed="false" aria-label="teams.follow:{&quot;team&quot;:&quot;Team 1&quot;}"');
  });

  test("captain presence is announced per row", () => {
    const html = renderRosters(board);

    expect(html).toContain('aria-label="teams.captainOnline"');
    expect(html).toContain('aria-label="teams.captainOffline"');
  });

  test("an empty follow filter explains how to fill it", () => {
    const html = renderRosters(board, { filter: "follow" });

    expect(html).toContain("teams.empty.follow");
  });
});

describe("order tab", () => {
  function renderOrder(picks: DraftPick[], teams = [makeTeam(1), makeTeam(2)]) {
    const board = makeBoard(ROLE_SHAPE, { teams, players: [], picks });
    return renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <TeamsPanel
          board={board}
          teamViews={buildTeamViews(board)}
          tab="order"
          onTabChange={noop}
          filter="all"
          onFilterChange={noop}
          sort="order"
          onSortChange={noop}
          followed={new Set()}
          onToggleFollow={noop}
          myTeamId={null}
          onlineCaptainIds={new Set()}
          onOpenProfile={noop}
          divisionGrid={GRID}
          ontology={OW_METADATA}
          headingId="teams-h"
        />
      </QueryClientProvider>
    );
  }

  test("alternating rounds read as a snake with a reversed second round", () => {
    const html = renderOrder([
      makePick(1, 1, 1, 1, "on_clock"),
      makePick(2, 1, 2, 2, "upcoming"),
      makePick(3, 2, 1, 2, "upcoming"),
      makePick(4, 2, 2, 1, "upcoming")
    ]);

    expect(html).toContain("teams.order.note.snake");
    expect(html).toContain("teams.order.roundTitle:{&quot;n&quot;:2,&quot;direction&quot;:&quot;reverse&quot;}");
    expect(html).toContain("teams.order.in:{&quot;n&quot;:3}");
  });

  test("every round forward reads as linear, whatever the format says", () => {
    const html = renderOrder([
      makePick(1, 1, 1, 1, "completed"),
      makePick(2, 1, 2, 2, "on_clock"),
      makePick(3, 2, 1, 1, "upcoming"),
      makePick(4, 2, 2, 2, "upcoming")
    ]);

    expect(html).toContain("teams.order.note.linear");
    expect(html).not.toContain("&quot;direction&quot;:&quot;reverse&quot;");
    expect(html).toContain("teams.order.now");
  });

  test("rounds that neither run straight nor alternate read as custom", () => {
    // Two reversed rounds in a row: a snake formula would call round 3 forward.
    const reversedTwice = renderOrder([
      makePick(1, 1, 1, 1, "on_clock"),
      makePick(2, 1, 2, 2, "upcoming"),
      makePick(3, 2, 1, 2, "upcoming"),
      makePick(4, 2, 2, 1, "upcoming"),
      makePick(5, 3, 1, 2, "upcoming"),
      makePick(6, 3, 2, 1, "upcoming")
    ]);
    expect(reversedTwice).toContain("teams.order.note.custom");
    expect(reversedTwice).toContain("teams.order.roundTitle:{&quot;n&quot;:3,&quot;direction&quot;:&quot;reverse&quot;}");

    // Seats 1, 3, 2 within one round: no direction at all.
    const shuffled = renderOrder(
      [makePick(1, 1, 1, 1, "on_clock"), makePick(2, 1, 2, 3, "upcoming"), makePick(3, 1, 3, 2, "upcoming")],
      [makeTeam(1), makeTeam(2), makeTeam(3)]
    );
    expect(shuffled).toContain("teams.order.roundTitle:{&quot;n&quot;:1,&quot;direction&quot;:&quot;custom&quot;}");
  });
});

describe("a one-role game", () => {
  test("names no role: no need chips, no slot heads, the cell reads the player and the rank", () => {
    const agent = { dimension: "agent", role: "agent" };
    const shape: RosterShape = {
      slots: { agent: 6 },
      team_size: 6,
      flex_slots: 0,
      has_role_slots: true,
      draft_rounds: 5,
      source: "tournament"
    };
    const player: DraftPlayer = {
      ...drafted,
      primary_role: agent,
      secondary_roles: [],
      role_ranks: { agent: 2800 },
      role_sources: { agent: "registration" }
    };
    const pick = makePick(1, 1, 1, 1, "completed", { picked_player_id: 7, target_role: agent });

    const html = renderRosters(makeBoard(shape, { players: [player], picks: [pick] }), { ontology: DEADLOCK_METADATA });

    expect(html).toContain('aria-label="Ana#1234 · 2800 SR');
    expect(html).not.toContain("teams.chips.need");
    expect(html).not.toContain("Agent");
    expect(html).toContain("teams.cell.openSeat");
  });
});
