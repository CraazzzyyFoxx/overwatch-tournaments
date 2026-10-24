// @vitest-environment happy-dom
//
// The overview is the tournament's landing page and it is not one screen: it is
// three, chosen by `status` (wireframes §3 A/B/C). What is pinned here is
// exactly the part a reader would notice if a branch regressed:
//
//  1. before the tournament starts, the phase timeline IS the page — it renders
//     first and carries `#phases`, because the retired `/schedule` route 301s
//     to that anchor and a missing id turns the redirect into a no-op scroll;
//  2. once play starts, live matches come first, and with nothing live the
//     block falls back rather than disappearing — an empty "Now playing" card
//     on a tournament with eighty played matches is the failure mode;
//  3. a finished tournament opens on its result, with third place read off the
//     lower-bracket final instead of the bracket's top-right corner.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Encounter, EncounterTeam } from "@/types/encounter.types";
import { catalogMap, catalogMode } from "@/test/catalog";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { Registration, RegistrationListResponse } from "@/types/registration.types";
import type { Team } from "@/types/team.types";
import type { TournamentLink } from "@/types/stream.types";
import type { PickBanConfig, Stage, StageSummary, Tournament, TournamentStatus } from "@/types/tournament.types";

import TournamentOverviewPage from "./TournamentOverviewPage";

vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TOURNAMENT_ID = 88;
const WORKSPACE_ID = 3;
const SLUG = "anak-cup";
const DEPLOYMENT_ZONE = "UTC";

const getAllEncounters = vi.fn();
const listRegistrations = vi.fn();
const getStandings = vi.fn();
const getStages = vi.fn();
const getTeams = vi.fn();
const getCharacterPlaytime = vi.fn();
const listPublicConfigs = vi.fn();
const getAllMaps = vi.fn();
const getTournamentStreams = vi.fn();
const getFfaStage = vi.fn();

vi.mock("@/services/encounter.service", () => ({
  default: { getAll: (...args: unknown[]) => getAllEncounters(...args) }
}));
vi.mock("@/services/registration.service", () => ({
  default: { listRegistrations: (...args: unknown[]) => listRegistrations(...args) }
}));
vi.mock("@/services/tournament.service", () => ({
  default: {
    getStandings: (...args: unknown[]) => getStandings(...args),
    getStages: (...args: unknown[]) => getStages(...args)
  }
}));
vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));
vi.mock("@/services/statistics.service", () => ({
  default: { getCharacterPlaytime: (...args: unknown[]) => getCharacterPlaytime(...args) }
}));
vi.mock("@/services/pickBan.service", () => ({
  default: { listPublicConfigs: (...args: unknown[]) => listPublicConfigs(...args) }
}));
vi.mock("@/services/catalog.service", () => ({
  default: { list: (...args: unknown[]) => getAllMaps(...args) }
}));
vi.mock("@/services/stream.service", () => ({
  default: { getTournamentStreams: (...args: unknown[]) => getTournamentStreams(...args) }
}));
vi.mock("@/services/ffa.service", () => ({
  default: { getStage: (...args: unknown[]) => getFfaStage(...args) }
}));

vi.mock("next/navigation", () => ({
  usePathname: () => `/tournaments/${SLUG}`,
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: () => {}, replace: () => {} })
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    prefetch: _prefetch,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    prefetch?: boolean | null;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

let tournament: Tournament;

vi.mock("@/hooks/useTournamentClientData", () => ({
  useTournamentQuery: () => ({ data: tournament, isError: false, refetch: () => {} })
}));

// ---------------------------------------------------------------------------
// Fixtures. Every field spelled out rather than cast into place: `tsconfig.json`
// excludes test files, so a fixture that lies about its shape type-checks green
// and feeds the component a hole.
// ---------------------------------------------------------------------------

function makeStage(overrides: Partial<StageSummary> & { id: number }): StageSummary {
  return {
    tournament_id: TOURNAMENT_ID,
    name: "Playoff",
    description: null,
    stage_type: "double_elimination",
    max_rounds: 2,
    advance_count: null,
    advance_upper_count: null,
    order: 1,
    is_active: true,
    is_published: true,
    is_completed: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: {
      win: null,
      draw: null,
      loss: null,
      preset: null,
      columns: null,
      placement_points: null,
      formula: null
    },
    swiss_bye_points: null,
    swiss_qualify_wins: null,
    swiss_eliminate_losses: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null, swiss_qualify: null, swiss_eliminate: null },
    has_custom_bracket: false,
    challonge_id: null,
    challonge_slug: null,
    ...overrides
  };
}

/** A schedule whose registration is over and whose play window is open. */
const PHASE_SCHEDULE: Tournament["phase_schedule"] = [
  {
    status: "registration",
    starts_at: new Date("2024-08-01T10:00:00Z").toISOString(),
    ends_at: new Date("2024-08-10T10:00:00Z").toISOString()
  },
  {
    status: "check_in",
    starts_at: new Date("2024-08-11T10:00:00Z").toISOString(),
    ends_at: null
  },
  {
    status: "live",
    starts_at: new Date("2024-08-12T10:00:00Z").toISOString(),
    ends_at: null
  }
];

