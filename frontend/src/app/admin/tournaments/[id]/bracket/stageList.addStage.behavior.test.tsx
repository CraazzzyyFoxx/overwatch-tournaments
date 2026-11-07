// @vitest-environment happy-dom
//
// One claim: adding a stage after another asks who advances from it, and the
// stage, its filter and their edges are created by ONE flow edit — the first
// stage keeps the plain stage create, which the server wires on its own.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { FlowRead } from "@/types/flow.types";
import type { Stage } from "@/types/tournament.types";

import { StageList } from "./components/StageList";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const createStage = vi.fn();
const getAdminFlow = vi.fn();
const applyChanges = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: { createStage: (...args: unknown[]) => createStage(...args), updateStage: vi.fn() }
}));

vi.mock("@/services/flow.service", () => ({
  default: {
    getAdmin: (...args: unknown[]) => getAdminFlow(...args),
    applyChanges: (...args: unknown[]) => applyChanges(...args)
  }
}));

vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() } }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/tournaments/84/bracket",
  useSearchParams: () => new URLSearchParams()
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

const groups = {
  id: 10,
  tournament_id: 84,
  name: "Groups",
  stage_type: "round_robin",
  order: 0,
  node_id: 1,
  status: "draft",
  items: [{ id: 100 }, { id: 101 }]
} as unknown as Stage;

const groupsRead = {
  nodes: [{ id: 1, kind: "stage", name: "Groups", config: {}, stage_id: 10, position_x: 600, position_y: 40 }],
  edges: []
} as unknown as FlowRead;

const afterSave = {
  nodes: [
    ...groupsRead.nodes,
    { id: 2, kind: "filter", name: "Who advances", stage_id: null },
    { id: 3, kind: "stage", name: "Playoff", stage_id: 20 }
  ],
  edges: []
} as unknown as FlowRead;

let container: HTMLDivElement;
let root: Root;
const onSelect = vi.fn();

async function settle(times = 8) {
  for (let index = 0; index < times; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount(stages: Stage[]) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <StageList
            tournamentId={84}
            stages={stages}
            progressByStageId={new Map()}
            selectedStageId={null}
            onSelect={onSelect}
            onChanged={() => {}}
          />
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

async function addStageNamed(name: string) {
  const open = [...document.querySelectorAll("button")].find((button) => button.textContent?.trim() === "Add stage");
  await click(open!);
  const input = document.querySelector<HTMLInputElement>("#new-stage-name")!;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, name);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click(document.querySelector<HTMLElement>('[role="dialog"] button[type="submit"]')!);
}

beforeEach(() => {
  vi.clearAllMocks();
  if (root) {
    act(() => root.unmount());
    container.remove();
  }
  getAdminFlow.mockResolvedValue(groupsRead);
  applyChanges.mockResolvedValue(afterSave);
  createStage.mockResolvedValue({ id: 10 });
});

describe("Add stage", () => {
  it("creates the stage, a top-2-per-group filter and both edges in one request", async () => {
    await mount([groups]);

    await addStageNamed("Playoff");

    expect(createStage).not.toHaveBeenCalled();
    expect(applyChanges).toHaveBeenCalledTimes(1);
    const [tournamentId, changes] = applyChanges.mock.calls[0];
    expect(tournamentId).toBe(84);
    expect(changes.nodes).toEqual([
      expect.objectContaining({
        ref: "stage",
        kind: "stage",
        name: "Playoff",
        stage: expect.objectContaining({ name: "Playoff", stage_type: "round_robin", order: 1 })
      }),
      expect.objectContaining({ ref: "filter", kind: "filter", config: { mode: "per_item_top", n: 2 } })
    ]);
    expect(changes.edges).toEqual([
      expect.objectContaining({ source: 1, source_port: "ranking", target: "filter", target_port: "ranking" }),
      expect.objectContaining({ source: "filter", source_port: "passed", target: "stage", target_port: "participants" })
    ]);
    expect(onSelect).toHaveBeenCalledWith(20);
  });

  it("keeps the plain stage create for the first stage", async () => {
    await mount([]);

    await addStageNamed("Groups");

    expect(createStage).toHaveBeenCalledTimes(1);
    expect(applyChanges).not.toHaveBeenCalled();
  });
});
