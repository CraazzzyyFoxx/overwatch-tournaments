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
import type { Encounter } from "@/types/encounter.types";
import type { MapRead } from "@/types/map.types";
import type { Registration } from "@/types/registration.types";
import type { Team } from "@/types/team.types";
import type { TournamentLink } from "@/types/stream.types";
import type { PickBanConfig, Stage, StageSummary, Tournament, TournamentStatus } from "@/types/tournament.types";

import TournamentOverviewPage from "./TournamentOverviewPage";

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
const getHeroPlaytime = vi.fn();
const listPublicConfigs = vi.fn();
const getAllMaps = vi.fn();
const getTournamentStreams = vi.fn();

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
vi.mock("@/services/hero.service", () => ({
  default: { getHeroPlaytime: (...args: unknown[]) => getHeroPlaytime(...args) }
}));
vi.mock("@/services/pickBan.service", () => ({
  default: { listPublicConfigs: (...args: unknown[]) => listPublicConfigs(...args) }
}));
vi.mock("@/services/map.service", () => ({
  default: { getAll: (...args: unknown[]) => getAllMaps(...args) }
}));
vi.mock("@/services/stream.service", () => ({
  default: { getTournamentStreams: (...args: unknown[]) => getTournamentStreams(...args) }
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

let tournament: Tournament;

vi.mock("../_hooks/useTournamentClientData", () => ({
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
    split_lower_bracket: true,
    order: 1,
    is_active: true,
    is_published: true,
    is_completed: false,
    settings_json: null,
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
    roster_slots_json: null,
    roster_shape: {
      slots: { tank: 1, dps: 2, support: 2 },
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
      sub_role: null,
      rank: 3500,
      division: 3,
      role: "Damage",
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

function makeEncounter(
  id: number,
  round: number,
  home: Team,
  away: Team,
  score: { home: number; away: number },
  overrides: Partial<Encounter> = {}
): Encounter {
  return {
    id,
    created_at: new Date("2024-08-12T12:00:00Z"),
    updated_at: null,
    name: `M${id}`,
    home_team_id: home.id,
    away_team_id: away.id,
    score,
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
    scheduled_at: null,
    started_at: new Date("2024-08-12T12:00:00Z").toISOString(),
    ended_at: new Date("2024-08-12T13:00:00Z").toISOString(),
    current_map_index: null,
    confirmed_at: null,
    matches: [],
    home_team: home,
    away_team: away,
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
    makeEncounter(1, 1, ALPHA, GAMMA, { home: 2, away: 0 }),
    makeEncounter(2, 1, BETA, DELTA, { home: 2, away: 0 }),
    makeEncounter(4, -1, BETA, GAMMA, { home: 2, away: 0 }),
    makeEncounter(3, 2, ALPHA, BETA, { home: 3, away: 2 })
  ];
}

function makeRegistration(id: number, role: string, battleTag: string): Registration {
  return {
    id,
    tournament_id: TOURNAMENT_ID,
    workspace_id: WORKSPACE_ID,
    user_id: id,
    battle_tag: battleTag,
    smurf_tags_json: null,
    discord_nick: null,
    twitch_nick: null,
    stream_pov: false,
    roles: [{ role, subrole: null, is_primary: true, priority: 0, top_heroes: [] }],
    notes: null,
    custom_fields_json: null,
    status: "approved",
    admission: { decision: "admitted", stage: "registration", requirements: [], reasons: [] },
    submitted_at: `2024-08-0${id}T10:00:00Z`,
    reviewed_at: null
  } as Registration;
}

const GAMEMODE = {
  id: 1,
  created_at: new Date(0),
  updated_at: null,
  name: "Control",
  image_path: "/modes/control.png",
  slug: "control",
  description: "",
  aliases: []
};

const MAPS: MapRead[] = [
  {
    id: 41,
    created_at: new Date(0),
    updated_at: null,
    name: "Ilios",
    image_path: "/maps/ilios.png",
    gamemode_id: 1,
    in_competitive: true,
    aliases: [],
    gamemode: GAMEMODE
  },
  {
    id: 42,
    created_at: new Date(0),
    updated_at: null,
    name: "Busan",
    image_path: "/maps/busan.png",
    gamemode_id: 1,
    in_competitive: true,
    aliases: [],
    gamemode: GAMEMODE
  },
  {
    id: 43,
    created_at: new Date(0),
    updated_at: null,
    name: "King's Row",
    image_path: "/maps/kings-row.png",
    gamemode_id: 2,
    in_competitive: true,
    aliases: [],
    gamemode: { ...GAMEMODE, id: 2, name: "Hybrid", slug: "hybrid" }
  }
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
  turn_timer_seconds: null,
  preset: null,
  sequence: ["ban_first", "ban_second", "decider"],
  no_repeat_scope: "none",
  unique_attribute_per_side_per_round: null,
  allow_protect: false,
  item_ids: [41, 42, 43],
  slots: []
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  tournament = makeTournament("live");
  getAllEncounters.mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
  listRegistrations.mockResolvedValue([]);
  getStandings.mockResolvedValue([]);
  getStages.mockResolvedValue([] as Stage[]);
  getTeams.mockResolvedValue({ results: [ALPHA, BETA, GAMMA, DELTA], total: 4, page: 1, per_page: -1 });
  getHeroPlaytime.mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
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
    listRegistrations.mockResolvedValue([
      makeRegistration(1, "tank", "Hornet#21345"),
      makeRegistration(2, "dps", "zMize#2978"),
      makeRegistration(3, "dps", "manqa#21668"),
      makeRegistration(4, "support", "Naord#2100")
    ]);
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

  it("breaks registration down by role and shows the format in full", async () => {
    await mount();

    const registration = Array.from(container.querySelectorAll("section")).find((node) =>
      node.querySelector("h2")?.textContent?.includes(COPY.registration.title)
    );
    expect(registration).toBeDefined();
    const text = registration?.textContent ?? "";
    expect(text).toContain(en.common.roles.tank);
    expect(text).toContain(en.common.roles.dps);
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
    // The roster shape reads as role glyphs (1 tank, 2 dps, 2 support), each
    // announced by its slot name — not as "1 × Tank · 2 × DPS".
    const glyphs = Array.from(container.querySelectorAll('[role="img"]')).map((node) =>
      node.getAttribute("aria-label")
    );
    expect(glyphs).toContain(en.rosterShape.slotCodes.tank);
    expect(glyphs).toContain(en.rosterShape.slotCodes.dps);
    expect(glyphs).toContain(en.rosterShape.slotCodes.support);
    expect(container.textContent).toContain("×2");
    // The old "1 × Tank" spelling is gone: no slot name in the format card.
    expect(container.textContent).not.toContain(`× ${en.rosterShape.slotCodes.tank}`);
  });

  it("does not tease the map pool — that lives on the Maps section", async () => {
    await mount();

    expect(container.querySelector("#map-pool")).toBeNull();
    expect(
      Array.from(container.querySelectorAll("a")).some(
        (node) => node.getAttribute("href") === `/tournaments/${SLUG}/maps`
      )
    ).toBe(false);
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
        makeEncounter(1, 1, ALPHA, GAMMA, { home: 1, away: 1 }, {
          status: "in_progress",
          ended_at: null
        }),
        makeEncounter(2, 1, BETA, DELTA, { home: 2, away: 0 })
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
        makeEncounter(1, 1, ALPHA, GAMMA, { home: 2, away: 0 }),
        makeEncounter(9, 2, ALPHA, BETA, { home: 0, away: 0 }, {
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
    const drawn = (id: number, round: number, home: Team, away: Team) =>
      makeEncounter(id, round, home, away, { home: 0, away: 0 }, {
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
      results: [makeEncounter(1, 1, ALPHA, GAMMA, { home: 2, away: 0 })],
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
      results: [makeEncounter(1, 1, ALPHA, GAMMA, { home: 2, away: 0 })],
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

  it("renders the official broadcast as a still that opens the stream page", async () => {
    getTournamentStreams.mockResolvedValue({
      official: [
        {
          platform: "twitch",
          channel: "owtesports",
          url: "https://twitch.tv/owtesports",
          live: true,
          title: "Grand final",
          game_name: "Overwatch 2",
          viewer_count: 1200,
          thumbnail_url: "https://example.test/thumb.jpg",
          started_at: null,
          player: null
        }
      ],
      participants: []
    });
    await mount();

    expect(headings()).toContain(COPY.stream.title);
    const still = Array.from(container.querySelectorAll("a")).find(
      (node) =>
        node.getAttribute("href") === `/tournaments/${SLUG}/stream` && node.querySelector("img")
    );
    expect(still?.querySelector("img")?.getAttribute("src")).toBe("https://example.test/thumb.jpg");
    expect(still?.textContent).toContain("owtesports");
    expect(still?.textContent).toContain(en.stream.status.live);
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
    // the bracket: "2–3 in the final", "Eliminated in Lower R1".
    expect(text).toContain("yaLucky · Kenny");
    expect(text).toContain(COPY.result.finalScore.replace("{score}", "2–3"));
    expect(text).toContain(COPY.result.exitedIn.replace("{round}", "Lower R1"));
  });

  it("counts the tournament up and links onward to the statistics", async () => {
    getHeroPlaytime.mockResolvedValue({
      results: [{ hero: { id: 1, name: "Kiriko", image_path: "/heroes/kiriko.png" }, playtime: 0.091 }],
      total: 1,
      page: 1,
      per_page: -1
    });
    await mount();

    const titles = headings();
    expect(titles).toContain(COPY.numbers.title);
    expect(titles).toContain(COPY.heroes.title);
    expect(container.textContent).toContain("Kiriko");
    // Two calendar days, 4 matches, 4 teams, 20 players.
    const numbers = Array.from(container.querySelectorAll("section")).find((node) =>
      node.querySelector("h2")?.textContent?.includes(COPY.numbers.title)
    );
    expect(numbers?.textContent).toContain("4");
    expect(numbers?.textContent).toContain("20");
    expect(numbers?.textContent).toContain("2");
  });

  it("drops to third-by-standings when the tournament never had a bracket", async () => {
    tournament = makeTournament("completed", {
      stages: [makeStage({ id: 7, name: "League", stage_type: "round_robin", is_completed: true })]
    });
    getAllEncounters.mockResolvedValue({
      results: [makeEncounter(1, 1, ALPHA, GAMMA, { home: 2, away: 0 })],
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

  it("names the stages once, with each stage's type — not the card's own heading twice", async () => {
    tournament = makeTournament("live", {
      stages: [
        makeStage({ id: 6, name: "Groups", stage_type: "round_robin", order: 0 }),
        makeStage({ id: 7, name: "Playoffs", stage_type: "double_elimination", order: 1 })
      ]
    });
    await mount();

    const card = Array.from(container.querySelectorAll("section")).find((node) =>
      node.querySelector("h2")?.textContent?.includes(COPY.format.title)
    );
    const text = card?.textContent ?? "";

    // The first row is "Stages", not a second "Format" under the heading.
    const terms = Array.from(card?.querySelectorAll("dt") ?? []).map((node) =>
      node.textContent?.trim()
    );
    expect(terms[0]).toBe(en.common.stages);
    expect(terms).not.toContain(COPY.format.title);
    expect(text).toContain(`Groups (${en.common.roundRobin})`);
    expect(text).toContain(`Playoffs (${en.bracket.doubleElimination.toLowerCase()})`);
    // The derived label used to restate them: "Groups → Playoff — Groups → Playoffs".
    expect(text).not.toContain("Groups → Playoff —");
    expect(text).toContain(
      `Groups (${en.common.roundRobin}) → Playoffs (${en.bracket.doubleElimination.toLowerCase()})`
    );
  });

  it("joins stages that share a phase order as parallel brackets", async () => {
    tournament = makeTournament("live", {
      stages: [
        makeStage({ id: 6, name: "PlayOff Low division", stage_type: "double_elimination", order: 1 }),
        makeStage({
          id: 7,
          name: "PlayOff High division",
          stage_type: "double_elimination",
          order: 1
        })
      ]
    });
    await mount();

    const card = Array.from(container.querySelectorAll("section")).find((node) =>
      node.querySelector("h2")?.textContent?.includes(COPY.format.title)
    );
    const text = card?.textContent ?? "";
    const type = en.bracket.doubleElimination.toLowerCase();
    expect(text).toContain(`PlayOff Low division (${type}) / PlayOff High division (${type})`);
    expect(text).not.toContain("→");
  });

  it("renders parallel stages per phase, then an arrow to the next wave", async () => {
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
    const rr = en.common.roundRobin;
    const de = en.bracket.doubleElimination.toLowerCase();
    expect(card?.textContent ?? "").toContain(
      `Groups Low (${rr}) / Groups High (${rr}) → Playoff Low (${de}) / Playoff High (${de})`
    );
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
