// @vitest-environment happy-dom
//
// The overview is the tournament's landing page and it is not one screen: it is
// one composition per phase, chosen by `status`. What is pinned here is exactly
// the part a reader would notice if a branch regressed:
//
//  1. before the start, the field is counted by PRIMARY role against the
//     roster shape, and the schedule keeps `#phases` (the retired `/schedule`
//     route 301s to that anchor);
//  2. during the draft, the board says who is on the clock and what was picked;
//  3. while play runs, live matches come first and a group table is the
//     OFFICIAL standings (tiebreakers included), with form and map difference
//     read off the finished series;
//  4. a finished tournament opens on its result, and the client-only insights
//     (stats, bans, draft) add cards when they answer and leave none behind
//     when they fail;
//  5. every branch closes on the same reference card: description, format,
//     links.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { catalogEntity } from "@/test/catalog";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { DraftBoard, DraftPick, DraftPlayer, DraftTeam } from "@/types/draft.types";
import type { Encounter, EncounterTeam } from "@/types/encounter.types";
import type { Registration, RegistrationListResponse } from "@/types/registration.types";
import type { TournamentLink } from "@/types/stream.types";
import type { Team } from "@/types/team.types";
import type {
  PickBanOutcomesResponse,
  Standings,
  StageSummary,
  Tournament,
  TournamentStatus
} from "@/types/tournament.types";

import TournamentOverviewPage from "./TournamentOverviewPage";

