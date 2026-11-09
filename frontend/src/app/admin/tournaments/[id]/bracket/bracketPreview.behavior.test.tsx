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
const updateStage = vi.fn();
const applyStageBestOf = vi.fn();
const onBestOfSaved = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getStageBracketPreview: (...args: unknown[]) => getStageBracketPreview(...args),
    updateStage: (...args: unknown[]) => updateStage(...args),
    applyStageBestOf: (...args: unknown[]) => applyStageBestOf(...args)
  }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
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
    order: 1,
    node_id: 1,
    status: "draft",
    is_published: false,
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
      slot_count: 2,
      team_ids: [1, 4],
      sources: []
    },
    {
      local_id: 2,
      round: 1,
      name: "Team 2 vs Team 3",
      best_of: 3,
      slot_count: 2,
      team_ids: [2, 3],
      sources: []
    },
    {
      local_id: 3,
      round: 2,
      name: "TBD vs TBD",
      best_of: 5,
      slot_count: 2,
      team_ids: [null, null],
      sources: [
        { local_id: 1, source_position: 1, slot: 1 },
        { local_id: 2, source_position: 1, slot: 2 }
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
    played_at: null,
    is_live: false,
    is_final: false,
    current_map_index: null,
    confirmed_at: null,
    matches: [],
    slot_count: 2,
    result_source: "games",
    result_version: 1,
    games: [],
    teams: [
      { id: 91, slot: 1, team_id: 1, name: "Team 1", seed: 1, score: 2, placement: 1, active: true },
      { id: 92, slot: 2, team_id: 4, name: "Team 4", seed: 4, score: 1, placement: 2, active: true }
    ],
    tournament: null as never,
    stage: null,
    stage_item: null
  };
}

let container: HTMLDivElement;
let root: Root | null = null;

async function settle() {
  for (let index = 0; index < 12; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

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
              stageType: current.stage_type,
              maxRounds: current.max_rounds,
              bestOf: current.best_of
            })}
            stage={current}
            teams={teams()}
            onBestOfSaved={onBestOfSaved}
          />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  // Two queries settle in sequence: the encounters list decides whether the
  // projection is requested at all.
  await settle();
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  getAllEncounters.mockResolvedValue({ results: [], total: 0 });
  getStageBracketPreview.mockResolvedValue(skeleton());
  updateStage.mockImplementation((_id: number, body: Partial<Stage>) => Promise.resolve({ ...stage(), ...body }));
  applyStageBestOf.mockResolvedValue({ updated: 1 });
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

  it("offers drag-to-reseed on a Draft skeleton only while seeds go in slot order", async () => {
    const toggle = () => container.querySelector("[data-bracket-rearrange]");

    await mount();
    expect(toggle()).not.toBeNull();

    act(() => root!.unmount());
    // An SR ranking re-sorts the seeds whatever their slots: a drop would do nothing.
    await mount({ ...stage(), seed_ranking: "avg_sr" });
    expect(toggle()).toBeNull();
    expect(container.textContent).toContain("Set Bracket seeds to slot order");
  });
});

describe("Best-of on the bracket", () => {
  async function pick(round: number, option: string) {
    const trigger = container.querySelector(`[data-round-best-of="${round}"]`);
    if (!trigger) throw new Error(`No best-of menu on round ${round}`);
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent("pointerdown", { bubbles: true, cancelable: true, button: 0, pointerType: "mouse" })
      );
    });
    const item = Array.from(document.body.querySelectorAll('[role="menuitemradio"]')).find(
      (candidate) => candidate.textContent?.trim() === option
    );
    if (!item) throw new Error(`No "${option}" in the menu`);
    await act(async () => {
      item.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    await settle();
  }

  const savedBestOf = () => (updateStage.mock.calls[0][1] as Pick<Stage, "best_of">).best_of;

  it("saves a round's length from its header at once, without touching matches that do not exist", async () => {
    await mount();

    await pick(1, "Bo5");

    expect(savedBestOf()).toEqual({ default: 3, by_round: { "1": 5 }, final: null, swiss_qualify: null, swiss_eliminate: null });
    expect(applyStageBestOf).not.toHaveBeenCalled();
    expect(onBestOfSaved).toHaveBeenCalledWith(expect.objectContaining({ best_of: savedBestOf() }));
  });

  it("sets the final through `final`, which outranks a row of its own round", async () => {
    // A row left on the final's round would be dead config under `final`.
    await mount({ ...stage(), best_of: { ...stage().best_of, by_round: { "2": 3 } } });

    await pick(2, "Bo5");

    expect(savedBestOf()).toMatchObject({ by_round: {}, final: 5 });
  });

  it("asks before changing a played match, then rewrites the existing ones", async () => {
    getAllEncounters.mockResolvedValue({
      results: [
        generatedEncounter(),
        { ...generatedEncounter(), id: 902, round: 2, status: "open", result_status: "none", teams: [] }
      ],
      total: 2
    });
    await mount();

    await pick(1, "Bo5");
    const dialog = document.body.querySelector('[role="alertdialog"]');
    expect(dialog?.textContent).toContain("1 match that is played, reported or in progress");
    expect(updateStage).not.toHaveBeenCalled();

    const confirm = Array.from(dialog!.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Change best-of"
    );
    await act(async () => {
      confirm!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    await settle();

    expect(savedBestOf().by_round).toEqual({ "1": 5 });
    expect(applyStageBestOf).toHaveBeenCalledWith(5);
  });
});
