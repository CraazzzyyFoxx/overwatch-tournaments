// @vitest-environment happy-dom
//
// A stage still in preview (`is_published=false`) is on the public bracket for
// everyone, look-only: even an organizer's handlers must not surface as links,
// edit/report buttons or the rearrange mode there. The standings ⇄ bracket
// switch is the one control that keeps working.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Encounter } from "@/types/encounter.types";
import type { Stage, Standings } from "@/types/tournament.types";

import { EliminationStagePanel } from "./EliminationStagePanel";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let isMobile = false;
vi.mock("@/hooks/useMobile", () => ({ useIsMobile: () => isMobile }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/tournaments/1/bracket",
  useSearchParams: () => new URLSearchParams("stage=3")
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  )
}));

vi.mock("@/services/encounter.service", () => ({ default: { getEncounter: vi.fn() } }));
const getStageBracketPreview = vi.fn();
vi.mock("@/services/tournament.service", () => ({
  default: {
    getStages: vi.fn().mockResolvedValue([]),
    getStageBracketPreview: (...args: unknown[]) => getStageBracketPreview(...args)
  }
}));
vi.mock("@/services/team.service", () => ({
  default: { getAll: vi.fn().mockResolvedValue({ results: [], total: 0 }) }
}));

function stage(isPublished: boolean): Stage {
  return {
    id: 3,
    tournament_id: 1,
    name: "Playoffs",
    description: null,
    stage_type: "single_elimination",
    max_rounds: null,
    advance_count: null,
    advance_upper_count: null,
    order: 1,
    is_active: false,
    is_published: isPublished,
    is_completed: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null },
    swiss_bye_points: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null },
    ffa_scoring: { placement_points: [], score_points: 1, score_label: null },
    challonge_id: null,
    challonge_slug: null,
    items: []
  } as Stage;
}

const encounter = {
  id: 11,
  created_at: new Date(0),
  updated_at: null,
  name: "Nova vs Void",
  home_team_id: 7,
  away_team_id: 8,
  score: { home: 0, away: 0 },
  round: 1,
  best_of: 3,
  tournament_id: 1,
  stage_id: 3,
  stage_item_id: null,
  challonge_id: null,
  status: "open",
  closeness: null,
  has_logs: false,
  result_status: "none",
  scheduled_at: null,
  started_at: null,
  ended_at: null,
  current_map_index: null,
  confirmed_at: null,
  matches: [],
  home_team: null,
  away_team: null,
  tournament: null,
  stage: null,
  stage_item: null
} as unknown as Encounter;

const standing = {
  id: 1,
  tournament_id: 1,
  team_id: 7,
  stage_id: 3,
  stage_item_id: null,
  position: 1,
  overall_position: 1,
  matches: 0,
  win: 0,
  draw: 0,
  lose: 0,
  points: 0,
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
  team: null,
  tournament: null,
  stage: null,
  stage_item: null,
  matches_history: []
} as Standings;

let container: HTMLDivElement;
let root: Root | null = null;

/** The panel as an organizer gets it: every action handler wired. */
function renderPanel(isPublished: boolean, encounters: Encounter[] = [encounter]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const target = stage(isPublished);
  root = createRoot(container);
  act(() =>
    root!.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <EliminationStagePanel
            stage={target}
            encounters={encounters}
            workspaceId={6}
            standings={[standing]}
            stages={[target]}
            bracketTabs={[]}
            defaultView="bracket"
            crownTop={false}
            onEdit={vi.fn()}
            onReport={vi.fn()}
            canEdit={() => true}
            canReport={() => true}
            onSwapSlots={vi.fn()}
            highlightMatchId={null}
          />
        </NextIntlClientProvider>
      </QueryClientProvider>
    )
  );
}

const byLabel = (label: string) => container.querySelector(`[aria-label="${label}"]`);

beforeEach(() => {
  isMobile = false;
  container = document.createElement("div");
  document.body.appendChild(container);
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  container.remove();
});

describe("EliminationStagePanel preview", () => {
  it("gives an organizer links and actions on a published stage", () => {
    renderPanel(true);

    expect(container.querySelector('a[href="/encounters/11"]')).not.toBeNull();
    expect(byLabel(en.bracket.editMatch)).not.toBeNull();
    expect(byLabel(en.bracket.reportMatch)).not.toBeNull();
    expect(byLabel(en.bracket.rearrange)).not.toBeNull();
  });

  it("drops every link and action on a preview, organizer or not", () => {
    renderPanel(false);

    expect(container.textContent).toContain(en.common.bracketPreview);
    expect(container.querySelector("a")).toBeNull();
    expect(byLabel(en.bracket.editMatch)).toBeNull();
    expect(byLabel(en.bracket.reportMatch)).toBeNull();
    expect(byLabel(en.bracket.rearrange)).toBeNull();
    expect(byLabel(en.bracket.viewMatch)).toBeNull();
    expect(byLabel(en.bracket.pregameRoom)).toBeNull();
  });

  it("keeps the phone list look-only too", () => {
    isMobile = true;
    renderPanel(false);

    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelectorAll("li")).toHaveLength(1);
    expect(container.textContent).not.toContain(en.bracket.editMatch);
    expect(container.textContent).not.toContain(en.bracket.reportMatch);
  });

  it("still switches between the bracket and the standings", () => {
    renderPanel(false);

    const tabs = [...container.querySelectorAll<HTMLElement>('[role="tab"]')];
    expect(tabs).toHaveLength(2);
    const standingsTab = tabs[0];
    expect(standingsTab.getAttribute("data-state")).toBe("inactive");

    act(() => {
      standingsTab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    });

    expect(standingsTab.getAttribute("data-state")).toBe("active");
    expect(container.querySelector("table")).not.toBeNull();
  });

  it("draws the bracket the generator would build while it has no matches yet", async () => {
    // A four-team single elimination, every slot still TBD (placeholder seeds).
    getStageBracketPreview.mockResolvedValue([
      { local_id: 1, round: 1, name: "TBD vs TBD", best_of: 3, home_team_id: -1, away_team_id: -4, sources: [] },
      { local_id: 2, round: 1, name: "TBD vs TBD", best_of: 3, home_team_id: -2, away_team_id: -3, sources: [] },
      {
        local_id: 3,
        round: 2,
        name: "TBD vs TBD",
        best_of: 3,
        home_team_id: null,
        away_team_id: null,
        sources: [
          { local_id: 1, role: "winner", slot: "home" },
          { local_id: 2, role: "winner", slot: "away" }
        ]
      }
    ]);
    renderPanel(false, []);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(getStageBracketPreview).toHaveBeenCalledWith(1, 3);
    expect(container.textContent).not.toContain(en.common.noMatches.replace("{stage}", "Playoffs"));
    expect(container.textContent).toContain("M3");
    expect(container.textContent).not.toContain("M4");
    expect(container.querySelector("a")).toBeNull();
  });
});
