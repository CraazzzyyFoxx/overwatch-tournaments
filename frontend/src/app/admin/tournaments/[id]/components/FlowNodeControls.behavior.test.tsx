// @vitest-environment happy-dom
//
// The hub header's node controls. Pinned here: each registration/formation node shows its name and status and offers
// exactly the moves `NODE_TRANSITIONS` allows from there; a click is one `transitionNode` call; `node` limits it to one.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";
import { FlowNodeControls } from "./FlowNodeControls";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const transitionNode = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: { transitionNode: (...args: unknown[]) => transitionNode(...args) }
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), apiError: vi.fn() } }));
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const { default: en } = await import("@/i18n/messages/en.json");
  return {
    ...actual,
    useTranslations: (namespace?: string) =>
      actual.createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
    useLocale: () => "en"
  };
});

function node(id: number, kind: string, status: string, name = `Node ${id}`): TournamentFlowNode {
  return { id, kind, name, status, config: {}, schedule: [], stage_id: null } as unknown as TournamentFlowNode;
}

const tournament = (...nodes: TournamentFlowNode[]) => ({ id: 7, flow_nodes: nodes }) as Tournament;
const mounted: Root[] = [];

async function mount(subject: Tournament, props: { node?: TournamentFlowNode; canUpdate?: boolean } = {}) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mounted.push(root);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <FlowNodeControls tournament={subject} node={props.node} canUpdate={props.canUpdate ?? true} />
      </QueryClientProvider>
    );
  });
  return container;
}

const labels = () => [...document.querySelectorAll("button")].map((node) => node.textContent?.trim());

beforeEach(() => {
  transitionNode.mockReset().mockResolvedValue({});
});

afterEach(async () => {
  await act(async () => {
    for (const root of mounted.splice(0)) root.unmount();
  });
  document.body.innerHTML = "";
});

describe("FlowNodeControls", () => {
  it("offers exactly Open on a draft registration, and a click transitions the node", async () => {
    const container = await mount(tournament(node(21, "registration", "draft", "Day 1")));

    expect(container.textContent).toContain("Day 1");
    expect(labels()).toEqual(["Open"]);
    await act(async () => {
      document.querySelector("button")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(transitionNode).toHaveBeenCalledWith(21, "open");
  });

  it("lists every move of each node's current status, registration and formation only", async () => {
    await mount(
      tournament(
        node(21, "registration", "open"),
        node(22, "formation", "forming"),
        node(23, "stage", "draft"),
        node(24, "leaderboard", "final")
      )
    );

    expect(labels()).toEqual(["Start check-in", "Close", "Back to draft", "Complete"]);
  });

  it("limits itself to the given node", async () => {
    const forming = node(22, "formation", "completed");
    await mount(tournament(node(21, "registration", "draft"), forming), { node: forming });

    expect(labels()).toEqual(["Reopen"]);
  });

  it("renders nothing without tournament.update", async () => {
    const container = await mount(tournament(node(21, "registration", "draft")), { canUpdate: false });

    expect(container.querySelector("button")).toBeNull();
  });
});
