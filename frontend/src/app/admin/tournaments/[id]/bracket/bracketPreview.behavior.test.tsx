// @vitest-environment happy-dom
//
// One claim: the Bracket tab's preview draws a REAL bracket.
//
// It used to render a row of round chips — a summary that says "UB Round 1,
// Bo3" and nothing about which team meets whom, how many matches a round has,
// or where a loser drops. The tree here comes out of the backend generator
// (`GET /admin/stages/{id}/bracket-preview`) and is drawn by the same
// `BracketView` the public page uses, so what an organizer configures is what
// gets generated.
//
// Pinned: the projected skeleton is drawn with the generator's slot hints and
// WITHOUT the links a card has on the public page (those matches have no
// encounter row yet), and once the stage really has matches those are drawn
// instead — with the links back.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { StageBracketPreviewMatch } from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
import type { Team } from "@/types/team.types";
import type { Stage } from "@/types/tournament.types";

import { BracketPreview } from "./components/BracketPreview";
import { projectStage } from "@/lib/bracket/projection";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getStageBracketPreview = vi.fn();
const getAllEncounters = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getStageBracketPreview: (...args: unknown[]) => getStageBracketPreview(...args)
  }
}));

vi.mock("@/services/encounter.service", () => ({
  default: {
    getAll: (...args: unknown[]) => getAllEncounters(...args),
    getEncounter: vi.fn()
  }
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/tournaments/84/bracket",
  useSearchParams: () => new URLSearchParams("stage=5")
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  )
}));

/** A 4-team single-elimination stage with its seeds wired in. */
function stage(): Stage {
  return {
    id: 5,
    tournament_id: 84,
    name: "Playoff",
    description: null,
    stage_type: "single_elimination",
    max_rounds: 2,
    advance_count: null,
    split_lower_bracket: false,
    order: 1,
    is_active: false,
    is_published: false,
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
    items: [
      {
        id: 1,
        stage_id: 5,
        name: "Bracket",
        type: "single_bracket",
        order: 0,
        inputs: [1, 2, 3, 4].map((slot) => ({
          id: slot,
          stage_item_id: 1,
          slot,
          input_type: "final" as const,
          team_id: slot,
          source_stage_item_id: null,
          source_position: null
        }))
      }
    ]
  };
}

function teams(): Team[] {
  return [1, 2, 3, 4].map((id) => ({ id, name: `Team ${id}` }) as Team);
}

/** What the generator emits for that stage: two semifinals feeding a final. */
function skeleton(): StageBracketPreviewMatch[] {
  return [
    {
      local_id: 1,
      round: 1,
      name: "Team 1 vs Team 4",
      best_of: 3,
      home_team_id: 1,
      away_team_id: 4,
      sources: []
    },
    {
      local_id: 2,
      round: 1,
      name: "Team 2 vs Team 3",
      best_of: 3,
      home_team_id: 2,
      away_team_id: 3,
      sources: []
    },
    {
      local_id: 3,
      round: 2,
      name: "TBD vs TBD",
      best_of: 5,
      home_team_id: null,
      away_team_id: null,
      sources: [
        { local_id: 1, role: "winner", slot: "home" },
        { local_id: 2, role: "winner", slot: "away" }
      ]
    }
  ];
}

function generatedEncounter(): Encounter {
  return {
    id: 900,
    created_at: new Date(0),
    updated_at: null,
    name: "Team 1 vs Team 4",
    home_team_id: 1,
    away_team_id: 4,
    score: { home: 2, away: 1 },
    round: 1,
    best_of: 3,
    tournament_id: 84,
    stage_id: 5,
    stage_item_id: 1,
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
    home_team: null as never,
    away_team: null as never,
    tournament: null as never,
    stage: null,
    stage_item: null
  };
}

let container: HTMLDivElement;
let root: Root | null = null;

async function mount(current: Stage = stage()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  root = createRoot(container);
  await act(async () => {
    root!.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <BracketPreview
            projection={projectStage({
              stage: current,
              stages: [current],
              stageType: current.stage_type,
              splitLowerBracket: false,
              maxRounds: current.max_rounds,
              bestOf: current.best_of
            })}
            stage={current}
            teams={teams()}
          />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  // Two queries settle in sequence: the encounters list decides whether the
  // projection is requested at all.
  for (let index = 0; index < 12; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  getAllEncounters.mockResolvedValue({ results: [], total: 0 });
  getStageBracketPreview.mockResolvedValue(skeleton());
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  container.remove();
  vi.clearAllMocks();
});

describe("Bracket preview", () => {
  it("draws the generator's skeleton, hints included, with no links out", async () => {
    await mount();

    // One card per pairing, seeds named.
    expect(container.textContent).toContain("Team 1");
    expect(container.textContent).toContain("Team 3");
    // The final's slots are labelled from the real advancement edges, not from
    // a shape guessed out of round numbers.
    expect(container.textContent).toContain("W M1");
    expect(container.textContent).toContain("W M2");
    // A drawn tree, not a list of round labels: the connectors between the
    // rounds are what the chips this replaced could never express.
    expect(container.querySelectorAll("svg path").length).toBeGreaterThanOrEqual(2);
    // Three matches: M1, M2 and the final.
    expect(container.textContent).toContain("M3");
    // Nothing to link to yet.
    expect(container.querySelectorAll("a[href^='/encounters/']")).toHaveLength(0);
  });

  it("draws the stage's real matches once they exist, and links to them", async () => {
    getAllEncounters.mockResolvedValue({ results: [generatedEncounter()], total: 1 });

    await mount();

    // The generated bracket is the truth: the projection is never requested.
    expect(container.textContent).toContain("2");
    expect(getStageBracketPreview).not.toHaveBeenCalled();
    expect(container.querySelector("a[href='/encounters/900']")).not.toBeNull();
  });

  it("draws one tree per group so a group stage is not one flat column", async () => {
    const groups: Stage = {
      ...stage(),
      name: "Groups",
      stage_type: "round_robin",
      items: [
        { id: 10, stage_id: 5, name: "Group A", type: "group", order: 0, inputs: [] },
        { id: 11, stage_id: 5, name: "Group B", type: "group", order: 1, inputs: [] }
      ]
    };
    getAllEncounters.mockResolvedValue({
      results: [
        { ...generatedEncounter(), id: 900, stage_item_id: 10 },
        { ...generatedEncounter(), id: 901, stage_item_id: 11, name: "Team 2 vs Team 3" }
      ],
      total: 2
    });

    await mount(groups);

    expect(container.textContent).toContain("Group A");
    expect(container.textContent).toContain("Group B");
    // Two trees, not one column: each group's match is drawn under its own name.
    expect(container.querySelector("a[href='/encounters/900']")).not.toBeNull();
    expect(container.querySelector("a[href='/encounters/901']")).not.toBeNull();
  });

  it("names every group's own advance count, not the stage default it overrides", async () => {
    const groups: Stage = {
      ...stage(),
      name: "Groups",
      stage_type: "round_robin",
      advance_count: 2,
      items: [
        { id: 10, stage_id: 5, name: "Group A", type: "group", order: 0, advance_count: 3, inputs: [] },
        { id: 11, stage_id: 5, name: "Group B", type: "group", order: 1, advance_count: null, inputs: [] }
      ]
    };
    getAllEncounters.mockResolvedValue({ results: [], total: 0 });

    await mount(groups);

    // "top 2 of each" would be a lie about group A, and 4 onward a lie about both.
    expect(container.textContent).toContain("top 3 / 2 of each advance, 5 teams onward");
  });
});