function makeTournament(status: TournamentStatus, overrides: Partial<Tournament> = {}): Tournament {
  return {
    id: TOURNAMENT_ID,
    created_at: new Date(0),
    updated_at: null,
    workspace_id: WORKSPACE_ID,
    name: "Anak Cup",
    slug: SLUG,
    start_date: new Date("2024-08-12T10:00:00Z"),
    end_date: new Date("2024-08-13T22:00:00Z"),
    description: "Players may swap roles between matches.",
    challonge_id: null,
    challonge_slug: null,
    is_league: false,
    is_finished: false,
    is_hidden: false,
    team_formation: "draft",
    status,
    auto_transitions_enabled: true,
    allow_late_registration: false,
    phase_schedule: PHASE_SCHEDULE,
    win_points: 1,
    draw_points: 0.5,
    loss_points: 0,
    stages: [makeStage({ id: 7 })],
    participants_count: 20,
    registrations_count: 24,
    teams_count: 4,
    division_grid_version_id: null,
    division_grid_version: null,
    discipline: "overwatch",
    roster_shape: {
      slots: { tank: 1, damage: 2, support: 2 },
      team_size: 5,
      flex_slots: 0,
      has_role_slots: true,
      draft_rounds: 5,
      source: "workspace"
    },
    roster_locked_by_draft: null,
    links: [],
    cover_image_url: null,
    logo_url: null,
    ...overrides
  };
}

function makeTeam(id: number, name: string, players: string[] = []): Team {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name,
    image_url: null,
    avg_sr: 3500,
    total_sr: 17_500,
    captain_id: id * 10,
    tournament_id: TOURNAMENT_ID,
    players: players.map((playerName, index) => ({
      id: id * 100 + index,
      created_at: new Date(0),
      updated_at: null,
      name: playerName,
      rank: 3500,
      division: 3,
      role: { dimension: "player_role", role: "damage" },
      tournament_id: TOURNAMENT_ID,
      user_id: id * 1000 + index,
      team_id: id,
      is_newcomer: false,
      is_newcomer_role: false,
      is_substitution: false,
      related_player_id: null,
      user: null
    })),
    tournament: null,
    placement: null,
    group: null
  };
}

const ALPHA = makeTeam(1, "Alpha", ["yaLucky", "Kenny"]);
const BETA = makeTeam(2, "Beta");
const GAMMA = makeTeam(3, "Gamma");
const DELTA = makeTeam(4, "Delta");

function seat(slot: number, team: Team, score: number): EncounterTeam {
  return {
    id: team.id * 10 + slot,
    slot,
    team_id: team.id,
    name: team.name,
    seed: null,
    score,
    placement: null,
    active: true,
    team
  };
}

/** `scores` are the standings of slot 1 and slot 2. */
function makeEncounter(
  id: number,
  round: number,
  one: Team,
  two: Team,
  scores: [number, number],
  overrides: Partial<Encounter> = {}
): Encounter {
  return {
    id,
    created_at: new Date("2024-08-12T12:00:00Z"),
    updated_at: null,
    name: `M${id}`,
    slot_count: 2,
    round,
    best_of: 3,
    tournament_id: TOURNAMENT_ID,
    stage_id: 7,
    stage_item_id: null,
    challonge_id: null,
    status: "completed",
    closeness: null,
    has_logs: false,
    result_status: "confirmed",
    result_source: "series_claim",
    result_version: 1,
    scheduled_at: null,
    started_at: new Date("2024-08-12T12:00:00Z").toISOString(),
    ended_at: new Date("2024-08-12T13:00:00Z").toISOString(),
    played_at: null,
    is_live: false,
    is_final: false,
    current_map_index: null,
    confirmed_at: null,
    matches: [],
    games: [],
    teams: [seat(1, one, scores[0]), seat(2, two, scores[1])],
    tournament,
    stage: null,
    stage_item: null,
    ...overrides
  };
}

/**
 * A finished double-elimination bracket: Beta climbs out of the lower bracket,
 * loses the grand final, and Gamma — the side it beat in the lower final — is
 * third. Round 2 holds a single match, so `stageFinalRounds` names it the Grand
 * Final exactly the way the bracket does.
 */
function playedBracket(): Encounter[] {
  return [
    makeEncounter(1, 1, ALPHA, GAMMA, [2, 0]),
    makeEncounter(2, 1, BETA, DELTA, [2, 0]),
    makeEncounter(4, -1, BETA, GAMMA, [2, 0]),
    makeEncounter(3, 2, ALPHA, BETA, [3, 2])
  ];
}

