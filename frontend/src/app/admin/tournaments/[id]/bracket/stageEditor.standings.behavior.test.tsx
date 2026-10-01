// @vitest-environment happy-dom
//
// One claim: standings are a section of the stage they rank.
//
// The Bracket tab used to carry a `Standings` sub-tab showing every row of the
// tournament at once, with the stage as one filter among others — so an
// organizer looking at a group had to re-pick that group in a second view, and
// the table's Recalculate button sat next to rows from stages they were not
// editing. The section below shows THIS stage's rows and says so with a pinned
// chip instead of a filter that can be widened again.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Stage, Standings } from "@/types/tournament.types";

import { StageEditor } from "./components/StageEditor";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getStandings = vi.fn();
const getStages = vi.fn();
const getTournament = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getStages: (...args: unknown[]) => getStages(...args),
    getTournament: (...args: unknown[]) => getTournament(...args),
    getStagePlannedRounds: vi.fn().mockResolvedValue([]),
    updateStage: vi.fn(),
    updateStanding: vi.fn(),
    deleteStanding: vi.fn(),
    recalculateStandings: vi.fn(),
    syncEncountersFromChallonge: vi.fn()
  }
}));

vi.mock("@/services/tournament.service", () => ({
  default: {
    getAll: vi.fn().mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 }),
    getStandings: (...args: unknown[]) => getStandings(...args)
  }
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: () => true,
    isLoaded: true,
    isSuperuser: true
  })
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  NextIntlClientProvider: ({ children }: { children: ReactNode }) => children
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

vi.mock("@/lib/tournament/workspace-query-keys", () => ({
  invalidateTournamentWorkspace: vi.fn(),
  getTournamentWorkspaceQueryKeys: (tournamentId: number) => ({
    standings: ["admin", "tournament", tournamentId, "standings"]
  })
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/tournaments/84/bracket",
  useParams: () => ({ id: "84" }),
  useSearchParams: () => new URLSearchParams("stage=10&section=standings")
}));

vi.mock("next/link", () => ({ default: "a" }));

// The code split is a bundling concern, and vitest's module runner never
// settles an `import()` issued from a mocked module during render — so the
// wrapper is replaced by the browser itself. The editor has exactly one
// dynamic component, so the loader is never consulted.
vi.mock("next/dynamic", async () => {
  const browser = await import("@/components/admin/StandingsBrowser");
  return { default: () => browser.StandingsBrowser };
});

vi.mock("../hubQueries", () => ({
  tabFallback: null,
  useHubTournamentQuery: () => ({
    data: { id: 84, name: "OWT 84", workspace_id: 4 },
    isLoading: false
  })
}));

function stage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "Groups",
    description: null,
    stage_type: "round_robin",
    max_rounds: 3,
    advance_count: 2,
    advance_upper_count: null,
    order: 0,
    is_active: true,
    is_published: true,
    is_completed: false,
    has_custom_bracket: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null },
    swiss_bye_points: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null },
    ffa_scoring: { columns: [], placement_points: [], formula: "score" },
    challonge_id: null,
    challonge_slug: null,
    items: [],
    ...overrides
  };
}

function standing(overrides: Partial<Standings> = {}): Standings {
  return {
    id: 1,
    tournament_id: 84,
    team_id: 3,
    stage_id: 10,
    stage_item_id: null,
    position: 1,
    overall_position: 1,
    matches: 3,
    win: 3,
    draw: 0,
    lose: 0,
    points: 3,
    buchholz: null,
    full_buchholz: null,
    tie_group: null,
    is_pinned: false,
    tb: null,
    score_differential: null,
    ranking_context: null,
    tb_metrics: null,
    source_rule_profile: null,
    tiebreak_order: null,
    team: { id: 3, name: "Group Team" } as Standings["team"],
    tournament: null,
    stage: null,
    stage_item: null,
    matches_history: [],
    ...overrides
  };
}

const groups = stage();
const playoff = stage({
  id: 20,
  name: "Playoff",
  stage_type: "double_elimination",
  order: 1
});

let container: HTMLDivElement;
let root: Root;

async function settle(turns = 8) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount(selected: Stage): Promise<void> {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const tree: ReactNode = (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <StageEditor
          stage={selected}
          stages={[groups, playoff]}
          tournament={undefined}
          teams={[]}
          isTeamsLoading={false}
          progress={undefined}
          isSuperuser
          encountersHref="/admin/tournaments/84/matches/encounters"
          onChanged={() => {}}
          onSelect={() => {}}
        />
      </TooltipProvider>
    </QueryClientProvider>
  );
  await act(async () => {
    root.render(tree);
  });
  await settle();
}

beforeEach(() => {
  getStages.mockReset().mockResolvedValue([groups, playoff]);
  getTournament.mockReset().mockResolvedValue({ id: 84, name: "OWT 84", workspace_id: 4 });
  getStandings.mockReset().mockResolvedValue([
    standing(),
    standing({ id: 2, team_id: 4, team: { id: 4, name: "Playoff Team" } as Standings["team"], stage_id: 20 })
  ]);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("stage editor › Standings section", () => {
  it("shows only the selected stage's rows, pinned to that stage", async () => {
    await mount(groups);

    expect(container.textContent).toContain("Group Team");
    // The playoff's row belongs to the playoff's own Standings section.
    expect(container.textContent).not.toContain("Playoff Team");
    expect(container.textContent).toContain("Stage: Groups");
  });

  it("states the stage as a pinned fact, not a filter that can be widened", async () => {
    await mount(groups);

    const chip = container.querySelector('[data-pinned-filter="stage"]');
    expect(chip?.textContent).toBe("Stage: Groups");
    // A pinned chip carries no remove control: widening the scope here would
    // show rows of stages this editor is not editing.
    expect(chip?.querySelector("button")).toBeNull();
  });

  it("follows the selection: the playoff section shows the playoff's rows", async () => {
    await mount(playoff);

    expect(container.textContent).toContain("Playoff Team");
    expect(container.textContent).not.toContain("Group Team");
    expect(container.textContent).toContain("Stage: Playoff");
  });
});
