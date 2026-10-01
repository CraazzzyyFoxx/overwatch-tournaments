// @vitest-environment happy-dom
//
// One claim: a bracket's wiring is editable on the canvas, and only the server
// decides whether the result is a bracket.
//
// The stage used to be whatever the generator produced for its team count. The
// layout here is the stage's own blueprint: clicking a match's `W` output and
// then another match's slot IS the advancement edge that will be written, and
// a result can only sit in one slot, so wiring it somewhere new empties where
// it was. What the editor refuses on its own is only the one thing the payload
// cannot express — an empty slot. Every bracket rule (the shape of the final,
// the loser drops) is the validator's, and its complaints come back as a list
// that points at the match it is talking about.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api/error";
import type { BracketTemplateRead } from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
import type { Stage } from "@/types/tournament.types";

import { BracketLayoutSection } from "./BracketLayoutSection";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getStageBracketTemplate = vi.fn();
const setStageBracketTemplate = vi.fn();
const clearStageBracketTemplate = vi.fn();
const getAllEncounters = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getStageBracketTemplate: (...args: unknown[]) => getStageBracketTemplate(...args),
    setStageBracketTemplate: (...args: unknown[]) => setStageBracketTemplate(...args),
    clearStageBracketTemplate: (...args: unknown[]) => clearStageBracketTemplate(...args)
  }
}));

vi.mock("@/services/encounter.service", () => ({
  default: {
    getAll: (...args: unknown[]) => getAllEncounters(...args),
    getEncounter: vi.fn()
  }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

/** A 4-team single-elimination stage. */
function stage(): Stage {
  return {
    id: 5,
    tournament_id: 84,
    name: "Playoff",
    description: null,
    stage_type: "single_elimination",
    max_rounds: 2,
    advance_count: null,
    advance_upper_count: null,
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
    items: []
  };
}

/** What `GET bracket-template` answers for it: the generated 4-team layout. */
function generatedTemplate(): BracketTemplateRead {
  return {
    custom: false,
    seeds: { upper: 4, lower: 0 },
    template: {
      version: 1,
      upper_seeds: 4,
      lower_seeds: 0,
      matches: [
        { id: 1, round: 1, home: { seed: "U1" }, away: { seed: "U4" } },
        { id: 2, round: 1, home: { seed: "U2" }, away: { seed: "U3" } },
        { id: 3, round: 2, home: { winner_of: 1 }, away: { winner_of: 2 } }
      ]
    }
  };
}

function generatedEncounter(): Encounter {
  return {
    id: 900,
    created_at: new Date(0),
    updated_at: null,
    name: "Team 1 vs Team 4",
    home_team_id: 1,
    away_team_id: 4,
    score: { home: 0, away: 0 },
    round: 1,
    best_of: 3,
    tournament_id: 84,
    stage_id: 5,
    stage_item_id: 1,
    challonge_id: null,
    status: "open",
    closeness: null,
    has_logs: false,
    result_status: null,
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

async function settle() {
  for (let index = 0; index < 8; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  root = createRoot(container);
  await act(async () => {
    root!.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <BracketLayoutSection stage={stage()} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  return client;
}

async function click(element: Element | null | undefined) {
  if (!element) throw new Error("Nothing to click");
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
  await settle();
}

const port = (id: string) => container.querySelector(`[data-template-port="${id}"]`);
const slot = (id: string) => container.querySelector(`[data-template-slot="${id}"]`);

function button(label: string, scope: ParentNode = container): HTMLButtonElement | undefined {
  return Array.from(scope.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.trim() === label
  );
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  getAllEncounters.mockResolvedValue({ results: [], total: 0 });
  // A new object per call, the way a real refetch answers.
  getStageBracketTemplate.mockImplementation(() => Promise.resolve(generatedTemplate()));
  setStageBracketTemplate.mockResolvedValue(generatedTemplate());
  clearStageBracketTemplate.mockResolvedValue(generatedTemplate());
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  container.remove();
  vi.clearAllMocks();
});

describe("Bracket layout editor", () => {
  it("saves the wiring drawn on the canvas", async () => {
    await mount();

    // Swap the final's feeders: W(M1) into `away`, which empties the `home`
    // slot it used to hold, then W(M2) into the slot it vacated.
    await click(port("1-winner"));
    await click(slot("3-away"));
    await click(port("2-winner"));
    await click(slot("3-home"));
    await click(button("Save"));

    expect(setStageBracketTemplate).toHaveBeenCalledWith(5, {
      version: 1,
      upper_seeds: 4,
      lower_seeds: 0,
      matches: [
        { id: 1, round: 1, home: { seed: "U1" }, away: { seed: "U4" } },
        { id: 2, round: 1, home: { seed: "U2" }, away: { seed: "U3" } },
        { id: 3, round: 2, home: { winner_of: 2 }, away: { winner_of: 1 } }
      ]
    });
  });

  it("keeps a drawn layout through a background refetch", async () => {
    // The app refetches on window focus. Re-seeding the draft from every
    // response would quietly delete a layout drawn while the organizer was
    // looking at another window.
    const client = await mount();

    await click(port("1-winner"));
    await click(slot("3-away"));
    await act(async () => {
      await client.refetchQueries();
    });
    await settle();

    expect(getStageBracketTemplate).toHaveBeenCalledTimes(2);
    expect(slot("3-away")?.textContent).toContain("W M1");
  });

  it("lists the validator's problems and points at the match each one names", async () => {
    setStageBracketTemplate.mockRejectedValue(
      new ApiError(422, [
        {
          msg: "The final must be the only match of the last upper round",
          code: "invalid_bracket_template",
          problems: [
            {
              match_id: 2,
              slot: null,
              code: "final",
              message: "The final must be the only match of the last upper round"
            }
          ]
        } as never
      ])
    );

    await mount();
    await click(button("Save"));

    const problem = button("M2: The final must be the only match of the last upper round");
    expect(problem).toBeDefined();

    // The list is a way back to the card: clicking the line marks it.
    expect(container.querySelector('[data-match-id="2"][data-highlighted]')).toBeNull();
    await click(problem);
    expect(container.querySelector('[data-match-id="2"][data-highlighted]')).not.toBeNull();
  });

  it("asks before throwing a custom layout away", async () => {
    getStageBracketTemplate.mockResolvedValue({ ...generatedTemplate(), custom: true });

    await mount();
    await click(button("Reset to generated"));

    const dialog = document.body.querySelector('[role="alertdialog"]');
    expect(dialog).not.toBeNull();
    expect(clearStageBracketTemplate).not.toHaveBeenCalled();

    await click(button("Reset to generated", dialog!));

    expect(clearStageBracketTemplate).toHaveBeenCalledWith(5);
  });

  it("refuses to edit a stage that already has matches, and says why", async () => {
    getAllEncounters.mockResolvedValue({ results: [generatedEncounter()], total: 1 });

    await mount();

    expect(container.textContent).toContain(
      "This stage already has generated matches. Delete them first to edit the bracket."
    );
    expect(button("Save")).toBeUndefined();
  });
});
