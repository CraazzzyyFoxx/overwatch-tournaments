// @vitest-environment happy-dom
//
// One claim: a stage fed by a formation edits that formation's method and draft
// format in its General card — a draft of the stage editor's own SaveBar — and
// saves them as the formation node's upsert over its whole config, in one
// `applyChanges`.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
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

const formed = (status: string) =>
  read(
    [
      node(5, "registration", "Signups"),
      { ...node(6, "formation", "Teams", { mode: "balancer", keep: "me" }), status },
      node(2, "stage", "Playoff")
    ],
    [edge(10, 5, "participants", 6, "players"), edge(11, 6, "teams", 2, "participants")]
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

describe("Stage editor · teams formed by", () => {
  it("saves the method on top of the formation node's whole config, in one applyChanges", async () => {
    await mount(formed("draft"));
    expect(byText("button", "Save changes")).toBeUndefined();

    await click(labelled("Teams formed by")!);
    await click(byText('[role="option"]', "Draft")!);
    await save();

    expect(applyChanges).toHaveBeenCalledTimes(1);
    expect(applyChanges).toHaveBeenCalledWith(84, {
      nodes: [{ id: 6, kind: "formation", name: "Teams", config: { mode: "draft", keep: "me" } }]
    });
  });

  it("adds the draft format row in Draft mode and saves it with the method", async () => {
    await mount(formed("draft"));

    await click(labelled("Teams formed by")!);
    await click(byText('[role="option"]', "Draft")!);
    await click(byText("button", "Linear")!);
    await save();

    expect(applyChanges).toHaveBeenCalledWith(84, {
      nodes: [
        {
          id: 6,
          kind: "formation",
          name: "Teams",
          config: {
            mode: "draft",
            keep: "me",
            draft_format: { format: "linear", round_rules: [], avg_tie_seed_reverse: false }
          }
        }
      ]
    });
  });

  it("locks the method with a visible reason once the formation left draft", async () => {
    await mount(formed("forming"));

    expect(labelled("Teams formed by")?.hasAttribute("disabled")).toBe(true);
    expect(document.body.textContent).toContain(en.adminBracket.feed.formationModeLocked);
  });
});
