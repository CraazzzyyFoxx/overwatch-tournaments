// @vitest-environment happy-dom
//
// One claim: «Who advances» edits the flow graph the stage is fed by — the
// filter's config, or the filter itself — in one `applyChanges` saved from the
// stage editor's own SaveBar, and shows a wiring it cannot express read-only
// with a way into Flow instead of rewriting it.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api/error";
import type { FlowRead } from "@/types/flow.types";
import type { Stage } from "@/types/tournament.types";

import BracketTabPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getStages = vi.fn();
const getAdminFlow = vi.fn();
const applyChanges = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getStages: (...args: unknown[]) => getStages(...args),
    getTournament: vi.fn().mockResolvedValue({ id: 84, name: "Cup", workspace_id: 4 }),
    getStagesProgress: vi.fn().mockResolvedValue([]),
    updateStage: vi.fn(),
    getStagePlannedRounds: vi.fn().mockResolvedValue([])
  }
}));

vi.mock("@/services/flow.service", () => ({
  default: {
    getAdmin: (...args: unknown[]) => getAdminFlow(...args),
    applyChanges: (...args: unknown[]) => applyChanges(...args)
  }
}));

vi.mock("@/services/team.service", () => ({
  default: { getAll: vi.fn().mockResolvedValue({ results: [] }) }
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ canAccessPermission: () => true, isSuperuser: true })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/tournaments/84/bracket",
  useParams: () => ({ id: "84" }),
  useSearchParams: () => new URLSearchParams("stage=20")
}));

vi.mock("next/link", () => ({
  default: ({ href, children, prefetch: _prefetch, ...rest }: { href: string; children: unknown; prefetch?: boolean | null }) => (
    <a href={href} {...rest}>
      {children as never}
    </a>
  )
}));

vi.mock("@/lib/tournament/workspace-query-keys", async (importOriginal) => ({
  ...((await importOriginal()) as object),
  invalidateTournamentWorkspace: vi.fn()
}));

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

const item = (id: number) => ({ id, stage_id: 10, name: `Group ${id}`, type: "group" as const, order: id, inputs: [] });

function stage(overrides: Partial<Stage>): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "Groups",
    description: null,
    stage_type: "round_robin",
    max_rounds: 3,
    order: 0,
    node_id: 1,
    status: "draft",
    is_published: false,
    has_custom_bracket: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null, preset: null, columns: null, placement_points: null, formula: null },
    swiss_bye_points: null,
    swiss_qualify_wins: null,
    swiss_eliminate_losses: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 1, by_round: {}, final: null, swiss_qualify: null, swiss_eliminate: null },
    challonge_id: null,
    challonge_slug: null,
    items: [],
    ...overrides
  };
}

const groups = stage({ items: [item(100), item(101)] });
const playoff = stage({ id: 20, name: "Playoff", stage_type: "double_elimination", order: 1, node_id: 2 });

const node = (id: number, kind: string, name: string, config: Record<string, unknown> = {}) => ({
  id,
  kind,
  name,
  config,
  position_x: id * 100,
  position_y: 0
});
const edge = (id: number, from: number, fromPort: string, to: number, toPort: string) => ({
  id,
  source_node_id: from,
  source_port: fromPort,
  target_node_id: to,
  target_port: toPort
});

const read = (nodes: ReturnType<typeof node>[], edges: ReturnType<typeof edge>[]) =>
  ({ nodes, edges, results: [], participants: [], issues: [] }) as unknown as FlowRead;

const filtered = read(
  [node(1, "stage", "Groups"), node(3, "filter", "Top", { mode: "per_item_top", n: 2 }), node(2, "stage", "Playoff")],
  [edge(10, 1, "ranking", 3, "ranking"), edge(11, 3, "passed", 2, "participants")]
);
const merged = read(
  [node(1, "stage", "Groups"), node(4, "merge", "Both"), node(2, "stage", "Playoff")],
  [edge(10, 1, "ranking", 4, "in"), edge(11, 4, "out", 2, "participants")]
);

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

async function mount(flow: FlowRead) {
  getStages.mockResolvedValue([groups, playoff]);
  getAdminFlow.mockResolvedValue(flow);
  applyChanges.mockResolvedValue(flow);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
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

const labelled = (label: string) => {
  const element = [...document.querySelectorAll("label")].find((candidate) => (candidate.textContent ?? "").trim() === label);
  return element ? document.getElementById(element.htmlFor) : null;
};

const byText = (selector: string, text: string) =>
  [...document.querySelectorAll<HTMLElement>(selector)].find((element) => (element.textContent ?? "").trim() === text);

async function save() {
  await click(byText("button", "Save changes")!);
}

beforeEach(() => {
  vi.clearAllMocks();
  if (root) {
    act(() => root.unmount());
    container.remove();
  }
});

describe("Stage editor · who advances", () => {
  it("rewrites only the filter's config when the count changes", async () => {
    await mount(filtered);

    await type(labelled("How many advance from each group") as HTMLInputElement, "3");
    await save();

    expect(applyChanges).toHaveBeenCalledTimes(1);
    expect(applyChanges).toHaveBeenCalledWith(84, {
      nodes: [{ id: 3, kind: "filter", name: "Top", config: { mode: "per_item_top", n: 3 } }],
      edges: []
    });
  });

  it("swaps the filter for a direct edge when everyone advances", async () => {
    await mount(filtered);

    await click(labelled("Rule")!);
    await click(byText('[role="option"]', "Everyone")!);
    await save();

    expect(applyChanges).toHaveBeenCalledWith(
      84,
      expect.objectContaining({
        edges: [{ source: 1, source_port: "ranking", target: 2, target_port: "participants" }],
        delete_edge_ids: [10, 11],
        delete_node_ids: [3]
      })
    );
  });

  it("says why in the save bar when the server refuses", async () => {
    await mount(filtered);
    applyChanges.mockRejectedValue(new ApiError(409, [{ code: "node_frozen", msg: "frozen" }]));

    await type(labelled("How many advance from each group") as HTMLInputElement, "3");
    await save();

    expect(document.querySelector('[role="alert"]')?.textContent).toBe(en.errors.flow.node_frozen);
  });

  it("shows a wiring it cannot express in words, with a link into Flow, and edits nothing", async () => {
    await mount(merged);

    expect(labelled("Rule")).toBeNull();
    expect(document.body.textContent).toContain("Merge \u201cBoth\u201d");
    expect(document.querySelector("a[href='/admin/tournaments/84/bracket/flow?node=2']")).not.toBeNull();
    expect(byText("button", "Save changes")).toBeUndefined();
  });
});
