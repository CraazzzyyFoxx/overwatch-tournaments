// @vitest-environment happy-dom
//
// One claim: what the Settings tab offers for best-of.
//
// An elimination bracket's best-of is set where the tree is — the Bracket tab's
// round headers — so Settings has no Best-of card for it. Every other format
// plays one length everywhere: a single "All matches" select, and whatever
// per-round / final override the saved stage carries is cleared on save, since
// nothing in that editor could reach it and it would silently beat the default.
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
const getStagePlannedRounds = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getStages: (...args: unknown[]) => getStages(...args),
    getTournament: (...args: unknown[]) => getTournament(...args),
    getStagesProgress: (...args: unknown[]) => getStagesProgress(...args),
    updateStage: (...args: unknown[]) => updateStage(...args),
    applyStageBestOf: vi.fn(),
    // The page also draws the bracket preview on the Bracket tab; these claims
    // are about Settings.
    getStageBracketPreview: vi.fn().mockResolvedValue([]),
    // The rounds the engine says the stage has; empty means "not known yet",
    // which falls the editor back to the team-count formula.
    getStagePlannedRounds: (...args: unknown[]) => getStagePlannedRounds(...args)
  }
}));

vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ canAccessPermission: () => true, isSuperuser: true })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

// `SaveBar` and `EntityFormDialog` guard navigation with the app router, and
// `LinkTabs` renders `next/link` — neither context exists in a test tree.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/tournaments/84/bracket",
  useParams: () => ({ id: "84" }),
  useSearchParams: () => new URLSearchParams("stage=10")
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    prefetch: _prefetch,
    ...rest
  }: {
    href: string;
    children: unknown;
    prefetch?: boolean | null;
  }) => (
    <a href={href} {...rest}>
      {children as never}
    </a>
  )
}));

// Partial: the Settings page's bracket preview and round schedule observe
// `useHubEncountersQuery`, which reads the real key factory from this module.
vi.mock("@/lib/tournament/workspace-query-keys", async (importOriginal) => ({
  ...((await importOriginal()) as object),
  invalidateTournamentWorkspace: vi.fn()
}));

/** A stage in the reported setup's shape; Settings is its default section. */
function stageOf(
  stageType: "round_robin" | "double_elimination",
  bestOf: Stage["best_of"] = { default: 3, by_round: {}, final: null, swiss_qualify: null, swiss_eliminate: null }
): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "Playoff",
    description: null,
    stage_type: stageType,
    max_rounds: 5,
    order: 1,
    node_id: 1,
    status: "live",
    ranking_preset: null,
    tiebreak_order: null,
    scoring: {
      win: null,
      draw: null,
      loss: null,
      preset: "points",
      columns: [{ key: "score", label: "Счёт", public: true, better: "higher" }],
      placement_points: [],
      formula: "score"
    },
    swiss_bye_points: null,
    swiss_qualify_wins: null,
    swiss_eliminate_losses: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: bestOf,
    challonge_id: null,
    challonge_slug: null,
    items: []
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
  getStagePlannedRounds.mockResolvedValue([]);

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

/** The labels of every Settings field, the controls an organizer can reach. */
function settingsLabels(): string[] {
  return [...container.querySelectorAll("label")].map((element) => (element.textContent ?? "").trim());
}

/** The select trigger the label `label` names. */
function selectFor(label: string): HTMLElement {
  const found = [...container.querySelectorAll("label")].find(
    (element) => (element.textContent ?? "").trim() === label
  );
  const trigger = found?.htmlFor ? document.getElementById(found.htmlFor) : null;
  if (!(trigger instanceof HTMLElement)) throw new Error(`no select for "${label}"`);
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
  updateStage.mockResolvedValue(stageOf("round_robin"));
});

describe("Stage editor best-of in Settings", () => {
  it("leaves an elimination bracket's best-of to the Bracket tab", async () => {
    await mount(stageOf("double_elimination"));

    // Sanity: this is the Settings page, so the stage's own fields are there.
    expect(settingsLabels()).toContain("Format");
    expect(settingsLabels()).not.toContain("All matches");
    expect(container.textContent).not.toContain("Apply to existing matches");
  });

  it("sets one length for every match of a round robin", async () => {
    await mount(stageOf("round_robin"));

    // One select, not a per-round grid and not a final override.
    expect(settingsLabels()).toContain("All matches");
    expect(settingsLabels()).not.toContain("Final");
    expect(settingsLabels().filter((label) => /^Round \d+$/.test(label))).toEqual([]);

    await click(selectFor("All matches"));
    await choose("Bo5");
    await click(only("Save changes"));

    expect(updateStage).toHaveBeenCalledTimes(1);
    const [stageId, payload] = updateStage.mock.calls[0] as [number, { best_of: unknown }];
    expect(stageId).toBe(10);
    expect(payload.best_of).toEqual({
      default: 5,
      by_round: {},
      final: null,
      swiss_qualify: null,
      swiss_eliminate: null
    });
  });

  it("clears a per-round override the stage carried from another format", async () => {
    // A stage that was an elimination bracket and is a round robin now: the
    // overrides are unreachable here and would silently beat the default.
    await mount(
      stageOf("round_robin", {
        default: 3,
        by_round: { "1": 5 },
        final: 7,
        swiss_qualify: null,
        swiss_eliminate: null
      })
    );

    await click(selectFor("All matches"));
    await choose("Bo1");
    await click(only("Save changes"));

    const [, payload] = updateStage.mock.calls[0] as [number, { best_of: unknown }];
    expect(payload.best_of).toEqual({
      default: 1,
      by_round: {},
      final: null,
      swiss_qualify: null,
      swiss_eliminate: null
    });
  });
});
