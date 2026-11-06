// @vitest-environment happy-dom
//
// The registration/formation node controls. Pinned here: each node shows its label and status and offers exactly the
// moves `NODE_TRANSITIONS` allows from there; moves that announce or freeze ask first, the rest are one `transitionNode`
// call; a lone node reads as its kind, several by name; Reopen is withheld once play started; `node` limits it to one.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/error";
import type { TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";
import { FlowNodeControls } from "./FlowNodeControls";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const { transitionNode, notifyError } = vi.hoisted(() => ({ transitionNode: vi.fn(), notifyError: vi.fn() }));

vi.mock("@/services/admin.service", () => ({
  default: { transitionNode: (...args: unknown[]) => transitionNode(...args) }
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), apiError: vi.fn(), error: notifyError } }));
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

const click = (element: Element | null | undefined) =>
  act(async () => {
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });

const tournament = (nodes: TournamentFlowNode[], status = "live") => ({ id: 7, status, flow_nodes: nodes }) as Tournament;
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
  it("asks before Open, and only the confirmation transitions the node", async () => {
    const container = await mount(tournament([node(21, "registration", "draft")]));

    expect(labels()).toEqual(["Open"]);
    await click(document.querySelector("button"));
    expect(transitionNode).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("Open Registration?");

    await click([...document.querySelectorAll("button")].filter((button) => button.textContent?.trim() === "Open").at(-1));
    expect(transitionNode).toHaveBeenCalledWith(21, "open");
    expect(container.textContent).toContain("Registration");
  });

  it("moves without asking where nothing is announced or frozen", async () => {
    await mount(tournament([node(22, "formation", "draft")]));

    await click(document.querySelector("button"));
    expect(transitionNode).toHaveBeenCalledWith(22, "forming");
  });

  it("names a node by its own name only when the tournament has several of its kind", async () => {
    const lone = await mount(
      tournament([node(21, "registration", "draft", "Main intake"), node(22, "formation", "draft", "Main teams")])
    );
    expect(lone.textContent).toContain("Registration");
    expect(lone.textContent).toContain("Teams");
    expect(lone.textContent).not.toContain("Main");

    const several = await mount(
      tournament([node(21, "registration", "draft", "Day 1"), node(23, "registration", "draft", "Day 3")])
    );
    expect(several.textContent).toContain("Day 1");
    expect(several.textContent).toContain("Day 3");
  });

  it("lists every move of each node's current status, registration and formation only", async () => {
    await mount(
      tournament([
        node(21, "registration", "open"),
        node(22, "formation", "forming"),
        node(23, "stage", "draft"),
        node(24, "leaderboard", "final")
      ])
    );

    expect(labels()).toEqual(["Start check-in", "Close", "Back to draft", "Complete"]);
  });

  it("withholds Reopen once a stage has started or the tournament is over", async () => {
    await mount(tournament([node(21, "registration", "closed"), node(23, "stage", "live")]));
    expect(labels()).toEqual([]);

    document.body.innerHTML = "";
    await mount(tournament([node(21, "registration", "closed")], "completed"));
    expect(labels()).toEqual([]);

    document.body.innerHTML = "";
    await mount(tournament([node(21, "registration", "closed"), node(23, "stage", "draft")]));
    expect(labels()).toEqual(["Reopen"]);
  });

  it("limits itself to the given node", async () => {
    const forming = node(22, "formation", "completed");
    await mount(tournament([node(21, "registration", "draft"), forming]), { node: forming });

    expect(labels()).toEqual(["Reopen"]);
  });

  it("shows the status but no moves without tournament.update", async () => {
    const container = await mount(tournament([node(21, "registration", "draft")]), { canUpdate: false });

    expect(container.querySelector("button")).toBeNull();
    expect(container.textContent).toContain("Draft");
  });

  it("reports a flow refusal as its translated message", async () => {
    transitionNode.mockRejectedValue(new ApiError(409, [{ code: "input_not_final", msg: "An input of this node is not final yet" }]));
    await mount(tournament([node(22, "formation", "draft")]));

    await click(document.querySelector("button"));
    expect(notifyError).toHaveBeenCalledWith(expect.stringContaining("close registration before forming teams"));
  });
});
