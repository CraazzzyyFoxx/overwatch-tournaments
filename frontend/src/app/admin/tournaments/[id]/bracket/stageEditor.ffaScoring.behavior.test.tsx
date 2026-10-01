// @vitest-environment happy-dom
//
// One claim: an FFA league's own scoring rule is editable, and it is saved for
// an FFA stage ONLY.
//
// The rule is three things the organizer writes: the columns entered per game
// (`kills`, `deaths`), the points a place pays, and the formula that turns both
// into a game's points. A preset is a starting point, not the rule — the
// organizer's real rule ("silver is worth 7 here, and deaths cost us") has to
// survive the save, which is pinned below through the REAL update mutation
// rather than through a number changing in a field.
//
// The formula is the one field of this editor the server can reject by
// POSITION, so the rejection is pinned too: it has to land on the formula
// field, naming what it stumbled over, not vanish into a toast.
//
// The rest of the editor has to agree that a lobby is not a duel: no
// win/draw/loss points (there is no opponent to beat), no Buchholz (there is no
// pairing to weigh), and the best-of knob renamed to what it actually sets
// there — how many games the lobby plays.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/error";
import en from "@/i18n/messages/en.json";
import type { StageUpdateInput } from "@/types/admin.types";
import type { Stage, StageRegulation, StageType } from "@/types/tournament.types";

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

// The section under test is chosen by `?section=`, so the query string is a
// per-test input rather than a constant.
let currentSearch = "stage=10&section=ffa-scoring";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/tournaments/84/bracket",
  useParams: () => ({ id: "84" }),
  useSearchParams: () => new URLSearchParams(currentSearch)
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: unknown }) => (
    <a href={href} {...rest}>
      {children as never}
    </a>
  )
}));

// Partial: the General section's bracket preview observes
// `useHubEncountersQuery`, which reads the real key factory from this module.
vi.mock("@/lib/tournament/workspace-query-keys", async (importOriginal) => ({
  ...((await importOriginal()) as object),
  invalidateTournamentWorkspace: vi.fn()
}));

// Radix's Checkbox measures its hidden form input, and the Select reaches for
// pointer-capture APIs happy-dom does not implement.
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
if (!("ResizeObserver" in globalThis)) {
  Object.defineProperty(globalThis, "ResizeObserver", {
    writable: true,
    value: class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  });
}

function stage(stageType: StageType, regulation: Partial<StageRegulation> = {}): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "League",
    description: null,
    stage_type: stageType,
    max_rounds: 5,
    advance_count: 2,
    advance_upper_count: null,
    order: 0,
    is_active: true,
    is_published: false,
    is_completed: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null },
    swiss_bye_points: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null },
    ffa_scoring: {
      columns: [{ key: "score", label: "Score", public: true, better: "higher" }],
      placement_points: [],
      formula: "score"
    },
    ...regulation,
    challonge_id: null,
    challonge_slug: null,
    items: []
  };
}

/** A rule left behind by a stage that used to be an FFA league. */
const SAVED_SCORING = {
  columns: [{ key: "kills", label: "Kills", public: true, better: "higher" as const }],
  placement_points: [10, 6],
  formula: "place_pts + kills"
};

/** What the server answers when the formula names a column that is not there.
 *  `place_pts + ` is twelve characters, so `kils` starts at offset 12 — where
 *  the parser (`shared/domain/ffa_formula.py`) reports it, 0-based. */
