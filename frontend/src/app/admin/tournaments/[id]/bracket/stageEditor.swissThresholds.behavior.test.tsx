// @vitest-environment happy-dom
//
// One claim: a Swiss stage's auto-qualify / auto-eliminate thresholds and the
// best-of of their decisive matches survive a save, and a threshold switched
// off is sent as null — its decisive best-of with it, since `best_of` is
// replaced whole on the server.
//
// Pinned through the REAL save mutation (`adminService.updateStage`): the claim
// is about the payload, not about a switch changing colour.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Stage, StageItem } from "@/types/tournament.types";

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
    applyStageBestOf: vi.fn(),
    getStagePlannedRounds: vi.fn().mockResolvedValue([])
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

// Radix's Switch measures its hidden form input, and the Select reaches for
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

/** One group of `size` empty slots. */
function group(size: number): StageItem {
  return {
    id: 100,
    stage_id: 10,
    name: "Group A",
    type: "group",
    order: 0,
    inputs: Array.from({ length: size }, (_, index) => ({
      id: 500 + index,
      stage_item_id: 100,
      slot: index + 1,
      input_type: "empty" as const,
      team_id: null,
      source_result_id: null
    }))
  };
}

function swissStage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "Swiss",
    description: null,
    stage_type: "swiss",
    max_rounds: 5,
    order: 0,
    node_id: 1,
    status: "live",
    is_published: false,
    has_custom_bracket: false,
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
    swiss_qualify_wins: 3,
    swiss_eliminate_losses: 3,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 1, by_round: {}, final: null, swiss_qualify: 3, swiss_eliminate: 5 },
    challonge_id: null,
    challonge_slug: null,
    items: [],
    ...overrides
  };
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
  updateStage.mockResolvedValue(stage);

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

/** Types into a controlled input the way React hears it. */
async function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

/** The control a settings row's label names. */
function labelled(label: string): HTMLElement {
  const element = [...document.querySelectorAll("label")].find(
    (candidate) => (candidate.textContent ?? "").trim() === label
  );
  const control = element ? document.getElementById(element.htmlFor) : null;
  if (!control) throw new Error(`no control labelled "${label}"`);
  return control;
}

function countInput(label: string): HTMLInputElement | null {
  return document.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`);
}

async function save() {
  const button = [...document.querySelectorAll<HTMLElement>("button")].find(
    (element) => (element.textContent ?? "").trim() === "Save changes"
  );
  if (!button) throw new Error("no save control");
  await click(button);
}

function payload(): Partial<Stage> {
  const [, sent] = updateStage.mock.calls[0] as [number, Partial<Stage>];
  return sent;
}

beforeEach(() => {
  vi.clearAllMocks();
  if (root) {
    act(() => root.unmount());
    container.remove();
  }
});

describe("Stage editor Swiss thresholds", () => {
  it("round-trips both thresholds and both decisive best-ofs", async () => {
    await mount(swissStage());

    await type(countInput("Wins to qualify")!, "4");
    await save();

    expect(updateStage).toHaveBeenCalledTimes(1);
    expect(payload()).toMatchObject({ swiss_qualify_wins: 4, swiss_eliminate_losses: 3 });
    expect(payload().best_of).toEqual({
      default: 1,
      by_round: {},
      final: null,
      swiss_qualify: 3,
      swiss_eliminate: 5
    });
  });

  it("sends a switched-off threshold as null, its decisive best-of included", async () => {
    await mount(swissStage());

    await click(labelled("Auto-qualify after N wins"));
    expect(countInput("Wins to qualify")).toBeNull();
    await save();

    expect(payload()).toMatchObject({ swiss_qualify_wins: null, swiss_eliminate_losses: 3 });
    // Replaced whole: every key rides along, the switched-off one as null.
    expect(payload().best_of).toEqual({
      default: 1,
      by_round: {},
      final: null,
      swiss_qualify: null,
      swiss_eliminate: 5
    });
  });

  it("warns when the rounds cannot reach every verdict", async () => {
    await mount(
      swissStage({
        max_rounds: 3,
        swiss_qualify_wins: null,
        swiss_eliminate_losses: null,
        items: [group(8)]
      })
    );
    expect(container.textContent).not.toContain("Not every team can reach a verdict");

    await click(labelled("Auto-qualify after N wins"));
    await click(labelled("Auto-eliminate after N losses"));

    // 3 wins / 3 losses take up to 5 rounds.
    expect(container.textContent).toContain("the stage's round cap (3) is below the 5 rounds");

    await save();
    expect(payload()).toMatchObject({ swiss_qualify_wins: 3, swiss_eliminate_losses: 3 });
  });
});
