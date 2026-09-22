// @vitest-environment happy-dom
//
// Teams is two renderings of one dataset, and the toolbar above them is the
// single source of order, filter and search for both. What is pinned here:
//
//  1. the default is the list — twenty teams comparable at a glance — and
//     `?view=cards` is what brings the full-roster cards back;
//  2. the search reaches battletags, not just team names, and narrows BOTH
//     views to the teams that carry the player (the card view marks the tag it
//     matched, since the card itself renders no highlight);
//  3. `?sort=` reorders both views, `?sort=sr` by average SR descending;
//  4. W-L comes from the tournament's settled encounters and honestly reads
//     "—" when that read is unavailable — never a zero that looks played.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { RosterShape } from "@/lib/roster/shape";
import type { Encounter } from "@/types/encounter.types";
import type { Player, Team } from "@/types/team.types";
import type { TeamGroup, Tournament, TournamentStatus } from "@/types/tournament.types";

import TournamentTeamsPage from "./TournamentTeamsPage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TOURNAMENT_ID = 88;
const SLUG = "anak-cup";

const getTeams = vi.fn();
const getEncounters = vi.fn();

vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));
vi.mock("@/services/encounter.service", () => ({
  default: { getAll: (...args: unknown[]) => getEncounters(...args) }
}));

/**
 * The division badge is an art asset resolved against the workspace grid; the
 * roster rows under a `<details>` are asserted by their text, not their icons.
 */
vi.mock("@/components/DivisionIcon", () => ({
  default: ({ division }: { division: number }) => <span data-division={division} />
}));

/** The page's whole URL state. `render` sets it; nothing here writes it back. */
let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => search,
  usePathname: () => `/tournaments/${SLUG}/teams`,
  useRouter: () => ({ replace: () => {}, push: () => {} })
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  )
}));

let tournament: Tournament;

vi.mock("@/hooks/useTournamentClientData", () => ({
  useTournamentQuery: () => ({ data: tournament, isError: false, refetch: () => {} })
}));

/** 1 tank, 2 damage, 2 support — the shape the five glyphs of a row come from. */
const SHAPE: RosterShape = {
  slots: { tank: 1, damage: 2, support: 2 },
  team_size: 5,
  flex_slots: 0,
  has_role_slots: true,
  draft_rounds: 5,
  source: "tournament"
};

/**
 * Every field spelled out rather than cast: `tsconfig.json` excludes test
 * files, so a fixture that lies about its shape type-checks green.
 */
function makeTournament(status: TournamentStatus): Tournament {
  return {
    id: TOURNAMENT_ID,
    created_at: new Date(0),
    updated_at: null,
    workspace_id: 3,
    name: "Anak Cup",
    start_date: new Date(0),
    end_date: new Date(0),
    description: null,
    challonge_id: null,
    challonge_slug: null,
    is_league: false,
    is_finished: false,
    is_hidden: false,
    team_formation: "balancer",
    status,
    auto_transitions_enabled: true,
    allow_late_registration: false,
    phase_schedule: [],
    win_points: 1,
    draw_points: 0.5,
    loss_points: 0,
    stages: [],
    participants_count: 15,
    registrations_count: 15,
    teams_count: 3,
    division_grid_version_id: null,
    division_grid_version: null,
    roster_slots_json: null,
    roster_shape: SHAPE,
    roster_locked_by_draft: null
  };
}

const GROUP_A: TeamGroup = { id: 1, name: "A" };
const GROUP_B: TeamGroup = { id: 2, name: "B" };

function player(id: number, name: string, role: string, division: number): Player {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name,
    sub_role: role === "Tank" ? "main_tank" : null,
    rank: 4,
    division,
    role,
    tournament_id: TOURNAMENT_ID,
    user_id: id + 500,
    team_id: 0,
    is_newcomer: false,
    is_newcomer_role: false,
    is_substitution: false,
    related_player_id: null,
    user: null
  };
}

function team(
  id: number,
  name: string,
  avgSr: number,
  placement: number | null,
  group: TeamGroup,
  roster: readonly [string, string, string, string, string]
): Team {
  const roles = ["Tank", "Damage", "Damage", "Support", "Support"];
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name,
    image_url: null,
    avg_sr: avgSr,
    total_sr: avgSr * 5,
    captain_id: id * 100 + 500,
    tournament_id: TOURNAMENT_ID,
    players: roster.map((tag, index) =>
      player(id * 100 + index, tag, roles[index], 3 + index)
    ),
    tournament: null,
    placement,
    group
  };
}

/**
 * Three teams whose SR order is deliberately NOT their placement order, so a
 * page that ignored `?sort=` would still pass the placement assertion and fail
 * this one.
 */
const EMERALD = team(1, "Emerald and a dot", 3760, 1, GROUP_A, [
  "yaLucky#21743",
  "CraazzzyyFox#2130",
  "VipereSombre#21773",
  "Kenny#1404",
  "Naord#2311"
]);
const BAN_KOTA = team(2, "Ban kota", 3800, 2, GROUP_A, [
  "dasha21cm#2481",
  "manqa#21668",
  "konweni#1314",
  "Sup1#1001",
  "Sup2#1002"
]);
const FREAKS = team(3, "Freak deck", 3705, 3, GROUP_B, [
  "zMize#2978",
  "Hornet#21345",
  "SerFim#21874",
  "Sup3#1003",
  "Sup4#1004"
]);

const TEAMS = [EMERALD, BAN_KOTA, FREAKS];