function makeRegistration(id: number, role: string, battleTag: string): Registration {
  return {
    id,
    tournament_id: TOURNAMENT_ID,
    workspace_id: WORKSPACE_ID,
    user_id: id,
    primary_handle: battleTag,
    roles: [{ role: { dimension: "player_role", role }, is_primary: true, priority: 0, top_characters: [] }],
    answers: { stream_pov: false, identity_battlenet: [battleTag] },
    form_version_id: 1,
    form_version_stale: false,
    status: "approved",
    admission: { decision: "admitted", stage: "registration", requirements: [], reasons: [] },
    submitted_at: `2024-08-0${id}T10:00:00Z`,
    reviewed_at: null
  } as Registration;
}

/**
 * The list envelope the server actually returns. `total` and `role_counts` are
 * ITS answer, not the page's — a tournament that hides its roster sends the
 * aggregate with no rows at all — so the fixture derives them from the same rows
 * the real read model would have counted.
 */
function regList(
  registrations: Registration[],
  overrides: Partial<RegistrationListResponse> = {}
): RegistrationListResponse {
  const role_counts: Record<string, number> = {};
  for (const registration of registrations) {
    const primary = registration.roles.find((role) => role.is_primary) ?? registration.roles[0];
    if (primary) {
      const code = primary.role.parent ?? primary.role.role;
      role_counts[code] = (role_counts[code] ?? 0) + 1;
    }
  }
  return {
    registrations,
    division_grids: {},
    hidden: false,
    total: registrations.length,
    role_counts,
    max_participants: null,
    ...overrides
  };
}

const GAMEMODE = { ...catalogMode(1, "Control"), image_path: "/modes/control.png" };

const MAPS: CatalogEntityRead[] = [
  catalogMap(41, GAMEMODE, { name: "Ilios", image_path: "/maps/ilios.png" }),
  catalogMap(42, GAMEMODE, { name: "Busan", image_path: "/maps/busan.png" }),
  catalogMap(43, { ...catalogMode(2, "Hybrid"), image_path: "/modes/hybrid.png" }, {
    name: "King's Row",
    image_path: "/maps/kings-row.png"
  })
];

