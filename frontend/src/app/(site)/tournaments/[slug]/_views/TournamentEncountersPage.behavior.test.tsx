// @vitest-environment happy-dom
//
// This section replaced a flat, paginated 90-row table. Four things are pinned
// here, all of them the reasons the table was wrong:
//
//  1. matches are grouped, and the round view reads FINAL FIRST — ordered by
//     the bracket's own match numbering, so a Grand Final at round 2 outranks
//     the round-1 pair that fed it (§7 ⑥);
//  2. the "by time" view does not exist until the organizer has scheduled
//     something. Every tournament in the database predates match scheduling,
//     and a segment that switches to an empty view is a dead control (§7 ①);
//  3. once a schedule exists, the time view groups by calendar day, naming the
//     day's stage when its matches share one (§7 ④);
//  4. `?team=` and `?stage=` narrow the list — `?team=` is where "team matches"
//     from the teams section lands (§7 ②).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Encounter, Match } from "@/types/encounter.types";
import type { Team } from "@/types/team.types";
import type { StageSummary, StageType, Tournament } from "@/types/tournament.types";

import TournamentEncountersPage from "./TournamentEncountersPage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TOURNAMENT_ID = 88;
const WORKSPACE_ID = 3;
/** Well after every fixture instant, so nothing is ever "still to come". */
const NOW = Date.parse("2025-09-01T12:00:00Z");

const getAll = vi.fn();

vi.mock("@/services/encounter.service", () => ({
  default: { getAll: (...args: unknown[]) => getAll(...args) }
}));

let search = new URLSearchParams();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => `/tournaments/${TOURNAMENT_ID}/matches`,
  useSearchParams: () => search,
  useRouter: () => ({ replace, push: vi.fn() })
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

vi.mock("@/hooks/useTournamentClientData", () => ({
  useTournamentQuery: () => ({ data: TOURNAMENT, isError: false, refetch: () => {} })
}));

/**
 * Every field spelled out rather than cast into place: `tsconfig.json` excludes
 * test files, so a fixture that lies about its shape type-checks green and
 * feeds the component a hole.
 */
function stage(id: number, name: string, order: number, stageType: StageType): StageSummary {
  return {
    id,
    tournament_id: TOURNAMENT_ID,
    name,
    description: null,
    stage_type: stageType,
    max_rounds: 5,
    advance_count: null,
    split_lower_bracket: false,
    order,
    is_active: false,
    is_published: true,
    is_completed: true,
    settings_json: null,
    challonge_id: null,
    challonge_slug: null
  };
}

/**
 * Groups before playoffs by `order`, and the reverse of that by id, so a view
 * that sorted on the id would put the sections the wrong way round.
 */
const GROUPS = stage(189, "Groups", 0, "round_robin");
const PLAYOFFS = stage(188, "Playoffs", 1, "double_elimination");

const TOURNAMENT: Tournament = {
  id: TOURNAMENT_ID,
  created_at: new Date(0),
  updated_at: null,
  workspace_id: WORKSPACE_ID,
  name: "Anak Cup",
  slug: "anak-cup",
  start_date: new Date(0),
  end_date: new Date(0),
  description: null,
  challonge_id: null,
  challonge_slug: null,
  is_league: false,
  is_finished: true,
  is_hidden: false,
  team_formation: "balancer",
  status: "completed",
  auto_transitions_enabled: true,
  allow_late_registration: false,
  phase_schedule: [],
  win_points: 1,
  draw_points: 0.5,
  loss_points: 0,
  stages: [GROUPS, PLAYOFFS],
  participants_count: 20,
  registrations_count: 20,
  teams_count: 4,
  division_grid_version_id: null,
  division_grid_version: null,
  roster_slots_json: null,
  roster_shape: null,
  roster_locked_by_draft: null
};

function team(id: number, name: string): Team {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name,
    image_url: null,
    avg_sr: 3000,
    total_sr: 15000,
    captain_id: id * 10,
    tournament_id: TOURNAMENT_ID,
    players: [],
    tournament: null,
    placement: null,
    group: null
  };
}

const ALPHA = team(11, "Alpha");
const BRAVO = team(12, "Bravo");
const CHARLIE = team(13, "Charlie");
const DELTA = team(14, "Delta");