function unknownNameRejection(): ApiError {
  return new ApiError(
    422,
    [{ msg: "Unknown name `kils`", code: "ffa_formula_unknown_name", field: "ffa_scoring.formula" }],
    {
      detail: "ffa_scoring.formula: Unknown name `kils`",
      code: "unprocessable_entity",
      fields: [
        {
          field: "ffa_scoring.formula",
          msg: "Unknown name `kils`",
          code: "ffa_formula_unknown_name",
          offset: 12,
          name: "kils"
        }
      ]
    }
  );
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

async function mount(current: Stage, section = "ffa-scoring") {
  currentSearch = `stage=10&section=${section}`;
  getStages.mockResolvedValue([current]);
  getTournament.mockResolvedValue({ id: 84, name: "Cup" });
  getStagesProgress.mockResolvedValue([]);
  getTeams.mockResolvedValue({ results: [] });
  updateStage.mockResolvedValue(current);

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

async function type(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype =
    input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

/** The `<textarea>` a `<label>` points at. */
function area(label: string): HTMLTextAreaElement {
  const found = [...container.querySelectorAll("label")].find(
    (element) => (element.textContent ?? "").trim() === label
  );
  const input = found?.htmlFor ? document.getElementById(found.htmlFor) : null;
  if (!(input instanceof HTMLTextAreaElement)) throw new Error(`no textarea labelled "${label}"`);
  return input;
}

/** The message a field points at through `aria-errormessage`. */
function errorFor(element: Element): string {
  const id = element.getAttribute("aria-errormessage");
  const node = id ? document.getElementById(id) : null;
  return (node?.textContent ?? "").trim();
}

/** The checkbox with this exact `aria-label`. */
function box(label: string): HTMLElement {
  const found = container.querySelector<HTMLElement>(`[role="checkbox"][aria-label="${label}"]`);
  if (!found) throw new Error(`no checkbox labelled "${label}"`);
  return found;
}

/** Every `<label>` the open section renders, in order. */
function labels(): string[] {
  return [...container.querySelectorAll("label")].map((element) =>
    (element.textContent ?? "").trim()
  );
}

/** The field a `<label>` points at, portalled popovers excluded. */
function field(label: string): HTMLInputElement {
  const found = [...container.querySelectorAll("label")].find(
    (element) => (element.textContent ?? "").trim() === label
  );
  const input = found?.htmlFor ? document.getElementById(found.htmlFor) : null;
  if (!(input instanceof HTMLInputElement)) throw new Error(`no field labelled "${label}"`);
  return input;
}

/** The select trigger a `<label>` points at. */
function select(label: string): HTMLElement {
  const found = [...container.querySelectorAll("label")].find(
    (element) => (element.textContent ?? "").trim() === label
  );
  const trigger = found?.htmlFor ? document.getElementById(found.htmlFor) : null;
  if (!(trigger instanceof HTMLElement)) throw new Error(`no select labelled "${label}"`);
  return trigger;
}

/** The options the currently open Select listbox offers, in order. */
function options(): string[] {
  return [...document.querySelectorAll<HTMLElement>('[role="option"]')].map((element) =>
    (element.textContent ?? "").trim()
  );
}

async function choose(option: string) {
  const items = [...document.querySelectorAll<HTMLElement>('[role="option"]')].filter(
    (element) => (element.textContent ?? "").trim() === option
  );
  if (items.length === 0) throw new Error(`no option named "${option}" is offered`);
  await click(items[0]);
}

/** The one button with this exact label, portalled popovers included. An icon
 *  button says its name in `aria-label` instead of in text. */
function only(name: string): HTMLElement {
  const matches = [...document.querySelectorAll<HTMLElement>("button")].filter(
    (element) =>
      (element.textContent ?? "").trim() === name || element.getAttribute("aria-label") === name
  );
  if (matches.length === 0) throw new Error(`no control named "${name}"`);
  return matches[0];
}

async function save() {
  const button = [...document.querySelectorAll<HTMLElement>("button")].find(
    (element) => (element.textContent ?? "").trim() === "Save changes"
  );
  if (!button) throw new Error("no save control");
  await click(button);
}

function payload(): StageUpdateInput {
  const [, sent] = updateStage.mock.calls[0] as [number, StageUpdateInput];
  return sent;
}

/** The metrics the tiebreakers section offers at all, evaluated or not. */
function offeredMetrics(): string[] {
  return [...document.querySelectorAll<HTMLElement>('[role="checkbox"][aria-label^="Use "]')].map(
    (element) => (element.getAttribute("aria-label") ?? "").replace(/^Use /, "")
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  if (root) {
    // Unmounting rather than clearing the body: the selects portal their
    // content, and React still owns those nodes.
    act(() => root.unmount());
    container.remove();
  }
});

describe("Stage editor, FFA league scoring", () => {
  it("saves the edited rule, not the preset it started from", async () => {
    await mount(stage("ffa_league"));

    await click(select("Scoring preset"));
    await choose("Battle royale");
    // The organizer's own rule: silver is worth 7 here, not the preset's 6, and
    // the lobby also tracks deaths — which cost points and stay off the table.
    await type(field("2nd place"), "7");
    await click(only("Add column"));
    await type(field("Column 2 key"), "deaths");
    await type(field("Column 2 label"), "Deaths");
    await click(box("Show column 2 in the table"));
    await click(select("Column 2 direction"));
    await choose("Lower is better");
    await type(area("Points formula"), "place_pts + kills - deaths");
    await save();

    expect(updateStage).toHaveBeenCalledTimes(1);
    expect(payload().ffa_scoring).toEqual({
      columns: [
        { key: "kills", label: "Kills", public: true, better: "higher" },
        { key: "deaths", label: "Deaths", public: false, better: "lower" }
      ],
      placement_points: [10, 7, 5, 4, 3, 2, 1],
      formula: "place_pts + kills - deaths"
    });
  });

  it("scores a place the preset never offered, and drops a column it did", async () => {
    await mount(stage("ffa_league"));

    await click(select("Scoring preset"));
    await choose("Score only");
    // Score-only means no placement table at all; adding a place starts one.
    await click(only("Add place"));
    await type(field("1st place"), "3");
    // And a lobby can pay for the place alone: the column goes, the formula
    // stops reading it.
    await click(only("Remove column 1"));
    await type(area("Points formula"), "place_pts");
    await save();

    expect(payload().ffa_scoring).toEqual({
      columns: [],
      placement_points: [3],
      formula: "place_pts"
    });
  });

  it("stops at ten columns", async () => {
    await mount(
      stage("ffa_league", {
        ffa_scoring: {
          columns: Array.from({ length: 10 }, (_, index) => ({
            key: `c${index}`,
            label: `C${index}`,
            public: true,
            better: "higher" as const
          })),
          placement_points: [],
          formula: "c0"
        }
      })
    );

    // Ten is what the server stores (`FFA_MAX_COLUMNS`); an eleventh would be
    // rejected after the organizer had already typed it.
    expect(only("Add column").hasAttribute("disabled")).toBe(true);
  });

  it("puts the server's refusal on the formula field", async () => {
    await mount(stage("ffa_league"));

    await type(area("Points formula"), "place_pts + kils");
    updateStage.mockRejectedValueOnce(unknownNameRejection());
    await save();

    // A formula is refused by POSITION, and a toast cannot point at one: the
    // message belongs to the field, and has to name what the server stumbled on.
    // The server counts characters from zero and the organizer from one, so the
    // position shown is the one they can actually point at in the field.
    expect(errorFor(area("Points formula"))).toBe(
      "Position 13: unknown name kils. Use a column key, place, place_pts or teams."
    );
  });

  it("keeps the block out of a stage that is not an FFA league", async () => {
    // A round robin that used to be an FFA league still stores its table; the
    // save of a round robin sends no FFA rule for a format that cannot use it.
    await mount(stage("round_robin", { ffa_scoring: SAVED_SCORING }), "general");

    await type(field("Name"), "Groups");
    await save();

    expect(payload()).not.toHaveProperty("ffa_scoring");
  });

  it("drops the FFA tiebreak order when the format stops being FFA", async () => {
    await mount(stage("ffa_league", { ffa_scoring: SAVED_SCORING }), "general");

    await click(select("Format"));
    await choose("Round Robin");
    await save();

    const sent = payload();
    expect(sent.stage_type).toBe("round_robin");
    expect(sent).not.toHaveProperty("ffa_scoring");
    // A lobby metric on a duel stage is silently dropped by the engine, so the
    // order the editor saves has to be one the new format can actually run.
    expect(sent.tiebreak_order?.filter((id) => id.startsWith("ffa_"))).toEqual([]);
  });

  it("offers a sum per column, and no metric a lobby cannot compute", async () => {
    await mount(
      stage("ffa_league", {
        ffa_scoring: {
          columns: [
            { key: "kills", label: "Kills", public: true, better: "higher" as const },
            { key: "deaths", label: "Deaths", public: false, better: "lower" as const }
          ],
          placement_points: [],
          formula: "kills * 2 - deaths"
        }
      }),
      "tiebreakers"
    );

    // The lobby's own sums are the stage's columns — including the one the
    // public table never shows, which still decides a tie.
    expect(offeredMetrics()).toEqual([
      "Points",
      "Game Wins",
      "Sum: Kills",
      "Last Placement",
      "Best Placement",
      "Sum: Deaths"
    ]);

    await click(select("Standings preset"));
    expect(options()).toEqual([
      "System default (based on type)",
      "FFA default (game wins, then score)"
    ]);
  });

  it("hides the duel-only points fields on an FFA stage", async () => {
    await mount(stage("ffa_league"), "tiebreakers");

    // Win/draw/loss points come from beating an opponent, and a Swiss bye is a
    // missing opponent — neither exists in a lobby.
    expect(labels()).not.toContain("Win points override");
    expect(labels()).not.toContain("Draw points override");
    expect(labels()).not.toContain("Loss points override");
    expect(labels()).not.toContain("Swiss bye points");
  });

  it("calls the best-of knob what it sets for a lobby", async () => {
    await mount(stage("ffa_league"), "best-of");

    expect(labels()).toContain("Games per lobby");
    // `final` resolves to the last round of a bracket; a lobby has one round.
    expect(labels()).not.toContain("Final");
    expect(labels()).not.toContain("Grand Final");

    await click(select("Games per lobby"));
    await choose("5 games");
    await save();

    expect(payload().best_of).toEqual({ default: 5, by_round: {}, final: null });
  });

  it("drops a per-round override the lobby would silently obey", async () => {
    // `by_round` survives a format change, and the lobby generator resolves its
    // games count as round 1 — which outranks the default. Left in the payload,
    // a leftover "5" from the generic grid decides the lobby instead of the
    // knob above, and no FFA control can reach it to clear it.
    await mount(
      stage("ffa_league", { best_of: { default: 3, by_round: { "1": 5 }, final: 7 } }),
      "best-of"
    );

    await click(select("Games per lobby"));
    await choose("7 games");
    await save();

    expect(payload().best_of).toEqual({ default: 7, by_round: {}, final: null });
  });
});