vi.mock(
  "@/services/discipline.service",
  async () => (await import("@/test/discipline-metadata")).disciplineServiceMock
);

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
const getPlayerStats = vi.fn();
const getPickBanOutcomes = vi.fn();
const getTournamentBoard = vi.fn();
const getTeams = vi.fn();
const getCharacterPlaytime = vi.fn();
const listCatalog = vi.fn();
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
    getPlayerStats: (...args: unknown[]) => getPlayerStats(...args),
    getPickBanOutcomes: (...args: unknown[]) => getPickBanOutcomes(...args)
  }
}));
vi.mock("@/services/draft.service", () => ({
  default: { getTournamentBoard: (...args: unknown[]) => getTournamentBoard(...args) }
}));
vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));
vi.mock("@/services/statistics.service", () => ({
  default: { getCharacterPlaytime: (...args: unknown[]) => getCharacterPlaytime(...args) }
}));
vi.mock("@/services/catalog.service", () => ({
  default: { list: (...args: unknown[]) => listCatalog(...args) }
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

function makeRegistration(
  id: number,
  role: string,
  battleTag: string,
  overrides: Partial<Registration> = {}
): Registration {
  return {
    id,
    tournament_id: TOURNAMENT_ID,
    workspace_id: WORKSPACE_ID,
    user_id: id,
    primary_handle: battleTag,
    roles: [
      {
        role: { dimension: "player_role", role },
        is_primary: true,
        priority: 0,
        top_characters: []
      }
    ],
    answers: { stream_pov: false, identity_battlenet: [battleTag] },
    form_version_id: 1,
    form_version_stale: false,
    status: "approved",
    admission: { decision: "admitted", stage: "registration", requirements: [], reasons: [] },
    submitted_at: `2024-08-0${id}T10:00:00Z`,
    reviewed_at: null,
    ...overrides
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

/** One official standings row; `record` is win·draw·loss. */
function makeStanding(
  id: number,
  team: Team,
  position: number,
  points: number,
  record: [number, number, number],
  group: { id: number; name: string } | null = null
): Standings {
  return {
    id,
    tournament_id: TOURNAMENT_ID,
    team_id: team.id,
    stage_id: 7,
    stage_item_id: group?.id ?? null,
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
    stage_item: group,
    matches_history: []
  } as Standings;
}

const DRAFT_SESSION_ID = 1;

function draftTeam(
  id: number,
  captainUserId: number,
  name: string,
  position: number,
  exportedTeamId: number
): DraftTeam {
  return {
    id,
    session_id: DRAFT_SESSION_ID,
    captain_user_id: captainUserId,
    captain_auth_user_id: null,
    name,
    draft_position: position,
    exported_team_id: exportedTeamId
  };
}

function draftPlayer(id: number, name: string, role: string, isCaptain = false): DraftPlayer {
  return {
    id,
    session_id: DRAFT_SESSION_ID,
    registration_id: id,
    user_id: 500 + id,
    identity: null,
    player_name: name,
    primary_role: { dimension: "player_role", role },
    is_flex: false,
    effective_rank: 3000 + id * 100,
    status: "available",
    is_captain: isCaptain,
    drafted_by_team_id: null,
    captain_role: isCaptain ? { dimension: "player_role", role } : null,
    secondary_roles: [],
    role_ranks: {},
    role_sources: {},
    role_top_characters: {},
    role_sub_roles: {},
    notes: null,
    custom_fields: [],
    version: 1
  };
}

function draftPick(
  overall: number,
  round: number,
  draftTeamId: number,
  role: string,
  pickedPlayerId: number | null,
  autopick = false
): DraftPick {
  return {
    id: overall,
    session_id: DRAFT_SESSION_ID,
    overall_no: overall,
    round_no: round,
    pick_in_round: ((overall - 1) % 2) + 1,
    draft_team_id: draftTeamId,
    target_role: { dimension: "player_role", role },
    target_rank_value: null,
    status: pickedPlayerId === null ? "upcoming" : autopick ? "autopicked" : "completed",
    picked_player_id: pickedPlayerId,
    picked_by_user_id: null,
    is_autopick: autopick,
    is_admin_override: false,
    clock_started_at: `2024-08-12T10:0${overall}:00Z`,
    clock_expires_at: null,
    overtime_started_at: null,
    version: 1
  };
}

/**
 * Two captains, two rounds: Alice took Carol, Bob was autopicked Dave, and Bob
 * is on the clock for a support. Erin and Finn are what is left in the pool.
 */
function liveDraftBoard(): DraftBoard {
  const onClock = draftPick(3, 2, 2, "support", null);
  return {
    session: {
      id: DRAFT_SESSION_ID,
      tournament_id: TOURNAMENT_ID,
      custom_game_id: null,
      lobby_index: null,
      workspace_id: WORKSPACE_ID,
      discipline: "overwatch",
      status: "live",
      blocked_reason: null,
      format: "snake",
      rounds: 2,
      pick_time_seconds: 60,
      overtime_seconds: 0,
      roster_shape: tournament.roster_shape as DraftBoard["session"]["roster_shape"],
      current_pick_id: onClock.id,
      pool_source: "manual",
      source_balance_id: null,
      autopick_strategy: "best_fit",
      allow_admin_override: false,
      exported_at: null,
      export_status: null,
      settings_json: {},
      version: 1,
      created_at: null
    },
    teams: [
      draftTeam(1, 501, "Team Alice", 1, ALPHA.id),
      draftTeam(2, 502, "Team Bob", 2, BETA.id)
    ],
    picks: [
      draftPick(1, 1, 1, "damage", 3),
      draftPick(2, 1, 2, "damage", 4, true),
      onClock,
      draftPick(4, 2, 1, "support", null)
    ],
    players: [
      draftPlayer(1, "Alice", "tank", true),
      draftPlayer(2, "Bob", "tank", true),
      draftPlayer(3, "Carol", "damage"),
      draftPlayer(4, "Dave", "damage"),
      draftPlayer(5, "Erin", "support"),
      draftPlayer(6, "Finn", "support")
    ],
    current_pick: onClock,
    last_event_id: null
  };
}

const HEROES: CatalogEntityRead[] = [
  catalogEntity({ id: 1, name: "Kiriko", slug: "kiriko" }),
  catalogEntity({ id: 2, name: "Ana", slug: "ana" })
];

const NO_BANS: PickBanOutcomesResponse = { hero_bans: [], map_outcomes: [] };

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  tournament = makeTournament("live");
  getAllEncounters.mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
  listRegistrations.mockResolvedValue(regList([]));
  getStandings.mockResolvedValue([]);
  getPlayerStats.mockResolvedValue({ players: [], total_players: 0 });
  getPickBanOutcomes.mockResolvedValue(NO_BANS);
  getTournamentBoard.mockResolvedValue(null);
  getTeams.mockResolvedValue({
    results: [ALPHA, BETA, GAMMA, DELTA],
    total: 4,
    page: 1,
    per_page: -1
  });
  getCharacterPlaytime.mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
  listCatalog.mockImplementation(async (_discipline: string, kind: string) => {
    const results = kind === "character" ? HEROES : [];
    return { results, total: results.length, page: 1, per_page: -1 };
  });
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

/**
 * Every heading, in DOM order — the page's shape in one line. Cards title with
 * `h2`; the blocks inside the reference card (about, format, links) with `h3`.
 */
function headings(): string[] {
  return Array.from(container.querySelectorAll("h2, h3")).map(
    (node) => node.textContent?.trim() ?? ""
  );
}

/** The card (or the reference card's block) under the heading `title`. */
function card(title: string): HTMLElement | null {
  const heading = Array.from(container.querySelectorAll("h2, h3")).find(
    (node) => node.textContent?.trim() === title
  );
  return heading?.closest("section") ?? null;
}

/** Each body row of a table as its cells' text. */
function rowsOf(table: Element): string[][] {
  return Array.from(table.querySelectorAll("tbody tr")).map((row) =>
    Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent?.trim() ?? "")
  );
}

function encounterList(results: Encounter[]) {
  return { results, total: results.length, page: 1, per_page: -1 };
}

const COPY = en.tournamentDetail.overview;

describe("before the tournament starts", () => {
  it("counts the field by primary role against the roster shape", async () => {
    tournament = makeTournament("registration");
    listRegistrations.mockResolvedValue(
      regList([
        makeRegistration(1, "tank", "Hornet#21345"),
        makeRegistration(2, "tank", "Mirro#2211"),
        makeRegistration(3, "damage", "zMize#2978"),
        makeRegistration(4, "damage", "manqa#21668"),
        makeRegistration(5, "damage", "Kenny#1337"),
        makeRegistration(6, "support", "Naord#2100"),
        // Lists tank first but plays support: the PRIMARY role is what counts.
        makeRegistration(7, "support", "Lina#4242", {
          roles: [
            {
              role: { dimension: "player_role", role: "tank" },
              is_primary: false,
              priority: 1,
              top_characters: []
            },
            {
              role: { dimension: "player_role", role: "support" },
              is_primary: true,
              priority: 0,
              top_characters: []
            }
          ]
        }),
        // Out of the field: a withdrawn application fills no slot.
        makeRegistration(8, "support", "Ghost#0001", { status: "withdrawn" })
      ])
    );
    await mount();

    const field = card(COPY.field.title);
    expect(field).not.toBeNull();
    // Slots 1 tank / 2 damage / 2 support: two tanks fill two teams, three
    // damage and two supports one each — one complete roster so far.
    const roles = Array.from(field?.querySelectorAll("ul > li") ?? []).map(
      (row) => row.textContent
    );
    expect(roles).toEqual([
      `${en.tournamentDetail.roles.tank}enough for 2 teams2`,
      `${en.tournamentDetail.roles.damage}enough for 1 team3`,
      `${en.tournamentDetail.roles.support}enough for 1 team2`
    ]);
    const text = field?.textContent ?? "";
    expect(text).toContain(`${COPY.field.teams}1`);
    expect(text).toContain("each needs 1 tank, 2 damage, 2 supports");
    // The second roster is short one damage and two supports; tanks are covered.
    expect(text).toContain(
      `Team 2 still needs: ${en.tournamentDetail.roles.damage} — 1, ${en.tournamentDetail.roles.support} — 2.`
    );
  });

  it("counts a team-registration field in teams, with no role shape to fill", async () => {
    tournament = makeTournament("registration", { team_formation: "registration" });
    const team = (id: number) =>
      ({
        id,
        name: `Team ${id}`,
        status: "complete",
        slot_code: "dps",
        is_substitute: false,
        is_captain: false
      }) as const;
    listRegistrations.mockResolvedValue(
      regList([
        makeRegistration(1, "tank", "Hornet#21345", { team: team(10) }),
        makeRegistration(2, "damage", "zMize#2978", { team: team(10) }),
        makeRegistration(3, "support", "Naord#2100", { team: team(11) }),
        // A withdrawn player's team is not in the field.
        makeRegistration(4, "support", "Ghost#0001", { team: team(12), status: "withdrawn" })
      ])
    );
    await mount();

    expect(card(COPY.field.title)).toBeNull();
    const numbers = card(COPY.regNumbers.title)?.textContent ?? "";
    expect(numbers).toContain(`${COPY.regNumbers.applications}3`);
    expect(numbers).toContain(`${COPY.regNumbers.teams}2`);
  });

  it("keeps the schedule under the anchor the retired /schedule route points at", async () => {
    tournament = makeTournament("check_in");
    await mount();

    const phases = container.querySelector("#phases");
    expect(phases).not.toBeNull();
    expect(phases?.textContent).toContain(en.common.statusBadge.check_in);
  });
});

describe("while the captains draft", () => {
  beforeEach(() => {
    tournament = makeTournament("draft");
    getTournamentBoard.mockResolvedValue(liveDraftBoard());
  });

  it("names the captain on the clock and the picks made so far, newest first", async () => {
    await mount();

    const progress = card(COPY.draft.live);
    expect(progress).not.toBeNull();
    const text = progress?.textContent ?? "";
    expect(text).toContain(`${COPY.draft.onClock}Bob`);
    expect(text).toContain(COPY.draft.needs.replace("{role}", en.common.roles.support));
    expect(progress?.querySelector('[aria-label="2 of 4 picks made"]')).not.toBeNull();

    const picks = Array.from(progress?.querySelectorAll("ol > li") ?? []).map(
      (row) => row.textContent ?? ""
    );
    expect(picks).toHaveLength(2);
    expect(picks[0]).toContain("#2");
    expect(picks[0]).toContain("Dave");
    expect(picks[0]).toContain(COPY.draft.teamOf.replace("{captain}", "Bob"));
    expect(picks[0]).toContain(COPY.draft.autopick);
    expect(picks[1]).toContain("#1");
    expect(picks[1]).toContain("Carol");
    expect(picks[1]).toContain(COPY.draft.teamOf.replace("{captain}", "Alice"));
    expect(picks[1]).not.toContain(COPY.draft.autopick);

    // The picked players have left the pool; the two supports are what remains.
    const pool = card(COPY.draft.pool)?.textContent ?? "";
    expect(pool).toContain("Erin");
    expect(pool).toContain("Finn");
    expect(pool).not.toContain("Carol");
    expect(pool).not.toContain("Dave");
  });

  it("falls back to the reference alone when there is no draft board yet", async () => {
    getTournamentBoard.mockResolvedValue(null);
    await mount();

    expect(headings()).not.toContain(COPY.draft.live);
    expect(headings()).toContain(COPY.reference.title);
  });
});

describe("while it is being played", () => {
  it("puts the live matches first", async () => {
    getAllEncounters.mockResolvedValue(
      encounterList([
        makeEncounter(1, 1, ALPHA, GAMMA, [1, 1], {
          status: "in_progress",
          ended_at: null,
          is_live: true
        }),
        makeEncounter(2, 1, BETA, DELTA, [2, 0])
      ])
    );
    await mount();

    expect(headings()).toContain(COPY.live.now);
    const live = container.querySelector("[data-live]");
    expect(live).not.toBeNull();
    expect(live?.textContent).toContain("Alpha");
    expect(live?.textContent).toContain(en.common.live);
  });

  it("shows the latest results and no live block when nothing is on", async () => {
    getAllEncounters.mockResolvedValue(encounterList(playedBracket()));
    await mount();

    const titles = headings();
    expect(titles).toContain(COPY.live.recent);
    expect(titles).not.toContain(COPY.live.now);
    expect(container.querySelector("[data-live]")).toBeNull();
  });

  it("draws the active stage as a mini bracket that links into the real one", async () => {
    getAllEncounters.mockResolvedValue(encounterList(playedBracket()));
    await mount();

    expect(headings()).toContain(COPY.bracketMini.title.replace("{stage}", "Playoff"));
    const deepLink = Array.from(container.querySelectorAll("a")).find((node) =>
      node.getAttribute("href")?.includes("match=3")
    );
    expect(deepLink?.getAttribute("href")).toBe(`/tournaments/${SLUG}/bracket?stage=7&match=3`);
  });

  it("ranks a group by its official standings, with form and map difference off the played series", async () => {
    tournament = makeTournament("live", {
      stages: [makeStage({ id: 7, name: "Group A", stage_type: "round_robin" })]
    });
    // Alpha won both of its series, Beta one of two — yet the official table,
    // tiebreakers and all, puts Beta first. The table is the server's answer.
    getStandings.mockResolvedValue([
      makeStanding(1, BETA, 1, 9, [1, 0, 1]),
      makeStanding(2, ALPHA, 2, 7, [2, 0, 0]),
      makeStanding(3, GAMMA, 3, 0, [0, 0, 2])
    ]);
    getAllEncounters.mockResolvedValue(
      encounterList([
        makeEncounter(1, 1, ALPHA, BETA, [2, 0]),
        makeEncounter(2, 2, ALPHA, GAMMA, [2, 1]),
        makeEncounter(3, 3, BETA, GAMMA, [2, 0])
      ])
    );
    await mount();

    const titles = headings();
    expect(titles).toContain(COPY.groupTable.title.replace("{stage}", "Group A"));
    expect(titles).not.toContain(COPY.bracketMini.title.replace("{stage}", "Group A"));
    const tables = Array.from(container.querySelectorAll("table"));
    expect(tables).toHaveLength(1);
    // Place, team, form (oldest first), map difference, points.
    expect(rowsOf(tables[0])).toEqual([
      ["1", "Beta", "LW", "0", "9"],
      ["2", "Alpha", "WW", "+3", "7"],
      ["3", "Gamma", "LL", "−3", "0"]
    ]);
  });

  it("keeps the two groups of one stage apart instead of interleaving their ranks", async () => {
    tournament = makeTournament("live", {
      stages: [makeStage({ id: 7, name: "Groups", stage_type: "round_robin" })]
    });
    // Both groups rank a 1 and a 2 of their own: merged into one list and
    // sorted by `position` this is the 1,1,2,2 ladder that means nothing.
    const groupA = { id: 11, name: "A" };
    const groupB = { id: 12, name: "B" };
    getStandings.mockResolvedValue([
      makeStanding(1, ALPHA, 1, 4, [3, 2, 0], groupA),
      makeStanding(2, GAMMA, 1, 4, [3, 2, 0], groupB),
      makeStanding(3, BETA, 2, 2.5, [1, 3, 1], groupA),
      makeStanding(4, DELTA, 2, 2, [2, 0, 3], groupB)
    ]);
    getAllEncounters.mockResolvedValue(encounterList([makeEncounter(1, 1, ALPHA, GAMMA, [2, 0])]));
    await mount();

    const tables = Array.from(container.querySelectorAll("table"));
    expect(tables.map((node) => node.querySelector("caption")?.textContent)).toEqual([
      "Group A",
      "Group B"
    ]);
    expect(tables.map((node) => rowsOf(node).map((cells) => cells[1]))).toEqual([
      ["Alpha", "Beta"],
      ["Gamma", "Delta"]
    ]);
    // Every points cell shares one decimal as soon as one carries a half.
    expect(tables.flatMap((node) => rowsOf(node).map((cells) => cells[4]))).toEqual([
      "4.0",
      "2.5",
      "4.0",
      "2.0"
    ]);
  });

  it("shows the lobby tables of an FFA stage, which has neither a bracket nor duels", async () => {
    tournament = makeTournament("live", {
      stages: [makeStage({ id: 7, name: "League", stage_type: "ffa_league" })]
    });
    // The encounter list answers duels only: an FFA-only tournament has none.
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

    expect(headings()).toContain(COPY.groupTable.title.replace("{stage}", "League"));
    const text = container.textContent ?? "";
    expect(text.indexOf("Alpha Lobby")).toBeGreaterThan(-1);
    expect(text.indexOf("Alpha Lobby")).toBeLessThan(text.indexOf("Gamma Lobby"));
    const link = Array.from(container.querySelectorAll("a")).find(
      (node) => node.textContent === COPY.groupTable.open
    );
    expect(link?.getAttribute("href")).toBe(`/tournaments/${SLUG}/bracket?stage=7`);
  });
});

describe("once it is over", () => {
  beforeEach(() => {
    tournament = makeTournament("completed", {
      stages: [makeStage({ id: 7, is_active: false, is_completed: true })]
    });
    getAllEncounters.mockResolvedValue(encounterList(playedBracket()));
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

  it("ranks the most banned heroes once the pick-ban outcomes answer", async () => {
    getPickBanOutcomes.mockResolvedValue({
      hero_bans: [
        { encounter_id: 1, hero_id: 2, first_map: true, target_player_id: null },
        { encounter_id: 1, hero_id: 1, first_map: true, target_player_id: null },
        { encounter_id: 3, hero_id: 1, first_map: true, target_player_id: null },
        { encounter_id: 3, hero_id: 1, first_map: false, target_player_id: null }
      ],
      map_outcomes: []
    } satisfies PickBanOutcomesResponse);
    await mount();

    expect(
      container.querySelector(`[aria-label="${en.tournamentDetail.podium.label}"]`)
    ).not.toBeNull();
    const bans = Array.from(card(COPY.bans.title)?.querySelectorAll("ol > li") ?? []).map(
      (row) => row.textContent ?? ""
    );
    expect(bans).toHaveLength(2);
    expect(bans[0]).toContain("Kiriko");
    expect(bans[0]).toMatch(/3$/);
    expect(bans[1]).toContain("Ana");
    expect(bans[1]).toMatch(/1$/);
    // The numbers count the same bans: four, over two series.
    const numbers = card(COPY.numbers.title)?.textContent ?? "";
    expect(numbers).toContain(`${COPY.numbers.heroBans}4in 2 series`);
  });

  it("draws no bans card when the series struck only maps", async () => {
    getPickBanOutcomes.mockResolvedValue({
      hero_bans: [],
      map_outcomes: [{ encounter_id: 1, map_id: 4, picked: false }]
    } satisfies PickBanOutcomesResponse);
    await mount();

    expect(headings()).toContain(COPY.result.title);
    expect(card(COPY.bans.title)).toBeNull();
  });

  it("still draws the result when every insights read fails", async () => {
    getPlayerStats.mockRejectedValue(new Error("stats down"));
    getPickBanOutcomes.mockRejectedValue(new Error("bans down"));
    getTournamentBoard.mockRejectedValue(new Error("draft down"));
    await mount();

    expect(
      container.querySelector(`[aria-label="${en.tournamentDetail.podium.label}"]`)
    ).not.toBeNull();
    const titles = headings();
    expect(titles).toContain(COPY.numbers.title);
    expect(titles).not.toContain(COPY.bans.title);
    expect(titles).not.toContain(COPY.leaders.title);
    expect(titles).not.toContain(COPY.draftCard.title);
    expect(card(COPY.numbers.title)?.textContent).not.toContain(COPY.numbers.heroBans);
  });

  it("counts the tournament up and lists its most played heroes", async () => {
    getCharacterPlaytime.mockResolvedValue({
      results: [
        {
          entity: { id: 1, name: "Kiriko", image_path: "/heroes/kiriko.png", attrs: {} },
          playtime: 0.091
        }
      ],
      total: 1,
      page: 1,
      per_page: -1
    });
    await mount();

    expect(card(COPY.heroes.title)?.textContent).toContain("Kiriko");
    // 4 matches over two calendar days.
    const numbers = card(COPY.numbers.title)?.textContent ?? "";
    expect(numbers).toContain(`${COPY.numbers.matches}4`);
    expect(numbers).toContain(`${COPY.numbers.days}2`);
  });

  it("drops to third-by-standings when the tournament never had a bracket", async () => {
    tournament = makeTournament("completed", {
      stages: [makeStage({ id: 7, name: "League", stage_type: "round_robin", is_completed: true })]
    });
    getAllEncounters.mockResolvedValue(encounterList([makeEncounter(1, 1, ALPHA, GAMMA, [2, 0])]));
    getStandings.mockResolvedValue([
      makeStanding(1, ALPHA, 1, 6, [3, 0, 0]),
      makeStanding(2, BETA, 2, 4, [2, 0, 1]),
      makeStanding(3, GAMMA, 3, 2, [1, 0, 2])
    ]);
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
 * tournament IS, and where the organizer's channels are, live in the reference
 * card that closes every branch.
 */
describe("the reference card", () => {
  const DISCORD: TournamentLink = {
    id: 1,
    tournament_id: TOURNAMENT_ID,
    kind: "discord",
    label: null,
    url: "https://discord.gg/anak",
    sort_order: 0,
    is_active: true
  };

  for (const status of ["check_in", "draft", "live", "completed"] as const) {
    it(`states the format, the full description and the links in the ${status} branch`, async () => {
      tournament = makeTournament(status, { links: [DISCORD] });
      getAllEncounters.mockResolvedValue(encounterList(playedBracket()));
      await mount();

      const reference = card(COPY.reference.title);
      expect(reference).not.toBeNull();
      const titles = Array.from(reference?.querySelectorAll("h3") ?? []).map(
        (node) => node.textContent
      );
      expect(titles).toContain(COPY.format.title);
      expect(titles).toContain(en.tournamentDetail.links.heading);
      // The whole description, not the header's one clamped line.
      expect(reference?.textContent).toContain("Players may swap roles between matches.");
      expect(
        Array.from(reference?.querySelectorAll("a") ?? []).some(
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

    const format = card(COPY.format.title);
    const items = Array.from(format?.querySelectorAll("ol > li") ?? []);
    const steps = items.map((node) => node.textContent ?? "");
    // The type is the chip that opens its explanation, beside the organizer's name.
    const chips = (node: Element) =>
      Array.from(node.querySelectorAll('button[aria-haspopup="dialog"]')).map(
        (chip) => chip.textContent
      );
    expect(steps).toHaveLength(2);
    expect(steps[0]).toContain("Groups");
    expect(chips(items[0])).toEqual([COPY.format.types.round_robin.name]);
    expect(steps[1]).toContain("Playoffs");
    expect(chips(items[1])).toEqual([COPY.format.types.double_elimination.name]);
    // Each name once: the stage list is not repeated under a second label.
    expect((format?.textContent ?? "").split("Playoffs").length - 1).toBe(1);
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
        makeStage({
          id: 7,
          name: "Playoffs",
          stage_type: "double_elimination",
          order: 1,
          advance_count: 2
        })
      ]
    });
    await mount();

    const steps = Array.from(card(COPY.format.title)?.querySelectorAll("ol > li") ?? []).map(
      (node) => node.textContent ?? ""
    );
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
        makeStage({
          id: 7,
          name: " double elimination ",
          stage_type: "double_elimination",
          order: 1
        })
      ]
    });
    await mount();

    const chips = Array.from(
      card(COPY.format.title)?.querySelectorAll('button[aria-haspopup="dialog"]') ?? []
    );
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

    const steps = Array.from(card(COPY.format.title)?.querySelectorAll("ol > li") ?? []).map(
      (node) => node.textContent ?? ""
    );
    expect(steps).toHaveLength(2);
    expect(steps[0]).toContain("Groups Low");
    expect(steps[0]).toContain("Groups High");
    expect(steps[1]).toContain("Playoff Low");
    expect(steps[1]).toContain("Playoff High");
  });

  it("draws no links heading when the only link is the official broadcast", async () => {
    // `TournamentLinkChips` renders nothing for a stream — the dock owns it —
    // so a block around it would be a heading over an empty row.
    tournament = makeTournament("live", {
      links: [{ ...DISCORD, kind: "stream", url: "https://twitch.tv/cast" }]
    });
    await mount();

    expect(headings()).not.toContain(en.tournamentDetail.links.heading);
  });
});
