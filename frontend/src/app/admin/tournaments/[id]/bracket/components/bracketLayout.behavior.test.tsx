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
//
// The editor is the Bracket tab's "Edit structure" mode, so it is reached the
// way an organizer reaches it: through that switch, and leaving it with an
// unsaved layout asks first.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api/error";
import { projectStage } from "@/lib/bracket/projection";
import type { BracketTemplateRead } from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
import type { Stage } from "@/types/tournament.types";

import { BracketTab } from "./BracketTab";

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
    clearStageBracketTemplate: (...args: unknown[]) => clearStageBracketTemplate(...args),
    // The View mode draws the generator's skeleton; nothing here asserts on it.
    getStageBracketPreview: vi.fn().mockResolvedValue([])
  }
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/tournaments/84/bracket",
  useSearchParams: () => new URLSearchParams("stage=5&section=layout")
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
    order: 1,
    node_id: 1,
    status: "draft",
    is_published: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null, preset: null, columns: null, placement_points: null, formula: null },
    swiss_bye_points: null,
    swiss_qualify_wins: null,
    swiss_eliminate_losses: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null, swiss_qualify: null, swiss_eliminate: null },
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
        {
          id: 1,
          round: 1,
          slots: [
            { slot: 1, seed: "U1" },
            { slot: 2, seed: "U4" }
          ]
        },
        {
          id: 2,
          round: 1,
          slots: [
            { slot: 1, seed: "U2" },
            { slot: 2, seed: "U3" }
          ]
        },
        {
          id: 3,
          round: 2,
          slots: [
            { slot: 1, source_match: 1, source_position: 1 },
            { slot: 2, source_match: 2, source_position: 1 }
          ]
        }
      ]
    }
  };
}

/** The same stage as a double elimination, so a layout has both sections. */
function deStage(): Stage {
  return { ...stage(), stage_type: "double_elimination", max_rounds: 3 };
}

