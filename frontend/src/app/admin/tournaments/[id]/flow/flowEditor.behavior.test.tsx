// @vitest-environment happy-dom
//
// The Flow tab (§13.1): a palette add becomes a draft node that the dry run
// sees under its ref, Save sends exactly the diff, and the issues panel names
// the node an issue belongs to. The canvas and the inspector are stubbed: this
// file pins the editor's state, not xyflow's drawing.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { starterRead } from "@/lib/flow/fixtures";

import { FlowEditor } from "./FlowEditor";
import { VALIDATE_DEBOUNCE_MS } from "./useFlowEditor";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SEEDS = {
  registration: { check_in: false, intake: "solo" },
  formation: { mode: "manual" },
  stage: {},
  filter: { mode: "top", n: 1 },
  merge: {},
  split: { buckets: [{ name: "Bucket 1", size: null }], serpentine: false },
  aggregate: { unit: "players", score: { preset: "stage_points", table: {}, formula: null }, mode: "sum_all", n: null },
  leaderboard: { pins: [] }
};
let adminRead = { ...starterRead(), issues: [] as unknown[], catalogue: [], config_defaults: SEEDS };
const getAdmin = vi.fn(async () => adminRead);
const validate = vi.fn(async () => ({ issues: [], ports: [], ref_ids: {}, new_edge_ids: [] }));
const applyChanges = vi.fn(async () => starterRead());
let savedStages: { id: number; order: number }[] = [];
let canvas: { onNodesChange: (changes: unknown[]) => void };

vi.mock("@/services/flow.service", () => ({
  default: {
    getAdmin: (...a: unknown[]) => getAdmin(...(a as [])),
    validate: (...a: unknown[]) => validate(...(a as [])),
    applyChanges: (...a: unknown[]) => applyChanges(...(a as []))
  }
}));
vi.mock("@/components/flow/FlowCanvas", () => ({
  FlowCanvas: (props: { nodes: { id: string; data: { name: string } }[]; onNodesChange: (changes: unknown[]) => void }) => {
    canvas = props;
    return (
      <ul aria-label="canvas">
        {props.nodes.map((n) => (
          <li key={n.id}>{n.data.name}</li>
        ))}
      </ul>
    );
  }
}));
vi.mock("../hubQueries", () => ({
  useHubTournamentQuery: () => ({ data: { id: 7, workspace_id: 3, flow_nodes: [], stages: savedStages }, isLoading: false }),
  tabFallback: null
}));
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({ canAccessPermission: () => true, isSuperuser: false }) }));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() } }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/admin/tournaments/7/flow",
  useSearchParams: () => new URLSearchParams()
}));

let root: Root;
let container: HTMLDivElement;
const wait = (ms: number) => act(() => new Promise((r) => setTimeout(r, ms)));

async function mount() {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <FlowEditor tournamentId={7} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await wait(0);
}
const button = (name: string) =>
  [...container.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === name || b.textContent === name)!;

beforeEach(() => {
  adminRead = { ...starterRead(), issues: [], catalogue: [], config_defaults: SEEDS };
  savedStages = [];
  vi.clearAllMocks();
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("Flow tab", () => {
  it("a palette add becomes a draft node the dry run sees under its ref", async () => {
    await mount();
    await act(async () => button("Add Filter").click());
    expect(container.querySelector('[aria-label="canvas"]')!.textContent).toContain("Filter");
    await wait(VALIDATE_DEBOUNCE_MS + 50);
    const [, changes] = validate.mock.calls.at(-1) as unknown as [number, { nodes: unknown[] }];
    expect(changes.nodes).toEqual([
      expect.objectContaining({ ref: "new-1", kind: "filter", name: "Filter", config: { mode: "top", n: 1 } })
    ]);
  });

  it("Save sends exactly the diff and the editor is clean again", async () => {
    await mount();
    await act(async () => button("Add Filter").click());
    await act(async () => button("Save flow").click());
    await wait(0);
    expect(applyChanges).toHaveBeenCalledWith(7, expect.objectContaining({ delete_node_ids: [], delete_edge_ids: [] }));
    expect(button("Save flow")).toBeUndefined();
  });

  it("lists server issues with the name of the node they belong to", async () => {
    adminRead = { ...adminRead, issues: [{ code: "missing_input", severity: "warning", message: "Teams has no input", node_id: 2, edge_id: null }] };
    await mount();
    expect(container.textContent).toContain("Teams has no input");
    expect(button("Teams")).toBeDefined();
  });

  it("a palette stage takes the phase after the saved stages", async () => {
    const read = starterRead();
    (read.nodes as unknown[]).push({ id: 3, kind: "stage", name: "Groups", status: "draft", config: {}, stage_id: 40, position_x: 520, position_y: 0, ports: [] });
    adminRead = { ...adminRead, ...read };
    savedStages = [{ id: 40, order: 3 }];
    await mount();
    await act(async () => button("Add Stage").click());
    await wait(VALIDATE_DEBOUNCE_MS + 50);
    const [, changes] = validate.mock.calls.at(-1) as unknown as [number, { nodes: { stage?: { order: number } }[] }];
    expect(changes.nodes[0].stage?.order).toBe(4);
  });

  it("asks before Save deletes a saved lifecycle node, naming what goes with it", async () => {
    await mount();
    await act(async () => canvas.onNodesChange([{ type: "remove", id: "2" }]));
    await act(async () => button("Save flow").click());

    expect(applyChanges).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("Delete these steps?");
    expect(document.body.textContent).toContain("Teams (formation): its balancer config, saved balances and draft sessions");

    const confirm = [...document.body.querySelectorAll("button")].find((b) => b.textContent === "Save and delete")!;
    await act(async () => confirm.click());
    expect(applyChanges).toHaveBeenCalledWith(7, expect.objectContaining({ delete_node_ids: [2] }));
  });

  it("saves a pure-node deletion without asking", async () => {
    await mount();
    await act(async () => button("Add Filter").click());
    await act(async () => canvas.onNodesChange([{ type: "remove", id: "new-1" }]));
    expect(button("Save flow")).toBeUndefined();
  });
});
