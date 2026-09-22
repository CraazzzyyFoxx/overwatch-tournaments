// @vitest-environment happy-dom
//
// One claim: a double-elimination stage's best-of can be set per BRACKET.
//
// Double elimination numbers its rounds by sign — upper bracket 1..U, grand
// final U+1, lower bracket -1..-L. The editor used to render a flat
// `Round 1..max_rounds` list, which could reach neither a lower-bracket round
// (its keys are negative) nor say which bracket a positive round meant. An
// organizer who wanted "Bo5 in the upper bracket only" had `default` as the only
// knob that visibly worked, and that lengthens every match in both brackets.
//
// The rows here are pinned against `double_elimination.generate`: an 8-team
// bracket really does emit upper 1..3, lower -1..-4 and round 4 for the grand
// final.
//
// Carried over from `stageManager.bestOf.behavior.test.tsx` when PR-2e split
// `StageManager` into the Bracket tab: same claims, now driven through
// `?stage=&section=best-of` and saved by `SaveBar` instead of the "Advanced"
// disclosure and its "Save override" button.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Stage } from "@/types/tournament.types";

import BracketTabPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getStages = vi.fn();
const getTournament = vi.fn();
const getStagesProgress = vi.fn();
const updateStage = vi.fn();
const getTeams = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getStages: (...args: unknown[]) => getStages(...args),
    getTournament: (...args: unknown[]) => getTournament(...args),
    getStagesProgress: (...args: unknown[]) => getStagesProgress(...args),
    updateStage: (...args: unknown[]) => updateStage(...args),
    applyStageBestOf: vi.fn()
  }
}));

vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isSuperuser: true })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

// `SaveBar` and `EntityFormDialog` guard navigation with the app router, and
// `AdminTabs` renders `next/link` — neither context exists in a test tree.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/tournaments/84/bracket",
  useParams: () => ({ id: "84" }),
  useSearchParams: () => new URLSearchParams("stage=10&section=best-of")
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: unknown }) => (
    <a href={href} {...rest}>
      {children as never}
    </a>
  )
}));

vi.mock("@/lib/tournament/workspace-query-keys", () => ({
  invalidateTournamentWorkspace: vi.fn()
}));

/** An 8-team double elimination in one `single_bracket` item — the reported setup. */
function singleBracketStage(seededTeams = 8): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "Playoff",
    description: null,
    stage_type: "double_elimination",
    max_rounds: 5,
    advance_count: null,
    split_lower_bracket: false,
    order: 1,
    is_active: true,
    is_completed: false,
    settings_json: {},
    challonge_id: null,
    challonge_slug: null,
    items: [
      {
        id: 100,
        stage_id: 10,
        name: "Bracket",
        type: "single_bracket",
        order: 0,
        inputs: Array.from({ length: seededTeams }, (_, index) => ({
          id: 200 + index,
          stage_item_id: 100,
          slot: index + 1,
          input_type: "final",
          team_id: index + 1,
          winner_from_stage_item_id: null,
          winner_position: null,
          team: null
        }))
      }
    ]
  } as unknown as Stage;
}

let container: HTMLDivElement;
let root: Root;

async function settle(times = 12) {
  for (let index = 0; index < times; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount(stage: Stage) {
  getStages.mockResolvedValue([stage]);
  getTournament.mockResolvedValue({ id: 84, name: "Cup" });
  getStagesProgress.mockResolvedValue([]);
  getTeams.mockResolvedValue({ results: [] });

  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <BracketTabPage />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    (element as HTMLElement).click();
  });
  await settle(4);
}

// Radix's Select reaches for pointer-capture and scroll APIs happy-dom does not
// implement. Without these the trigger throws before the listbox ever opens.
for (const [name, value] of Object.entries({
  hasPointerCapture: () => false,
  setPointerCapture: () => undefined,
  releasePointerCapture: () => undefined,
  scrollIntoView: () => undefined
})) {
  if (!(name in Element.prototype)) {
    Object.defineProperty(Element.prototype, name, { value, writable: true });
  }
}

/** Pick `option` from the currently open Select listbox. */
async function choose(option: string) {
  const items = [...document.querySelectorAll<HTMLElement>('[role="option"]')].filter(
    (element) => (element.textContent ?? "").trim() === option
  );
  if (items.length === 0) throw new Error(`no option named "${option}" is offered`);
  await click(items[0]);
}

/** Every button in the document, portalled popovers included. */
function byName(name: string): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>("button")].filter(
    (element) => (element.textContent ?? "").trim() === name
  );
}