function mapRow(id: number, encounterId: number, home: Team, away: Team): Match {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    home_team_id: home.id,
    away_team_id: away.id,
    score: { home: 2, away: 1 },
    time: 680,
    encounter_id: encounterId,
    map_id: 52,
    map_index: 1,
    log_name: "log.txt",
    source: "log_parser",
    code: null,
    map: null,
    home_team: null,
    away_team: null,
    encounter: null
  };
}

/**
 * One settled encounter. `at` is midday UTC on purpose: a fixture timed near
 * midnight would fall on a different calendar day depending on the machine's
 * time zone, and the day grouping is local by design.
 */
function encounter(
  id: number,
  stageSummary: StageSummary,
  round: number,
  home: Team,
  away: Team,
  at: string,
  options: { group?: string; scheduled?: boolean } = {}
): Encounter {
  const ended = new Date(at);
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name: `${home.name} vs ${away.name}`,
    home_team_id: home.id,
    away_team_id: away.id,
    score: { home: 2, away: 0 },
    round,
    best_of: 2,
    tournament_id: TOURNAMENT_ID,
    stage_id: stageSummary.id,
    stage_item_id: options.group ? stageSummary.id * 100 : null,
    challonge_id: null,
    status: "completed",
    closeness: 6,
    has_logs: true,
    result_status: "confirmed",
    scheduled_at: options.scheduled === true ? ended : null,
    started_at: ended,
    ended_at: ended,
    current_map_index: null,
    confirmed_at: ended,
    sources: [],
    matches: [mapRow(id * 10, id, home, away)],
    home_team: home,
    away_team: away,
    tournament: TOURNAMENT,
    stage: { ...stageSummary, items: [] },
    stage_item: options.group
      ? {
          id: stageSummary.id * 100,
          stage_id: stageSummary.id,
          name: options.group,
          type: "group",
          order: 0,
          inputs: []
        }
      : null
  };
}

/**
 * Five settled matches across two stages. The playoff stage carries a two-match
 * round 1 and a single-match round 2, which is what makes round 2 the Grand
 * Final by the bracket's own rule (`getDoubleEliminationFinalRounds`).
 *
 * Alpha never meets Delta, so `?team=11` has an observable consequence: Delta
 * disappears from the page entirely.
 */