/** Upper R1, two lower rounds, grand final — one column per section to add to. */
function deTemplate(): BracketTemplateRead {
  return {
    custom: false,
    seeds: { upper: 2, lower: 2 },
    template: {
      version: 1,
      upper_seeds: 2,
      lower_seeds: 2,
      matches: [
        {
          id: 1,
          round: 1,
          slots: [
            { slot: 1, seed: "U1" },
            { slot: 2, seed: "U2" }
          ]
        },
        {
          id: 2,
          round: -1,
          slots: [
            { slot: 1, seed: "L1" },
            { slot: 2, seed: "L2" }
          ]
        },
        {
          id: 3,
          round: -2,
          slots: [
            { slot: 1, source_match: 2, source_position: 1 },
            { slot: 2, source_match: 1, source_position: 2 }
          ]
        },
        {
          id: 4,
          round: 2,
          slots: [
            { slot: 1, source_match: 1, source_position: 1 },
            { slot: 2, source_match: 3, source_position: 1 }
          ]
        }
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
    played_at: null,
    is_live: false,
    is_final: false,
    current_map_index: null,
    confirmed_at: null,
    slot_count: 2,
    result_source: null,
    result_version: 1,
    games: [],
    teams: [
      { id: 91, slot: 1, team_id: 1, name: "Team 1", seed: 1, score: 0, placement: null, active: true },
      { id: 92, slot: 2, team_id: 4, name: "Team 4", seed: 4, score: 0, placement: null, active: true }
    ],
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

async function mount(current: Stage = stage(), { edit = true } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  root = createRoot(container);
  await act(async () => {
    root!.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <BracketTab
            stage={current}
            projection={projectStage({
              stage: current,
              stageType: current.stage_type,
              maxRounds: current.max_rounds,
              bestOf: current.best_of
            })}
            teams={[]}
            onBestOfSaved={vi.fn()}
          />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  if (edit) await click(button("Edit structure"));
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

    // Swap the final's feeders: W(M1) into slot 2, which empties the slot 1 it
    // used to hold, then W(M2) into the slot it vacated.
    await click(port("1-winner"));
    await click(slot("3-2"));
    await click(port("2-winner"));
    await click(slot("3-1"));
    await click(button("Save"));

    expect(setStageBracketTemplate).toHaveBeenCalledWith(5, {
      version: 1,
      upper_seeds: 4,
      lower_seeds: 0,
      matches: [
        {
          id: 1,
          round: 1,
          slots: [
            { slot: 1, seed: "U1" },
            { slot: 2, seed: "U4" }
          ]
        },
        {
          id: 2,
          round: 1,
          slots: [
            { slot: 1, seed: "U2" },
            { slot: 2, seed: "U3" }
          ]
        },
        {
          id: 3,
          round: 2,
          slots: [
            { slot: 1, source_match: 2, source_position: 1 },
            { slot: 2, source_match: 1, source_position: 1 }
          ]
        }
      ]
    });
  });

  it("keeps a drawn layout through a background refetch", async () => {
    // The app refetches on window focus. Re-seeding the draft from every
    // response would quietly delete a layout drawn while the organizer was
    // looking at another window.
    const client = await mount();

    await click(port("1-winner"));
    await click(slot("3-2"));
    await act(async () => {
      await client.refetchQueries();
    });
    await settle();

    expect(getStageBracketTemplate).toHaveBeenCalledTimes(2);
    expect(slot("3-2")?.textContent).toContain("W M1");
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

  it("adds a match to the column its button sits on, upper or lower", async () => {
    // The round a column adds to comes from the layout, not from parsing its
    // header's id: `upper-header-2` reads as -2 to a regex, which silently put
    // every new upper match in the lower bracket.
    getStageBracketTemplate.mockImplementation(() => Promise.resolve(deTemplate()));

    await mount(deStage());

    // Layout order: upper columns, then lower columns, then the finals.
    const headers = Array.from(container.querySelectorAll<HTMLElement>("[data-add-match]")).map(
      (addButton) => addButton.parentElement as HTMLElement
    );
    const upperHeader = headers[0];
    const lowerHeader = headers[1];

    await click(upperHeader.querySelector("[data-add-match]"));
    const added = container.querySelector<HTMLElement>('[data-match-id="5"]');
    expect(added?.style.left).toBe(upperHeader.style.left);
    // Same section, not merely the same column: the upper band sits above the
    // lower header, which is where the misparsed round used to land it.
    expect(parseFloat(added!.style.top)).toBeLessThan(parseFloat(lowerHeader.style.top));

    await click(lowerHeader.querySelector("[data-add-match]"));
    const addedLower = container.querySelector<HTMLElement>('[data-match-id="6"]');
    expect(addedLower?.style.left).toBe(lowerHeader.style.left);
    expect(parseFloat(addedLower!.style.top)).toBeGreaterThan(parseFloat(lowerHeader.style.top));
  });

  it("deletes a match from its card menu", async () => {
    // The menu is portaled, yet React bubbles its pointerdown to the canvas.
    // Taken as the start of a pan, the canvas captured the pointer and the
    // browser never delivered the click to "Delete".
    const capture = vi.fn();
    const original = Element.prototype.setPointerCapture;
    Element.prototype.setPointerCapture = capture;
    try {
      await mount();
      const pointerDown = (element: Element) =>
        act(async () => {
          element.dispatchEvent(
            new PointerEvent("pointerdown", { bubbles: true, cancelable: true, button: 0, pointerType: "mouse" })
          );
        });

      await pointerDown(container.querySelector('[aria-label="Match 3 actions"]')!);
      await settle();
      const remove = Array.from(document.body.querySelectorAll('[role="menuitem"]')).find(
        (item) => item.textContent?.trim() === "Delete"
      );
      expect(remove).toBeDefined();

      await pointerDown(remove!);
      expect(capture).not.toHaveBeenCalled();
      await click(remove);

      expect(container.querySelector('[data-match-id="3"]')).toBeNull();
    } finally {
      Element.prototype.setPointerCapture = original;
    }
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
    expect(button("Edit structure")?.disabled).toBe(true);
    expect(button("Save")).toBeUndefined();
  });

  it("asks before leaving the editor with an unsaved layout", async () => {
    await mount();
    await click(port("1-winner"));
    await click(slot("3-2"));

    // Leaving with the draft unsaved asks; declining keeps the editor and the wiring.
    await click(button("View"));
    const dialog = () => document.body.querySelector('[role="alertdialog"]');
    expect(dialog()).not.toBeNull();
    await click(button("Cancel", dialog()!));
    expect(slot("3-2")?.textContent).toContain("W M1");

    // Discarding goes back to the saved layout.
    await click(button("View"));
    await click(button("Discard", dialog()!));
    expect(port("1-winner")).toBeNull();
    await click(button("Edit structure"));
    expect(slot("3-1")?.textContent).toContain("W M1");
    expect(setStageBracketTemplate).not.toHaveBeenCalled();
  });
});