function only(name: string): HTMLElement {
  const matches = byName(name);
  if (matches.length === 0) throw new Error(`no control named "${name}"`);
  return matches[0];
}

/** The best-of section, addressed by its heading. */
function bestOfPanel(): HTMLElement {
  const heading = [...container.querySelectorAll("h3")].find(
    (element) => (element.textContent ?? "").trim() === "Best-of per round"
  );
  const found = heading?.parentElement?.parentElement;
  if (!(found instanceof HTMLElement)) throw new Error("best-of section is not rendered");
  return found;
}

/** Bracket heading -> the round labels it offers, in order. */
function roundLabelsBySection(): Record<string, string[]> {
  const sections: Record<string, string[]> = {};
  for (const heading of bestOfPanel().querySelectorAll("h4")) {
    const grid = heading.nextElementSibling;
    sections[(heading.textContent ?? "").trim()] = [
      ...(grid?.querySelectorAll("label") ?? [])
    ].map((label) => (label.textContent ?? "").trim());
  }
  return sections;
}

/** The select trigger under the round labelled `label`. */
function roundSelect(label: string): HTMLElement {
  const found = [...bestOfPanel().querySelectorAll("label")].find(
    (element) => (element.textContent ?? "").trim() === label
  );
  const trigger = found?.parentElement?.querySelector("button");
  if (!(trigger instanceof HTMLElement)) throw new Error(`no select for round "${label}"`);
  return trigger;
}

beforeEach(() => {
  vi.clearAllMocks();
  if (root) {
    // Unmounting rather than clearing the body: the selects portal their
    // content, and React still owns those nodes.
    act(() => root.unmount());
    container.remove();
  }
  updateStage.mockResolvedValue(singleBracketStage());
});

describe("Stage editor best-of, double elimination", () => {
  it("groups the rounds by bracket instead of one flat list", async () => {
    await mount(singleBracketStage());

    expect(roundLabelsBySection()).toEqual({
      "Upper bracket": ["UB Round 1", "UB Semifinal", "UB Final"],
      "Lower bracket": ["LB Round 1", "LB Round 2", "LB Round 3", "LB Final"]
    });
  });

  it("names the grand final knob so it is not read as 'the last round of both'", async () => {
    await mount(singleBracketStage());

    const labels = [...bestOfPanel().querySelectorAll("label")].map((element) =>
      (element.textContent ?? "").trim()
    );
    expect(labels).toContain("Grand Final");
    expect(labels).not.toContain("Final");
  });

  it("writes upper-bracket rounds and the grand final without touching the lower bracket", async () => {
    await mount(singleBracketStage());

    // The reported ask: Bo5 in upper rounds 2 and 3 and the grand final, lower
    // bracket untouched.
    for (const label of ["UB Semifinal", "UB Final"]) {
      await click(roundSelect(label));
      await choose("Bo5");
    }
    await click(roundSelect("Grand Final"));
    await choose("Bo5");
    await click(only("Save changes"));

    expect(updateStage).toHaveBeenCalledTimes(1);
    const [stageId, payload] = updateStage.mock.calls[0] as [
      number,
      { settings_json: { best_of: { by_round?: Record<string, number>; final?: number } } }
    ];
    expect(stageId).toBe(10);
    // Upper rounds 2 and 3 by number; the grand final via `final`, which the
    // server resolves to the max round and which outranks `by_round`.
    expect(payload.settings_json.best_of).toEqual({ by_round: { "2": 5, "3": 5 }, final: 5 });
    // Nothing negative: every lower-bracket round keeps the stage default.
    expect(
      Object.keys(payload.settings_json.best_of.by_round ?? {}).filter((key) => Number(key) < 0)
    ).toEqual([]);
  });

  it("reaches a lower-bracket round, which a positive-only list could not address", async () => {
    await mount(singleBracketStage());

    await click(roundSelect("LB Final"));
    await choose("Bo5");
    await click(only("Save changes"));

    const [, payload] = updateStage.mock.calls[0] as [
      number,
      { settings_json: { best_of: { by_round?: Record<string, number> } } }
    ];
    // LB Final is round -4 in an 8-team bracket, per `double_elimination.generate`.
    expect(payload.settings_json.best_of.by_round).toEqual({ "-4": 5 });
  });

  it("offers the bracket it is about to build before any team is seeded", async () => {
    await mount(singleBracketStage(0));

    // No seeds means no team count to derive from, so the rows fall back to
    // max_rounds (5, which counts the grand final) rather than disappearing.
    expect(roundLabelsBySection()["Upper bracket"]).toEqual([
      "UB Round 1",
      "UB Round 2",
      "UB Semifinal",
      "UB Final"
    ]);
  });
});