function fixtures(scheduled: boolean): Encounter[] {
  const options = (group?: string) => ({ group, scheduled });
  return [
    encounter(501, GROUPS, 5, ALPHA, BRAVO, "2025-08-15T12:00:00Z", options("B")),
    encounter(502, GROUPS, 4, CHARLIE, DELTA, "2025-08-14T12:00:00Z", options("A")),
    encounter(503, PLAYOFFS, 1, ALPHA, CHARLIE, "2025-08-16T10:00:00Z", options()),
    encounter(504, PLAYOFFS, 1, BRAVO, DELTA, "2025-08-16T12:00:00Z", options()),
    encounter(505, PLAYOFFS, 2, ALPHA, CHARLIE, "2025-08-16T14:00:00Z", options())
  ];
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

/** Let queued promise callbacks and React Query's own scheduling drain. */
async function settle(ticks = 3) {
  for (let index = 0; index < ticks; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function render(encounters: Encounter[], query = "") {
  getAll.mockResolvedValue({
    results: encounters,
    total: encounters.length,
    page: 1,
    per_page: -1,
    total_pages: 1
  });
  search = new URLSearchParams(query);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <TournamentEncountersPage
            tournamentId={TOURNAMENT_ID}
            slug={String(TOURNAMENT_ID)}
            now={NOW}
          />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  return container.textContent ?? "";
}

/** Every group heading, in DOM order — the page's whole structure in one array. */
function headings(): string[] {
  return Array.from(container.querySelectorAll("h2")).map((heading) =>
    (heading.textContent ?? "").trim()
  );
}

/** The view switcher, or `null` when the section offers a single view. */
function segment(): { labels: string[]; selected: string | null } | null {
  const tablist = container.querySelector('[role="radiogroup"]');
  if (!tablist) return null;
  const tabs = Array.from(tablist.querySelectorAll('[role="radio"]'));
  return {
    labels: tabs.map((tab) => (tab.textContent ?? "").trim()),
    selected:
      tabs.find((tab) => tab.getAttribute("aria-checked") === "true")?.textContent?.trim() ?? null
  };
}

/**
 * The leading mono cell of every row, in DOM order. Addressed through the
 * structure — each heading is followed by its list, each row's first `span` is
 * the leading cell — rather than through a utility class, so a visual pass that
 * renames one does not fail this.
 */
function leadingCells(): string[] {
  return Array.from(container.querySelectorAll("h2")).flatMap((heading) =>
    Array.from(heading.nextElementSibling?.children ?? []).map((row) =>
      (row.querySelector("span")?.textContent ?? "").trim()
    )
  );
}

const COPY = en.tournamentDetail.matches;

describe("tournament matches", () => {
  it("groups by stage and round, final first, without a time view to switch to", async () => {
    await render(fixtures(false));

    // Playoffs first (later stage), its Grand Final ahead of the round that fed
    // it, then the group rounds counting down.
    expect(headings()).toEqual([
      "Playoffs · Grand Final",
      "Playoffs · UB Final · 2 matches",
      "Groups · Round 5",
      "Groups · Round 4"
    ]);
    // No `scheduled_at` anywhere: one view, so no switcher at all.
    expect(segment()).toBeNull();
    // Elimination rows lead with the bracket's match number, group rows with the
    // group's own letter.
    expect(leadingCells()).toEqual(["M3 · Bo2", "M1 · Bo2", "M2 · Bo2", "B", "A"]);
  });

  it("offers the time view once anything is scheduled, and groups it by day", async () => {
    await render(fixtures(true));

    expect(segment()).toEqual({
      labels: [COPY.viewRound, COPY.viewTime],
      selected: COPY.viewRound
    });

    const text = await render(fixtures(true), "view=time");
    const days = headings();
    expect(days).toHaveLength(3);
    // Newest day first; the stage names the day because that day's matches all
    // belong to one, and the count is the day's own.
    expect(days[0]).toContain("Aug 16");
    expect(days[0]).toContain("Playoffs");
    expect(days[0]).toContain("3 matches");
    expect(days[1]).toContain("Aug 15");
    expect(days[1]).toContain("Groups");
    expect(days[2]).toContain("Aug 14");
    // The round moves into the row, since the day heading no longer names it.
    expect(text).toContain("Grand Final · Bo2");
    expect(text).toContain("Group B · Bo2");
  });

  it("puts a live match in its own section as a card", async () => {
    const live: Encounter = {
      ...encounter(506, PLAYOFFS, 3, ALPHA, BRAVO, "2025-09-01T11:00:00Z", { scheduled: true }),
      status: "in_progress",
      score: { home: 1, away: 1 },
      ended_at: null,
      confirmed_at: null
    };
    await render([...fixtures(true), live], "view=time");

    expect(headings()[0]).toBe(COPY.now);
    // The card, not a row: `MatchCard` marks itself live.
    expect(container.querySelector("[data-live]")).not.toBeNull();
  });

  it("narrows the list to one team, and to one stage", async () => {
    const byTeam = await render(fixtures(false), "team=11");

    expect(headings()).toEqual([
      "Playoffs · Grand Final",
      "Playoffs · UB Final",
      "Groups · Round 5"
    ]);
    expect(byTeam).toContain("Alpha");
    // Alpha never played Delta, so the only opponent left out is observable.
    expect(byTeam).not.toContain("Delta");

    const byStage = await render(fixtures(false), `stage=${GROUPS.id}`);
    expect(headings()).toEqual(["Groups · Round 5", "Groups · Round 4"]);
    expect(byStage).not.toContain("Playoffs · ");
  });

  it("says nothing exists rather than showing an empty grouping", async () => {
    const text = await render([]);

    expect(text).toContain(en.tournamentDetail.publicPages.matches.emptyTitle);
    expect(headings()).toEqual([]);
    expect(segment()).toBeNull();
  });

  it("offers a way out when the filters exclude everything", async () => {
    const text = await render(fixtures(false), "team=999");

    expect(text).toContain(en.tournamentDetail.pageState.filteredEmpty.title);
    expect(headings()).toEqual([]);
  });
});
