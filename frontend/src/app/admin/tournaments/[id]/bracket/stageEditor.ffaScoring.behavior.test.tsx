// @vitest-environment happy-dom
//
// One claim: an FFA league's points table is editable, and it is saved for an
// FFA stage ONLY.
//
// `settings_json.ffa_scoring` is what the points adder reads
// (`shared.domain.ffa_scoring.parse_ffa_rules`): points per place, plus points
// per unit of raw score. A preset is a starting point, not the rule — the
// organizer's real table ("2nd place is worth 7 here") has to survive the save,
// which is pinned below through the REAL update mutation rather than through a
// number changing in a field.
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

import en from "@/i18n/messages/en.json";
import type { Stage, StageType } from "@/types/tournament.types";

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

function stage(stageType: StageType, settingsJson: Record<string, unknown> = {}): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "League",
    description: null,
    stage_type: stageType,
    max_rounds: 5,
    advance_count: 2,
    split_lower_bracket: false,
    order: 0,
    is_active: true,
    is_completed: false,
    settings_json: settingsJson,
    challonge_id: null,
    challonge_slug: null,
    items: []
  } as unknown as Stage;
}

/** A table left behind by a stage that used to be an FFA league. */
const SAVED_SCORING = { placement_points: [10, 6], score_points: 2, score_label: "Kills" };

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

async function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
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

/** The one button with this exact label, portalled popovers included. */
function only(name: string): HTMLElement {
  const matches = [...document.querySelectorAll<HTMLElement>("button")].filter(
    (element) => (element.textContent ?? "").trim() === name
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

function payload(): {
  stage_type: StageType;
  settings_json: Record<string, unknown> & { tiebreak_order?: string[] };
} {
  const [, sent] = updateStage.mock.calls[0] as [
    number,
    { stage_type: StageType; settings_json: Record<string, unknown> }
  ];
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
  it("saves the edited table, not the preset it started from", async () => {
    await mount(stage("ffa_league"));

    await click(select("Scoring preset"));
    await choose("Placement + score");
    // The organizer's own rule: silver is worth 7 here, not the preset's 6.
    await type(field("2nd place"), "7");
    await type(field("Score label"), "Kills");
    await save();

    expect(updateStage).toHaveBeenCalledTimes(1);
    expect(payload().settings_json.ffa_scoring).toEqual({
      placement_points: [10, 7, 5, 4, 3, 2, 1, 1],
      score_points: 1,
      score_label: "Kills"
    });
  });

  it("scores a place the preset never offered, and drops one it did", async () => {
    await mount(stage("ffa_league"));

    await click(select("Scoring preset"));
    await choose("Score only");
    // Score-only means no placement table at all; adding a place starts one.
    await click(only("Add place"));
    await type(field("1st place"), "3");
    await save();

    expect(payload().settings_json.ffa_scoring).toEqual({
      placement_points: [3],
      score_points: 1,
      score_label: null
    });
  });

  it("keeps the block out of a stage that is not an FFA league", async () => {
    // A round robin that used to be an FFA league still carries the block in
    // `settings_json`; saving it as a round robin has to drop it, or the points
    // adder reads a rule this stage no longer plays by.
    await mount(stage("round_robin", { ffa_scoring: SAVED_SCORING }), "general");

    await type(field("Name"), "Groups");
    await save();

    expect(Object.keys(payload().settings_json)).not.toContain("ffa_scoring");
  });

  it("drops the FFA tiebreak order when the format stops being FFA", async () => {
    await mount(stage("ffa_league", { ffa_scoring: SAVED_SCORING }), "general");

    await click(select("Format"));
    await choose("Round Robin");
    await save();

    const sent = payload();
    expect(sent.stage_type).toBe("round_robin");
    expect(Object.keys(sent.settings_json)).not.toContain("ffa_scoring");
    // A lobby metric on a duel stage is silently dropped by the engine, so the
    // order the editor saves has to be one the new format can actually run.
    expect(sent.settings_json.tiebreak_order?.filter((id) => id.startsWith("ffa_"))).toEqual([]);
  });

  it("offers the lobby tiebreakers, and only those", async () => {
    await mount(stage("ffa_league"), "tiebreakers");

    expect(offeredMetrics()).toEqual([
      "Points",
      "Game Wins",
      "Score",
      "Last Placement",
      "Manual Override",
      "Best Placement"
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

    expect(payload().settings_json.best_of).toEqual({ default: 5 });
  });
});