const POOL_CONFIG: PickBanConfig = {
  id: 1,
  tournament_id: TOURNAMENT_ID,
  kind: "map",
  stage_id: null,
  round: null,
  mode: "pool",
  first_pick_rule: "higher_seed",
  first_ban_rotation: "fixed",
  ruleset: {
    version: 2,
    timer_seconds: null,
    on_timeout: "random_fill",
    phases: [
      {
        id: "main",
        name: null,
        when: {},
        pool_filter: {},
        generator: "bracket",
        steps: []
      }
    ]
  },
  item_ids: [41, 42, 43],
  slots: []
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  tournament = makeTournament("live");
  getAllEncounters.mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
  listRegistrations.mockResolvedValue(regList([]));
  getStandings.mockResolvedValue([]);
  getStages.mockResolvedValue([] as Stage[]);
  getTeams.mockResolvedValue({ results: [ALPHA, BETA, GAMMA, DELTA], total: 4, page: 1, per_page: -1 });
  getCharacterPlaytime.mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
  listPublicConfigs.mockResolvedValue({ configs: [POOL_CONFIG] });
  getAllMaps.mockResolvedValue({ results: MAPS, total: MAPS.length, page: 1, per_page: -1 });
  getTournamentStreams.mockResolvedValue({ official: [], participants: [] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

/** Let queued promise callbacks and React Query's own scheduling drain. */
async function settle(ticks = 4) {
  for (let index = 0; index < ticks; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en} timeZone={DEPLOYMENT_ZONE}>
          <TournamentOverviewPage tournamentId={TOURNAMENT_ID} slug={SLUG} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

/** Every card heading, in DOM order — the page's shape in one line. */
function headings(): string[] {
  return Array.from(container.querySelectorAll("h2")).map((node) => node.textContent?.trim() ?? "");
}

const COPY = en.tournamentDetail.overview;

describe("before the tournament starts (§3A)", () => {
  beforeEach(() => {
    tournament = makeTournament("check_in");
    listRegistrations.mockResolvedValue(
      regList([
        makeRegistration(1, "tank", "Hornet#21345"),
        makeRegistration(2, "damage", "zMize#2978"),
        makeRegistration(3, "damage", "manqa#21668"),
        makeRegistration(4, "support", "Naord#2100")
      ])
    );
  });

  it("leads with the phase timeline under the anchor the retired /schedule route points at", async () => {
    await mount();

    const phases = container.querySelector("#phases");
    expect(phases).not.toBeNull();
    // First block on the page: the phases are the content, not context.
    const cards = Array.from(container.querySelectorAll("section[aria-label] section"));
    expect(cards[0]?.id).toBe("phases");
    expect(phases?.textContent).toContain(en.common.statusBadge.check_in);
  });

  it("breaks the sign-ups down by role while the field forms, and shows the format in full", async () => {
    // Registration still open and no teams yet: the sign-ups are the story.
    tournament = makeTournament("registration", {
      teams_count: 0,
      phase_schedule: [
        { ...PHASE_SCHEDULE[0], ends_at: new Date("2099-01-01T00:00:00Z").toISOString() },
        ...PHASE_SCHEDULE.slice(1)
      ]
    });
    await mount();
    const registration = Array.from(container.querySelectorAll("section")).find((node) =>
      node.querySelector("h2")?.textContent?.includes(COPY.registration.title)
    );
    expect(registration).toBeDefined();
    const text = registration?.textContent ?? "";
    expect(text).toContain(en.common.roles.tank);
    expect(text).toContain(en.common.roles.damage);
    expect(text).toContain(en.common.roles.support);
    // Two DPS, one tank, one support — counted off the primary role.
    expect(text).toContain("2");
    // The three most recent submissions, newest first; the oldest of the four
    // (Hornet, 1 Aug) falls off the end.
    expect(text).toContain("Naord#2100");
    expect(text).toContain("manqa#21668");
    expect(text).not.toContain("Hornet#21345");

    expect(headings()).toContain(COPY.format.title);
    expect(container.textContent).toContain("Players may swap roles between matches.");
    // The roster shape reads as role glyphs (1 tank, 2 damage, 2 support), each
    // announced by its slot name — not as "1 × Tank · 2 × DPS".
    const glyphs = Array.from(container.querySelectorAll('[role="img"]')).map((node) =>
      node.getAttribute("aria-label")
    );
    expect(glyphs).toContain(en.rosterShape.slotCodes.tank);
    expect(glyphs).toContain(en.rosterShape.slotCodes.damage);
    expect(glyphs).toContain(en.rosterShape.slotCodes.support);
    expect(container.textContent).toContain("×2");
    // The old "1 × Tank" spelling is gone: no slot name in the format card.
    expect(container.textContent).not.toContain(`× ${en.rosterShape.slotCodes.tank}`);
  });

  it("shows the strongest teams instead of the sign-ups once the field is set", async () => {
    // Check-in with four teams formed: the default fixture.
    await mount();

    expect(headings()).not.toContain(COPY.registration.title);
    const teams = Array.from(container.querySelectorAll("section")).find(
      (node) => node.querySelector("h2")?.textContent === COPY.teams.title
    );
    expect(teams).toBeDefined();
    for (const name of ["Alpha", "Beta", "Gamma", "Delta"]) {
      expect(teams?.textContent).toContain(name);
    }
    const all = Array.from(teams?.querySelectorAll("a") ?? []).find(
      (node) => node.getAttribute("href") === `/tournaments/${SLUG}/teams`
    );
    expect(all?.textContent).toContain("All 4 teams");
  });

  it("previews the maps before the start and leads on to the Maps section", async () => {
    // A tournament-wide pool (no rounds to lay out) shows as one row of maps.
    await mount();

    const maps = Array.from(container.querySelectorAll("section")).find(
      (node) => node.querySelector("h2")?.textContent === COPY.maps.pool
    );
    expect(maps).toBeDefined();
    for (const name of ["Ilios", "Busan", "King's Row"]) {
      expect(maps?.textContent).toContain(name);
    }
    const all = Array.from(maps?.querySelectorAll("a") ?? []).find(
      (node) => node.getAttribute("href") === `/tournaments/${SLUG}/maps`
    );
    expect(all?.textContent).toContain("All 3 maps");
  });

  it("has no maps block for a tournament without a map pool", async () => {
    listPublicConfigs.mockResolvedValue({ configs: [] });
    await mount();

    expect(headings()).not.toContain(COPY.maps.pool);
    expect(headings()).not.toContain(COPY.maps.firstRound);
  });

  it("counts teams instead of roles when the tournament registers teams", async () => {
    tournament = makeTournament("registration", { team_formation: "registration" });
    await mount();

    const text = container.textContent ?? "";
    expect(text).toContain(COPY.registration.teams);
    // No roster read at all: team registration has no per-role shortfall.
    expect(listRegistrations).not.toHaveBeenCalled();
  });
});

describe("while it is being played (§3B)", () => {
  it("puts the live matches first", async () => {
    getAllEncounters.mockResolvedValue({
      results: [
        makeEncounter(1, 1, ALPHA, GAMMA, [1, 1], {
          status: "in_progress",
          ended_at: null,
          is_live: true
        }),
        makeEncounter(2, 1, BETA, DELTA, [2, 0])
      ],
      total: 2,
      page: 1,
      per_page: -1
    });
    await mount();

    expect(headings()).toContain(COPY.live.title);
    const live = container.querySelector("[data-live]");
    expect(live).not.toBeNull();
    expect(live?.textContent).toContain("Alpha");
    expect(live?.textContent).toContain(en.common.live);
  });

  it("falls back to the latest results when nothing is live", async () => {
    getAllEncounters.mockResolvedValue({
      results: playedBracket(),
      total: 4,
      page: 1,
      per_page: -1
    });
    await mount();

    const titles = headings();
    expect(titles).toContain(COPY.recent.title);
    expect(titles).not.toContain(COPY.live.title);
    expect(titles).not.toContain(COPY.upcoming.title);
    expect(container.querySelector("[data-live]")).toBeNull();
  });

  it("offers the upcoming matches when the organizer published a schedule", async () => {
    const soon = new Date(Date.now() + 3_600_000).toISOString();
    getAllEncounters.mockResolvedValue({
      results: [
        makeEncounter(1, 1, ALPHA, GAMMA, [2, 0]),
        makeEncounter(9, 2, ALPHA, BETA, [0, 0], {
          status: "pending",
          scheduled_at: soon,
          started_at: null,
          ended_at: null
        })
      ],
      total: 2,
      page: 1,
      per_page: -1
    });
    await mount();

    expect(headings()).toContain(COPY.upcoming.title);
  });

  // The generator draws a round long before anyone gives it a time: open
  // matches, no schedule, no results. The overview used to call that "nothing
  // published yet" while the bracket page showed the full grid.
  it("lists a drawn round that has no schedule and no results yet", async () => {
    const drawn = (id: number, round: number, one: Team, two: Team) =>
      makeEncounter(id, round, one, two, [0, 0], {
        status: "open",
        result_status: "none",
        scheduled_at: null,
        started_at: null,
        ended_at: null
      });
    getAllEncounters.mockResolvedValue({
      results: [drawn(1, 1, ALPHA, GAMMA), drawn(2, 1, BETA, DELTA)],
      total: 2,
      page: 1,
      per_page: -1
    });
    await mount();

    const titles = headings();
    expect(titles).toContain(COPY.upcoming.title);
    expect(container.textContent).not.toContain(COPY.empty.title);
  });

  it("draws the active stage as a mini bracket that links into the real one", async () => {
    getAllEncounters.mockResolvedValue({
      results: playedBracket(),
      total: 4,
      page: 1,
      per_page: -1
    });
    await mount();

    expect(headings()).toContain(COPY.bracketMini.title.replace("{stage}", "Playoff"));
    const deepLink = Array.from(container.querySelectorAll("a")).find((node) =>
      node.getAttribute("href")?.includes("match=3")
    );
    expect(deepLink?.getAttribute("href")).toBe(`/tournaments/${SLUG}/bracket?stage=7&match=3`);
  });

  it("shows a group table instead of a bracket for a round-robin stage", async () => {
    tournament = makeTournament("live", {
      stages: [makeStage({ id: 7, name: "Group A", stage_type: "round_robin" })]
    });
    getStandings.mockResolvedValue([
      {
        id: 1,
        tournament_id: TOURNAMENT_ID,
        team_id: ALPHA.id,
        stage_id: 7,
        stage_item_id: null,
        position: 1,
        overall_position: 1,
        matches: 3,
        win: 3,
        draw: 0,
        lose: 0,
        points: 6,
        buchholz: null,
        tb: null,
        score_differential: null,
        ranking_context: null,
        tb_metrics: null,
        source_rule_profile: null,
        tiebreak_order: null,
        team: ALPHA,
        tournament: null,
        stage: null,
        stage_item: null,
        matches_history: []
      }
    ]);
    getAllEncounters.mockResolvedValue({
      results: [makeEncounter(1, 1, ALPHA, GAMMA, [2, 0])],
      total: 1,
      page: 1,
      per_page: -1
    });
    await mount();

    const titles = headings();
    expect(titles).toContain(COPY.groupTable.title.replace("{stage}", "Group A"));
    expect(titles).not.toContain(COPY.bracketMini.title.replace("{stage}", "Group A"));
    expect(container.textContent).toContain("3·0·0");
  });

  it("shows the lobby tables of an FFA stage, which has neither a bracket nor duels", async () => {
    tournament = makeTournament("live", {
      stages: [makeStage({ id: 7, name: "League", stage_type: "ffa_league" })]
    });
    // The encounter list answers duels only: an FFA-only tournament has none.
    getAllEncounters.mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
    const row = (teamId: number, name: string, slot: number, position: number, points: number) => ({
      team_id: teamId,
      team_name: name,
      team_image_url: null,
      slot,
      position,
      tie_group: null,
      is_pinned: false,
      points,
      games_played: 2,
      wins: 0,
      stats: {},
      games: []
    });
    getFfaStage.mockResolvedValue([
      {
        encounter_id: 50,
        tournament_id: TOURNAMENT_ID,
        stage_id: 7,
        stage_item_id: 70,
        name: "Lobby A",
        status: "open",
        result_status: "none",
        best_of: 3,
        scheduled_at: null,
        advance_count: null,
        rules: { columns: [], placement_points: [], formula: null },
        // Out of order on purpose: the card ranks by `position`.
        rows: [row(2, "Gamma Lobby", 2, 2, 9), row(1, "Alpha Lobby", 1, 1, 14)]
      }
    ]);
    await mount();

    expect(getFfaStage).toHaveBeenCalledWith(TOURNAMENT_ID, 7);
    expect(headings()).toContain(COPY.groupTable.title.replace("{stage}", "League"));
    const text = container.textContent ?? "";
    expect(text.indexOf("Alpha Lobby")).toBeGreaterThan(-1);
    expect(text.indexOf("Alpha Lobby")).toBeLessThan(text.indexOf("Gamma Lobby"));
    const link = Array.from(container.querySelectorAll("a")).find(
      (node) => node.textContent === COPY.groupTable.open
    );
    expect(link?.getAttribute("href")).toBe(`/tournaments/${SLUG}/bracket?stage=7`);
    // No duels is not "nothing published": the lobbies are the matches.
    expect(text).not.toContain(COPY.empty.title);
  });

  it("keeps the two groups of one stage apart instead of interleaving their ranks", async () => {
    tournament = makeTournament("live", {
      stages: [makeStage({ id: 7, name: "Groups", stage_type: "round_robin" })]
    });
    const standingRow = (
      id: number,
      team: Team,
      itemId: number,
      itemName: string,
      position: number,
      record: [number, number, number],
      points: number
    ) => ({
      id,
      tournament_id: TOURNAMENT_ID,
      team_id: team.id,
      stage_id: 7,
      stage_item_id: itemId,
      position,
      overall_position: id,
      matches: record[0] + record[1] + record[2],
      win: record[0],
      draw: record[1],
      lose: record[2],
      points,
      buchholz: null,
      full_buchholz: null,
      tie_group: null,
      is_pinned: false,
      swiss_status: null,
      tb: null,
      score_differential: null,
      ranking_context: null,
      tb_metrics: null,
      source_rule_profile: null,
      tiebreak_order: null,
      team,
      tournament: null,
      stage: null,
      stage_item: { id: itemId, name: itemName },
      matches_history: []
    });
    // Both groups rank a 1 and a 2 of their own: merged into one list and
    // sorted by `position` this is the 1,1,2,2 ladder that means nothing.
    getStandings.mockResolvedValue([
      standingRow(1, ALPHA, 11, "A", 1, [3, 2, 0], 4),
      standingRow(2, GAMMA, 12, "B", 1, [3, 2, 0], 4),
      standingRow(3, BETA, 11, "A", 2, [1, 3, 1], 2.5),
      standingRow(4, DELTA, 12, "B", 2, [2, 0, 3], 2)
    ]);
    getAllEncounters.mockResolvedValue({
      results: [makeEncounter(1, 1, ALPHA, GAMMA, [2, 0])],
      total: 1,
      page: 1,
      per_page: -1
    });
    await mount();

    const tables = Array.from(container.querySelectorAll("table")).filter((node) =>
      node.querySelector("caption")?.textContent?.startsWith("Group")
    );
    expect(tables.map((node) => node.querySelector("caption")?.textContent)).toEqual([
      "Group A",
      "Group B"
    ]);
    expect(
      tables.map((node) =>
        Array.from(node.querySelectorAll("tbody tr")).map(
          (cells) => cells.querySelectorAll("td")[1]?.textContent
        )
      )
    ).toEqual([
      ["Alpha", "Beta"],
      ["Gamma", "Delta"]
    ]);
    // The record carries draws, and every points cell shares one decimal.
    expect(tables[0].querySelectorAll("tbody td")[2]?.textContent).toBe("3·2·0");
    expect(
      tables.flatMap((node) =>
        Array.from(node.querySelectorAll("tbody tr")).map(
          (row) => row.querySelectorAll("td")[3]?.textContent
        )
      )
    ).toEqual(["4.0", "2.5", "4.0", "2.0"]);
  });
});

describe("once it is over (§3C)", () => {
  beforeEach(() => {
    tournament = makeTournament("completed", {
      stages: [makeStage({ id: 7, is_active: false, is_completed: true })]
    });
    getAllEncounters.mockResolvedValue({
      results: playedBracket(),
      total: 4,
      page: 1,
      per_page: -1
    });
  });

  it("opens on the result, with third place off the lower-bracket final", async () => {
    await mount();

    expect(headings()).toContain(COPY.result.title);
    const podium = container.querySelector(`[aria-label="${en.tournamentDetail.podium.label}"]`);
    expect(podium).not.toBeNull();
    const text = podium?.textContent ?? "";
    expect(text).toContain("Alpha");
    expect(text).toContain("Beta");
    expect(text).toContain("Gamma");
    expect(text).not.toContain("Delta");
    // The champion's roster comes off the teams read, the finalists' notes off
    // the bracket: "2–3 in the final", "Eliminated in LB Final".
    expect(text).toContain("yaLucky · Kenny");
    expect(text).toContain(COPY.result.finalScore.replace("{score}", "2–3"));
    expect(text).toContain(COPY.result.exitedIn.replace("{round}", "LB Final"));
  });

  it("counts the tournament up and links onward to the statistics", async () => {
    getCharacterPlaytime.mockResolvedValue({
      results: [{ entity: { id: 1, name: "Kiriko", image_path: "/heroes/kiriko.png", attrs: {} }, playtime: 0.091 }],
      total: 1,
      page: 1,
      per_page: -1
    });
    await mount();

    const titles = headings();
    expect(titles).toContain(COPY.numbers.title);
    expect(titles).toContain(COPY.heroes.title);
    expect(container.textContent).toContain("Kiriko");
    // 4 matches over two calendar days. Teams and players are the header's
    // stamps — the card used to repeat both one screen below them.
    const numbers = Array.from(container.querySelectorAll("section")).find((node) =>
      node.querySelector("h2")?.textContent?.includes(COPY.numbers.title)
    );
    expect(numbers?.textContent).toContain(COPY.numbers.matches);
    expect(numbers?.textContent).toContain(COPY.numbers.days);
    expect(numbers?.textContent).toContain("4");
    expect(numbers?.textContent).toContain("2");
  });

  it("drops to third-by-standings when the tournament never had a bracket", async () => {
    tournament = makeTournament("completed", {
      stages: [makeStage({ id: 7, name: "League", stage_type: "round_robin", is_completed: true })]
    });
    getAllEncounters.mockResolvedValue({
      results: [makeEncounter(1, 1, ALPHA, GAMMA, [2, 0])],
      total: 1,
      page: 1,
      per_page: -1
    });
    getStandings.mockResolvedValue(
      [ALPHA, BETA, GAMMA].map((team, index) => ({
        id: index + 1,
        tournament_id: TOURNAMENT_ID,
        team_id: team.id,
        stage_id: 7,
        stage_item_id: null,
        position: index + 1,
        overall_position: index + 1,
        matches: 3,
        win: 3 - index,
        draw: 0,
        lose: index,
        points: 6 - index * 2,
        buchholz: null,
        tb: null,
        score_differential: null,
        ranking_context: null,
        tb_metrics: null,
        source_rule_profile: null,
        tiebreak_order: null,
        team,
        tournament: null,
        stage: null,
        stage_item: null,
        matches_history: []
      }))
    );
    await mount();

    const podium = container.querySelector(`[aria-label="${en.tournamentDetail.podium.label}"]`);
    expect(podium?.textContent).toContain("Gamma");
    expect(podium?.textContent).toContain("Alpha");
    expect(podium?.textContent).toContain("Beta");
    expect(podium?.textContent).toContain(en.tournamentDetail.podium.place3);
  });
});

/**
 * The header carries the tournament's STATE and its actions; what the
 * tournament IS, and where the organizer's channels are, live here — in every
 * branch, because the header no longer holds either. Before this the format
 * card existed only before the start, and the links only in the header's action
 * row, which put translucent chips on top of the cover banner.
 */
describe("the reference tail", () => {
  const DISCORD: TournamentLink = {
    id: 1,
    tournament_id: TOURNAMENT_ID,
    kind: "discord",
    label: null,
    url: "https://discord.gg/anak",
    sort_order: 0,
    is_active: true
  };

  for (const status of ["check_in", "live", "completed"] as const) {
    it(`states the format, the full description and the links in the ${status} branch`, async () => {
      tournament = makeTournament(status, { links: [DISCORD] });
      getAllEncounters.mockResolvedValue({
        results: playedBracket(),
        total: 4,
        page: 1,
        per_page: -1
      });
      await mount();

      const titles = headings();
      expect(titles).toContain(COPY.format.title);
      expect(titles).toContain(en.tournamentDetail.links.heading);
      // The whole description, not the header's one clamped line.
      expect(container.textContent).toContain("Players may swap roles between matches.");
      expect(
        Array.from(container.querySelectorAll("a")).some(
          (node) => node.getAttribute("href") === DISCORD.url
        )
      ).toBe(true);
    });
  }

  it("names each stage once with its type, in play order, numbered by phase", async () => {
    tournament = makeTournament("live", {
      stages: [
        makeStage({ id: 7, name: "Playoffs", stage_type: "double_elimination", order: 1 }),
        makeStage({ id: 6, name: "Groups", stage_type: "round_robin", order: 0 })
      ]
    });
    await mount();

    const card = Array.from(container.querySelectorAll("section")).find((node) =>
      node.querySelector("h2")?.textContent?.includes(COPY.format.title)
    );
    const items = Array.from(card?.querySelectorAll("ol > li") ?? []);
    const steps = items.map((node) => node.textContent ?? "");
    // The type is the chip that opens its explanation, beside the organizer's name.
    const chips = (node: Element) =>
      Array.from(node.querySelectorAll('button[aria-haspopup="dialog"]')).map((chip) => chip.textContent);
    expect(steps).toHaveLength(2);
    expect(steps[0]).toContain("Groups");
    expect(chips(items[0])).toEqual([COPY.format.types.round_robin.name]);
    expect(steps[1]).toContain("Playoffs");
    expect(chips(items[1])).toEqual([COPY.format.types.double_elimination.name]);
    // Each name once: the stage list is not repeated under a second label.
    expect((card?.textContent ?? "").split("Playoffs").length - 1).toBe(1);
  });

  it("states what each stage's regulation says a reader needs to follow it", async () => {
    tournament = makeTournament("live", {
      stages: [
        makeStage({
          id: 6,
          name: "Groups",
          stage_type: "swiss",
          order: 0,
          max_rounds: 5,
          advance_count: 8,
          swiss_qualify_wins: 3,
          swiss_eliminate_losses: 3
        }),
        makeStage({ id: 7, name: "Playoffs", stage_type: "double_elimination", order: 1, advance_count: 2 })
      ]
    });
    await mount();

    const steps = Array.from(
      Array.from(container.querySelectorAll("section"))
        .find((node) => node.querySelector("h2")?.textContent?.includes(COPY.format.title))
        ?.querySelectorAll("ol > li") ?? []
    ).map((node) => node.textContent ?? "");
    expect(steps[0]).toContain("5 rounds");
    expect(steps[0]).toContain("Through at 3 wins");
    expect(steps[0]).toContain("Out at 3 losses");
    expect(steps[0]).toContain("Top 8 advance");
    // The last stage advances nobody, whatever its `advance_count` says.
    expect(steps[1]).not.toContain("advance");
    expect(steps[1]).toContain(COPY.format.grandFinalNoReset);
  });

  it("shrinks the type chip to its icon when the organizer named the stage after it", async () => {
    // "Swiss system · Swiss system" is the same words twice; the label exists
    // for names that do NOT state the format. The chip still explains it.
    tournament = makeTournament("live", {
      stages: [
        makeStage({ id: 6, name: "Swiss system", stage_type: "swiss", order: 0 }),
        makeStage({ id: 7, name: " double elimination ", stage_type: "double_elimination", order: 1 })
      ]
    });
    await mount();

    const card = Array.from(container.querySelectorAll("section")).find((node) =>
      node.querySelector("h2")?.textContent?.includes(COPY.format.title)
    );
    const chips = Array.from(card?.querySelectorAll('button[aria-haspopup="dialog"]') ?? []);

    expect(chips.map((chip) => [chip.textContent, chip.getAttribute("aria-label")])).toEqual([
      ["", COPY.format.types.swiss.name],
      ["", COPY.format.types.double_elimination.name]
    ]);
  });

  it("keeps stages that share a phase order in one step, and the next phase in the next", async () => {
    tournament = makeTournament("live", {
      stages: [
        makeStage({ id: 1, name: "Groups Low", stage_type: "round_robin", order: 1 }),
        makeStage({ id: 2, name: "Groups High", stage_type: "round_robin", order: 1 }),
        makeStage({ id: 3, name: "Playoff Low", stage_type: "double_elimination", order: 2 }),
        makeStage({ id: 4, name: "Playoff High", stage_type: "double_elimination", order: 2 })
      ]
    });
    await mount();

    const card = Array.from(container.querySelectorAll("section")).find((node) =>
      node.querySelector("h2")?.textContent?.includes(COPY.format.title)
    );
    const steps = Array.from(card?.querySelectorAll("ol > li") ?? []).map(
      (node) => node.textContent ?? ""
    );
    expect(steps).toHaveLength(2);
    expect(steps[0]).toContain("Groups Low");
    expect(steps[0]).toContain("Groups High");
    expect(steps[1]).toContain("Playoff Low");
    expect(steps[1]).toContain("Playoff High");
  });

  it("gives the links their own aside before the start, with no map pool to share it", async () => {
    // The registration branch's aside is optional — it used to appear only for
    // a map pool, so links alone would have had nowhere to render.
    tournament = makeTournament("check_in", { links: [DISCORD] });
    listPublicConfigs.mockResolvedValue({ configs: [] });
    await mount();

    expect(headings()).toContain(en.tournamentDetail.links.heading);
    expect(container.querySelector("#map-pool")).toBeNull();
  });

  it("draws no links heading when the only link is the official broadcast", async () => {
    // `TournamentLinkChips` renders nothing for a stream — the dock owns it —
    // so a card around it would be a heading over an empty row.
    tournament = makeTournament("live", {
      links: [{ ...DISCORD, kind: "stream", url: "https://twitch.tv/cast" }]
    });
    await mount();

    expect(headings()).not.toContain(en.tournamentDetail.links.heading);
  });
});