/** Emerald beat Ban kota twice; Freaks played nothing settled. */
function encounter(id: number, home: Team, away: Team, score: { home: number; away: number }): Encounter {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name: `E${id}`,
    home_team_id: home.id,
    away_team_id: away.id,
    score,
    round: 1,
    best_of: 3,
    tournament_id: TOURNAMENT_ID,
    stage_id: null,
    stage_item_id: null,
    challonge_id: null,
    status: "completed",
    closeness: null,
    has_logs: false,
    result_status: "confirmed",
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    current_map_index: null,
    confirmed_at: null,
    matches: [],
    home_team: home,
    away_team: away,
    tournament: makeTournament("completed")
  };
}

const ENCOUNTERS = [
  encounter(10, EMERALD, BAN_KOTA, { home: 2, away: 0 }),
  encounter(11, EMERALD, FREAKS, { home: 2, away: 1 })
];

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  // Node 22 exposes its own `localStorage` that throws without
  // `--localstorage-file`, and happy-dom does not shadow it. A per-test
  // in-memory store is also what "the same browser, one tournament later"
  // means here, and it never leaks into the next test.
  const stored = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => stored.get(key) ?? null,
      setItem: (key: string, value: string) => void stored.set(key, String(value)),
      removeItem: (key: string) => void stored.delete(key),
      clear: () => stored.clear()
    }
  });
  tournament = makeTournament("completed");
  getTeams.mockResolvedValue({ results: TEAMS });
  getEncounters.mockResolvedValue({ results: ENCOUNTERS });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  search = new URLSearchParams();
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

async function render(query = "") {
  search = new URLSearchParams(query);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <TournamentTeamsPage slug={SLUG} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  return container.textContent ?? "";
}

/** Collapsed list rows, in DOM order, by the team name each carries. */
function listRows(): string[] {
  return Array.from(container.querySelectorAll("details > summary")).map((summary) => {
    const name = summary.querySelector("[title]")?.getAttribute("title");
    return name ?? summary.textContent ?? "";
  });
}

/** The cards view's articles, in DOM order. */
function cardNames(): string[] {
  return Array.from(container.querySelectorAll("article.team-card .tc-name")).map(
    (node) => node.textContent ?? ""
  );
}

describe("the list is the default view", () => {
  it("renders one expandable row per team, ordered by placement", async () => {
    await render();

    expect(listRows()).toEqual(["Emerald and a dot", "Ban kota", "Freak deck"]);
    expect(cardNames()).toEqual([]);
  });

  it("brings the full-roster cards back on ?view=cards", async () => {
    await render("view=cards");

    expect(cardNames()).toEqual(["Emerald and a dot", "Ban kota", "Freak deck"]);
    expect(container.querySelectorAll("details > summary")).toHaveLength(0);
  });

  it("links a row's roster to that team's matches", async () => {
    await render();

    const hrefs = Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).toContain(`/tournaments/${SLUG}/matches?team=${EMERALD.id}`);
  });

  it("opens on the remembered view when the URL carries none", async () => {
    window.localStorage.setItem("owt:teams-view", "cards");
    await render();

    expect(cardNames()).toEqual(["Emerald and a dot", "Ban kota", "Freak deck"]);
  });

  it("lets the URL outrank the remembered view", async () => {
    window.localStorage.setItem("owt:teams-view", "cards");
    await render("view=list");

    expect(cardNames()).toEqual([]);
    expect(listRows()).toEqual(["Emerald and a dot", "Ban kota", "Freak deck"]);
  });
});

describe("searching reaches battletags", () => {
  it("leaves only the player's team in the list", async () => {
    await render("q=yalucky");

    expect(listRows()).toEqual(["Emerald and a dot"]);
    expect(container.querySelector("mark")?.textContent).toBe("yaLucky#21743");
  });

  it("leaves only the player's team in the cards, with the tag marked", async () => {
    await render("q=yalucky&view=cards");

    expect(cardNames()).toEqual(["Emerald and a dot"]);
    expect(container.querySelector("mark")?.textContent).toBe("yaLucky#21743");
  });

  it("offers a way out when nothing matches", async () => {
    const text = await render("q=nobody");

    expect(listRows()).toEqual([]);
    expect(text).toContain(en.tournamentDetail.pageState.filteredEmpty.title);
  });
});

describe("the toolbar orders both views", () => {
  it("sorts by average SR descending on ?sort=sr", async () => {
    await render("sort=sr");

    expect(listRows()).toEqual(["Ban kota", "Emerald and a dot", "Freak deck"]);
  });

  it("applies the same order to the cards", async () => {
    await render("sort=sr&view=cards");

    expect(cardNames()).toEqual(["Ban kota", "Emerald and a dot", "Freak deck"]);
  });

  it("filters by group", async () => {
    await render("group=B");

    expect(listRows()).toEqual(["Freak deck"]);
  });
});

describe("the W-L column", () => {
  it("counts the tournament's settled encounters", async () => {
    await render();

    const rows = Array.from(container.querySelectorAll("details > summary"));
    expect(rows[0]?.textContent).toContain("2–0");
    expect(rows[1]?.textContent).toContain("0–1");
  });

  it("reads an em dash when encounters are unavailable", async () => {
    getEncounters.mockRejectedValue(new Error("offline"));
    await render();
    await settle();

    const rows = Array.from(container.querySelectorAll("details > summary"));
    expect(rows[0]?.textContent).toContain("—");
    expect(rows[0]?.textContent).not.toContain("0–0");
  });
});

describe("nothing to show", () => {
  it("renders the empty state, not an empty toolbar", async () => {
    getTeams.mockResolvedValue({ results: [] });
    const text = await render();

    expect(text).toContain(en.tournamentDetail.pageState.empty.title);
    expect(container.querySelectorAll("details")).toHaveLength(0);
  });
});
